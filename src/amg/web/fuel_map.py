"""Where you filled up: every fill-up (or charge) placed at its town, on a map drawn from the state outlines.

A fill-up says its city and state, not where the pump was, so it goes at the
middle of its town, found in the town list (``amg.geo``) by its name as
``engine.geo.town_key`` reads it. A name more than one town in the state has
(two Hamilton townships in NJ) goes at the one nearest your other fill-ups,
and says so. A town the list doesn't know, or a fill-up that names only its
state, goes at the middle of the state, and says so. One with no state isn't
placed: the page counts it and points to the log's No location.

The filters are in the address, read forgivingly as the reports' are, so a
narrowed map is a link. Fuel and charging are never mixed: a gallon's price
and a kWh's don't belong on one scale.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from urllib.parse import urlencode

from .. import geo
from ..engine.geo import project, town_key
from . import brands
from .fuel_finder import Finder
from .fuel_status import UNITS, price_words

ENERGIES = {"gas": "Fuel", "electric": "Charging"}
NO_STATION = "none"
SORTS = {"fills": "Most visits", "spent": "Most spent", "price_low": "Lowest price", "price_high": "Highest price",
         "last": "Most recent", "name": "A to Z"}
TONES = 5                   # the dots' price shades, cheapest to dearest
ASPECT = 1.6                # the map's width over its height
NAMED_WITHIN = 600.0        # km across: a map this close names its towns beside their dots
CLOSEST = 200.0             # km across: the outlines are 1:50m, so closer than this their borders are visibly off
LOWER_48 = [code for code in ("WA", "OR", "CA", "NV", "ID", "MT", "WY", "UT", "AZ", "NM", "CO", "ND", "SD", "NE",
                              "KS", "OK", "TX", "MN", "IA", "MO", "AR", "LA", "WI", "IL", "MI", "IN", "OH", "KY",
                              "TN", "MS", "AL", "GA", "FL", "SC", "NC", "VA", "WV", "MD", "DE", "PA", "NJ", "NY",
                              "CT", "RI", "MA", "VT", "NH", "ME", "DC")]


@dataclass(frozen=True)
class MapFilters:
    energy: str = "gas"
    car: int | None = None
    start: str | None = None
    end: str | None = None
    brand: str = ""             # a brand's name, a station as typed, or NO_STATION
    state: str = ""
    city: str = ""
    sort: str = "fills"

    @classmethod
    def read(cls, params: Mapping[str, str], energies: list[str]) -> MapFilters:
        first, last = _day(params.get("from")), _day(params.get("to"))
        if first and last and first > last:
            first, last = last, first
        energy = params.get("energy", "")
        car = (params.get("car") or "").strip()
        return cls(energy if energy in energies else (energies[0] if energies else "gas"),
                   int(car) if car.isascii() and car.isdigit() else None, first, last, _tidy(params.get("brand")),
                   _tidy(params.get("state")).upper(), _tidy(params.get("city")),
                   params.get("sort", "") if params.get("sort", "") in SORTS else "fills")

    def within(self, options: dict) -> MapFilters:
        """Drop a car, brand, state or city the map doesn't hold, so nothing filters out of sight."""
        state = self.state if self.state in options["states"] else ""
        city = next((town["name"] for town in options["cities"]
                     if town_key(town["name"]) == town_key(self.city) and (not state or town["state"] == state)), "")
        return replace(self, car=self.car if self.car in [c["id"] for c in options["cars"]] else None,
                       brand=next((b["value"] for b in options["brands"] if b["value"].lower() == self.brand.lower()),
                                  ""),
                       state=state, city=city)

    @property
    def active(self) -> bool:
        return bool(self.car or self.start or self.end or self.brand or self.state or self.city)

    def url(self, **changes) -> str:
        target = replace(self, **changes)
        pairs = [("energy", target.energy if target.energy != "gas" else ""), ("car", target.car),
                 ("from", target.start), ("to", target.end), ("brand", target.brand), ("state", target.state),
                 ("city", target.city), ("sort", target.sort if target.sort != "fills" else "")]
        params = {key: value for key, value in pairs if value}
        return "/fuel/map" + (f"?{urlencode(params)}" if params else "")

    def cleared(self) -> str:
        return MapFilters(energy=self.energy).url()


# ---------- What a fill-up is ----------


def brand_of(station: str) -> tuple[str, str]:
    """A station's brand to filter by: (value, its words). A brand AMG knows by name, else the station as typed, else
    no station."""
    station = _tidy(station)
    if not station:
        return NO_STATION, "No station"
    known = brands.recognise(station)
    return (known.name, known.name) if known else (station, station)


def options(rows: list[dict], energy: str) -> dict:
    """What the map's fills hold to filter by, for one energy: cars, brands (most visited first), states, and each
    city with its state, as last written (the rows are newest first)."""
    mine = [row for row in rows if row["energy"] == energy]
    cars: dict[int, dict] = {}
    counts: dict[str, list] = {}
    spelled: dict[tuple[str, str], str] = {}
    for row in mine:
        cars.setdefault(row["vehicle_id"], {"id": row["vehicle_id"], "name": row["car_name"]})
        value, words = brand_of(row["station"])
        entry = counts.setdefault(value.lower(), [value, words, 0])
        entry[2] += 1
        if row["station_city"] and row["station_state"]:
            spelled.setdefault((town_key(row["station_city"]), row["station_state"]), _tidy(row["station_city"]))
    return {
        "cars": sorted(cars.values(), key=lambda c: c["name"].lower()),
        "brands": [{"value": value, "label": words, "count": count}
                   for value, words, count in sorted(counts.values(), key=lambda e: (e[0] == NO_STATION, -e[2], e[1].lower()))],
        "states": sorted({row["station_state"] for row in mine if row["station_state"]}),
        "cities": [{"name": name, "state": state}
                   for (_, state), name in sorted(spelled.items(), key=lambda item: (item[1].lower(), item[0][1]))],
    }


def chosen(rows: list[dict], filters: MapFilters) -> list[dict]:
    def keeps(row: dict) -> bool:
        if row["energy"] != filters.energy or (filters.car and row["vehicle_id"] != filters.car):
            return False
        if (filters.start and row["filled_on"] < filters.start) or (filters.end and row["filled_on"] > filters.end):
            return False
        if filters.brand and brand_of(row["station"])[0].lower() != filters.brand.lower():
            return False
        if filters.state and row["station_state"] != filters.state:
            return False
        return not filters.city or town_key(row["station_city"]) == town_key(filters.city)
    return [row for row in rows if keeps(row)]


# ---------- Where it goes ----------


@dataclass
class Place:
    state: str
    key: str                    # the town's, or "" for the middle of the state
    name: str                   # "Trenton, NJ", or "NJ" for the middle of it
    x: float
    y: float
    how: str                    # town, guessed (one of several of that name) or state (the middle of it)
    rows: list[dict]

    @property
    def count(self) -> int:
        return len(self.rows)

    @property
    def spent(self) -> int:
        return sum(row["cost_cents"] or 0 for row in self.rows)

    @property
    def price(self) -> float | None:
        """Cents a gallon (or kWh) over the fills with a cost."""
        priced = [row for row in self.rows if row["cost_cents"] is not None and row["quantity"]]
        quantity = sum(row["quantity"] for row in priced)
        return sum(row["cost_cents"] for row in priced) / quantity if quantity else None

    @property
    def last(self) -> str:
        return max(row["filled_on"] for row in self.rows)

    def cars(self) -> list[dict]:
        found: dict[int, str] = {}
        for row in self.rows:
            found.setdefault(row["vehicle_id"], row["car_name"])
        return [{"id": car_id, "name": name} for car_id, name in found.items()]


def candidates(city: str, state: str) -> list[tuple[float, float]]:
    """The towns a city and state could be, as map points; none when the list doesn't know it."""
    return [project(lat, lon) for lat, lon in geo.towns().get((state, town_key(city)), [])] if city else []


def place(rows: list[dict], everyone: list[dict] | None = None) -> tuple[list[Place], list[dict]]:
    """The rows grouped by where they go, and the rows with no state to go by. A name with more than one town goes
    at the one nearest the middle of your fills whose town is certain (``everyone``'s, so a filter can't move it)."""
    regions = geo.regions()
    certain = [points[0] for row in (everyone or rows)
               if len(points := candidates(row["station_city"], row["station_state"])) == 1]
    home = (statistics.median(x for x, _ in certain), statistics.median(y for _, y in certain)) if certain else None
    found: dict[tuple[str, str], Place] = {}
    unplaced = []
    for row in rows:
        state, city = row["station_state"], _tidy(row["station_city"])
        if state not in regions:
            unplaced.append(row)
            continue
        points = candidates(city, state)
        if points:
            key, how = town_key(city), "town"
            if len(points) > 1:
                how = "guessed"
                if home:
                    points = [min(points, key=lambda p: (p[0] - home[0]) ** 2 + (p[1] - home[1]) ** 2)]
            x, y = points[0]
            name = f"{city}, {state}"
        else:
            key, how = "", "state"
            x, y = regions[state]["label"]
            name = regions[state]["name"]
        spot = found.get((state, key))
        if spot is None:
            spot = found[(state, key)] = Place(state, key, name, x, y, how, [])
        spot.rows.append(row)
    return list(found.values()), unplaced


def ordered(places: list[Place], sort: str) -> list[Place]:
    keys = {
        "fills": lambda p: (-p.count, p.name.lower()),
        "spent": lambda p: (-p.spent, p.name.lower()),
        "price_low": lambda p: (p.price is None, p.price or 0, p.name.lower()),
        "price_high": lambda p: (p.price is None, -(p.price or 0), p.name.lower()),
        "last": lambda p: (_negate(p.last), p.name.lower()),
        "name": lambda p: p.name.lower(),
    }
    return sorted(places, key=keys[sort])


def _negate(day: str) -> tuple:
    return tuple(-int(part) for part in day.split("-"))


# ---------- The map ----------


def drawing(places: list[Place], state: str = "") -> dict:
    """The SVG: its viewBox (around the dots, else the state asked for, else the lower 48, kept to ASPECT), the
    outlines that show in it, each state's code where there's room, and the dots, sized by visits and shaded by
    price, each named once the map is zoomed in close. Everything is in the map's kilometres; strokes don't
    scale."""
    regions = geo.regions()
    if places:
        xs, ys = [p.x for p in places], [p.y for p in places]
        box = [min(xs), min(ys), max(xs), max(ys)]
    elif state in regions:
        box = regions[state]["box"]
    else:
        box = _union([regions[code]["box"] for code in LOWER_48])
    left, top, right, bottom = _framed(box)
    width = right - left
    close = width <= NAMED_WITHIN
    shown = [{"code": code, "name": r["name"], "path": r["path"],
              "visited": any(p.state == code for p in places), "picked": code == state}
             for code, r in regions.items() if _meets(r["box"], (left, top, right, bottom))]
    labels = [{"code": code, "x": r["label"][0], "y": r["label"][1]}
              for code, r in regions.items()
              if left < r["label"][0] < right and top < r["label"][1] < bottom
              and (r["box"][2] - r["box"][0]) > width * 0.05]
    most = max((p.count for p in places), default=1)
    prices = [p.price for p in places if p.price is not None]
    low, high = (min(prices), max(prices)) if prices else (0.0, 0.0)
    dots = []
    for index, p in enumerate(sorted(places, key=lambda p: -p.count)):   # big ones underneath
        tone = None
        if p.price is not None and high > low:
            tone = min(TONES - 1, int((p.price - low) / (high - low) * TONES))
        dots.append({"id": _anchor(p), "x": round(p.x, 1), "y": round(p.y, 1),
                     "r": round(width * (0.006 + 0.01 * math.sqrt(p.count / most)), 2),
                     "tone": tone, "how": p.how, "title": f"{p.name}: {p.count} visit{'s' if p.count != 1 else ''}",
                     "name": (p.name.split(",")[0] if p.how != "state" else "") if close else ""})
    _make_room(dots, width * 0.024)
    return {"view": f"{left:.0f} {top:.0f} {width:.0f} {bottom - top:.0f}", "regions": shown, "labels": labels,
            "dots": dots, "font": round(width * 0.02, 1), "town_font": round(width * 0.024, 1), "low": low, "high": high, "toned": high > low}


def _make_room(dots: list[dict], font: float) -> None:
    """Leave a town's name off where it would run into one already placed: the dots come busiest first, so the
    busiest towns keep theirs. A name is guessed at about 0.55 of the font size a letter."""
    placed: list[tuple[float, float, float, float]] = []
    for dot in dots:
        if not dot["name"]:
            continue
        x = dot["x"] + dot["r"] * 1.3
        box = (x, dot["y"] - font * 0.6, x + len(dot["name"]) * font * 0.55, dot["y"] + font * 0.6)
        if any(box[0] < b[2] and box[2] > b[0] and box[1] < b[3] and box[3] > b[1] for b in placed):
            dot["name"] = ""
        else:
            placed.append(box)


def _framed(box: list[float]) -> tuple[float, float, float, float]:
    """A box with room around it, at least CLOSEST across, widened or heightened to ASPECT."""
    left, top, right, bottom = box
    cx, cy = (left + right) / 2, (top + bottom) / 2
    width, height = max((right - left) * 1.3, CLOSEST), max((bottom - top) * 1.3, CLOSEST / ASPECT)
    if width / height < ASPECT:
        width = height * ASPECT
    else:
        height = width / ASPECT
    return cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2


def _union(boxes: list[list[float]]) -> list[float]:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _meets(box: list[float], view: tuple[float, float, float, float]) -> bool:
    return box[0] < view[2] and box[2] > view[0] and box[1] < view[3] and box[3] > view[1]


def _anchor(p: Place) -> str:
    return "town-" + p.state.lower() + ("-" + p.key.replace(" ", "-") if p.key else "")


# ---------- For the page ----------


def rows_for_table(places: list[Place], energy: str) -> list[dict]:
    units = UNITS[energy]
    return [{
        "id": _anchor(p), "name": p.name, "how": p.how, "count": p.count, "spent": p.spent,
        "price": price_words(p.price, units) or "", "last": p.last,
        "logs": [{"car": car["name"], "url": Finder(state=p.state, city=_city_of(p)).url(car["id"])}
                 for car in p.cars()],
        "fills": [{"day": row["filled_on"], "car": row["car_name"], "station": row["station"],
                   "quantity": row["quantity"], "cost": row["cost_cents"]} for row in p.rows],
    } for p in places]


def _city_of(p: Place) -> str:
    return _tidy(p.rows[0]["station_city"]) if p.key else ""


def summary(places: list[Place], unplaced: list[dict], energy: str) -> dict:
    fill = UNITS[energy].fill
    count = sum(p.count for p in places)
    towns = [p for p in places if p.how != "state"]
    states = {p.state for p in places}
    middle = sum(p.count for p in places if p.how == "state")
    guessed = sum(p.count for p in places if p.how == "guessed")
    canadian = any(geo.regions()[s]["country"] == "CA" for s in states)
    american = any(geo.regions()[s]["country"] == "US" for s in states)
    where = " or ".join(word for word, used in (("state", american), ("province", canadian)) if used) or "state"
    plural = "s" if len(states) != 1 else ""
    where = where.replace("state", "state" + plural).replace("province", "province" + plural)
    parts = [f"{count} {fill}{'s' if count != 1 else ''} in {len(towns)} town{'s' if len(towns) != 1 else ''}"
             f" across {len(states)} {where}" if count else f"No {fill}s placed"]
    if middle:
        parts.append(f"{middle} at the middle of the state")
    if guessed:
        parts.append(f"{guessed} in a town whose name the state has more than once")
    if unplaced:
        parts.append(f"{len(unplaced)} with no location")
    cars: dict[int, list] = {}
    for row in unplaced:
        cars.setdefault(row["vehicle_id"], [row["car_name"], 0])[1] += 1
    return {"line": " · ".join(parts),
            "unplaced": [{"car": name, "count": n, "url": Finder(look="location").url(car_id)}
                         for car_id, (name, n) in cars.items()]}


def _day(value: str | None) -> str | None:
    try:
        return date.fromisoformat((value or "").strip()).isoformat()
    except ValueError:
        return None


def _tidy(value: str | None) -> str:
    return " ".join((value or "").split())
