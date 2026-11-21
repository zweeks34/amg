"""Build the fill-up map's data from downloaded sources: the town list and the state and province outlines.

    python scripts/build_places.py DOWNLOADS

DOWNLOADS holds the four files src/amg/geo/SOURCES.md names, each as it
was downloaded:

    2024_Gaz_place_national.zip     Census Gazetteer, places
    2024_Gaz_cousubs_national.zip   Census Gazetteer, county subdivisions (townships)
    CA.zip                          GeoNames, Canada
    ne_50m_admin_1_states_provinces.geojson   Natural Earth 5.1.2

It writes src/amg/geo/places.tsv.gz (state, town key, latitude, longitude;
a line each for a name more than one town in a state has, the biggest first)
and src/amg/geo/regions.json (each state's and province's outline as SVG path
data in the map's kilometres, its box and where its label goes). Run it again
to refresh them; nothing else reads the downloads.
"""

from __future__ import annotations

import gzip
import io
import json
import math
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from amg.engine.geo import project, town_key  # noqa: E402

OUT = ROOT / "src" / "amg" / "geo"
US = ("AK AL AR AZ CA CO CT DC DE FL GA HI IA ID IL IN KS KY LA MA MD ME MI MN MO MS MT NC ND NE NH NJ NM NV NY OH OK "
      "OR PA RI SC SD TN TX UT VA VT WA WI WV WY").split()
# GeoNames' first-level codes for Canada's provinces and territories.
PROVINCES = {"01": "AB", "02": "BC", "03": "MB", "04": "NB", "05": "NL", "07": "NS", "08": "ON", "09": "PE",
             "10": "QC", "11": "SK", "12": "YT", "13": "NT", "14": "NU"}
# What the Census writes after a name: "Abbeville city", "Hamilton township", "Nashville-Davidson metropolitan
# government (balance)". Longest first, so "city and borough" goes before "borough".
SUFFIXES = sorted([
    "city and borough", "consolidated government", "metropolitan government", "unified government",
    "urban county", "city", "town", "village", "borough", "cdp", "township", "municipality", "plantation", "ccd",
    "comunidad", "zona urbana", "barrio", "barrio-pueblo", "charter township", "gore", "grant", "location",
    "purchase", "district", "precinct", "unorganized territory", "corporation", "municipio", "census subarea",
    "reservation", "county", "island",
], key=len, reverse=True)
# Rank, when a name comes up more than once in a state: an incorporated place, then a township, then the rest.
PLACE, TOWNSHIP, OTHER = 0, 1, 2


def bare(name: str) -> str:
    """A Census name without what it is: "Hamilton township" → "Hamilton"."""
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    for _ in range(2):
        for suffix in SUFFIXES:
            if name.lower().endswith(" " + suffix):
                name = name[: -len(suffix) - 1].strip()
                break
    return name


def census(path: Path, kind: int) -> list[tuple]:
    rows = []
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.endswith(".txt"))
        with z.open(name) as fh:
            lines = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
            header = [h.strip() for h in next(lines).split("\t")]
            at = {h: i for i, h in enumerate(header)}
            for line in lines:
                cells = [c.strip() for c in line.split("\t")]
                state = cells[at["USPS"]]
                if state not in US:
                    continue
                raw = cells[at["NAME"]]
                key = town_key(bare(raw))
                if not key:
                    continue
                active = cells[at["FUNCSTAT"]] in ("A", "B", "C", "G", "N")
                rank = kind if active else OTHER
                if kind == PLACE and raw.endswith(" CDP"):
                    rank = OTHER
                rows.append((state, key, rank, -float(cells[at["ALAND"]] or 0),
                             float(cells[at["INTPTLAT"]]), float(cells[at["INTPTLONG"]])))
    return rows


def geonames(path: Path) -> list[tuple]:
    rows = []
    with zipfile.ZipFile(path) as z, z.open("CA.txt") as fh:
        for line in io.TextIOWrapper(fh, encoding="utf-8"):
            cells = line.rstrip("\n").split("\t")
            if cells[6] != "P" or cells[10] not in PROVINCES:
                continue
            population = int(cells[14] or 0)
            if population <= 0 and not cells[7].startswith(("PPLA", "PPLC")):
                continue
            for name in {cells[1], cells[2]}:
                key = town_key(name)
                if key:
                    rows.append((PROVINCES[cells[10]], key, PLACE, -population, float(cells[4]), float(cells[5])))
    return rows


def towns(downloads: Path) -> list[tuple]:
    found = (census(downloads / "2024_Gaz_place_national.zip", PLACE)
             + census(downloads / "2024_Gaz_cousubs_national.zip", TOWNSHIP)
             + geonames(downloads / "CA.zip"))
    # Every town of the best rank a name has in its state: Hamilton, NJ is two townships, and the app places a
    # fill-up at the one nearest your others. The biggest first, so with nothing to go on it's the one used.
    best: dict[tuple[str, str], list[tuple]] = {}
    for row in sorted(found, key=lambda r: (r[0], r[1], r[2], r[3])):
        same = best.setdefault((row[0], row[1]), [])
        if (not same or same[0][2] == row[2]) and all(abs(row[4] - o[4]) + abs(row[5] - o[5]) > 0.01 for o in same):
            same.append(row)
    return [(state, key, lat, lon) for (state, key), rows in sorted(best.items()) for *_, lat, lon in rows]


# ---------- Outlines ----------

TOLERANCE = 1.0      # km: a point nearer than this to the line through its neighbours is dropped
SMALLEST = 15.0      # km²: a smaller island is left off, unless it's all there is


def simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Douglas–Peucker, without recursion."""
    if len(points) < 4:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        (x1, y1), (x2, y2) = points[first], points[last]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1e-9
        far, at = 0.0, None
        for i in range(first + 1, last):
            x, y = points[i]
            d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / length
            if d > far:
                far, at = d, i
        if at is not None and far > tolerance:
            keep[at] = True
            stack += [(first, at), (at, last)]
    return [p for p, k in zip(points, keep) if k]


def simplify_ring(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """A closed ring simplified as two lines: from its first point to the point farthest from it, and back. (As one
    line it would start and end on the same point, and every other point would be measured against nothing.)"""
    if points[0] == points[-1]:
        points = points[:-1]
    if len(points) < 4:
        return points
    x0, y0 = points[0]
    far = max(range(len(points)), key=lambda i: (points[i][0] - x0) ** 2 + (points[i][1] - y0) ** 2)
    there = simplify(points[: far + 1], tolerance)
    back = simplify(points[far:] + points[:1], tolerance)
    return there + back[1:-1]


def area(points: list[tuple[float, float]]) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))) / 2


def regions(geojson: Path) -> dict:
    data = json.loads(geojson.read_text(encoding="utf-8"))
    found = {}
    for feature in data["features"]:
        p = feature["properties"]
        if p.get("iso_a2") not in ("US", "CA"):
            continue
        code = p["postal"]
        geometry = feature["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        rings = []
        for polygon in polygons:
            for ring in polygon[:1]:          # outer rings only: lakes inside a state aren't drawn
                projected = [project(lat, lon) for lon, lat in ring]
                rings.append((area(projected), simplify_ring(projected, TOLERANCE)))
        rings.sort(key=lambda r: -r[0])
        kept = [ring for size, ring in rings if size >= SMALLEST and len(ring) >= 4] or [rings[0][1]]
        path = "".join("M" + " ".join(f"{x:.0f},{y:.0f}" for x, y in ring) + "Z" for ring in kept)
        xs = [x for ring in kept for x, _ in ring]
        ys = [y for ring in kept for _, y in ring]
        lx, ly = project(p["latitude"], p["longitude"])
        found[code] = {"name": p["name"], "country": p["iso_a2"], "path": path,
                       "box": [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))],
                       "label": [round(lx), round(ly)]}
    return dict(sorted(found.items()))


def main(downloads: Path) -> None:
    rows = towns(downloads)
    text = "".join(f"{state}\t{key}\t{lat:.4f}\t{lon:.4f}\n" for state, key, lat, lon in rows)
    (OUT / "places.tsv.gz").write_bytes(gzip.compress(text.encode("utf-8"), mtime=0))
    outlines = regions(downloads / "ne_50m_admin_1_states_provinces.geojson")
    (OUT / "regions.json").write_text(json.dumps(outlines, separators=(",", ":")), encoding="utf-8")
    print(f"{len(rows):,} towns; {len(outlines)} states and provinces")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
