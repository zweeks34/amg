"""The fill-up map's data: towns in the US and Canada, and each state's and province's outline.

Both are built by scripts/build_places.py from the sources in SOURCES.md and
read once, on first use. Nothing here reaches the network.
"""

from __future__ import annotations

import gzip
import json
from functools import cache
from pathlib import Path

HERE = Path(__file__).parent


@cache
def towns() -> dict[tuple[str, str], list[tuple[float, float]]]:
    """Each (state, town key) with where it is, (latitude, longitude): one, or for a name more than one town in the
    state has, each of them, the biggest first."""
    found: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for line in gzip.decompress((HERE / "places.tsv.gz").read_bytes()).decode("utf-8").splitlines():
        state, key, lat, lon = line.split("\t")
        found.setdefault((state, key), []).append((float(lat), float(lon)))
    return found


@cache
def regions() -> dict[str, dict]:
    """Each state and province by its code: name, country, path (SVG, in the map's kilometres), box
    [left, top, right, bottom], and label [x, y], which is also where a fill-up that names only the state goes."""
    return json.loads((HERE / "regions.json").read_text(encoding="utf-8"))
