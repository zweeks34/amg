"""Finding fill-ups in a car's log: narrow it by date, place, station, what needs a look, the kind of fill and its note,
and sort it.

The filters live in the address bar, so a narrowed log is a link you can keep. They are read forgivingly, as a report's
are: a date that isn't one is no date, From after To is taken the right way round, and a state, city or station the log
doesn't hold is dropped rather than left filtering out of sight.

A row's economy and its Unusual flag depend on the fills around it, so the log is worked out whole first
(``fuel_status.log_rows``) and the rows are chosen from that: a filter decides what shows, never what a row says.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from urllib.parse import urlencode

ANCHOR = "log-heading"      # a narrowed log opens here, not at the top of the page
NEEDS_A_LOOK = {
    "any": "Anything missing or unusual",
    "location": "No location",
    "station": "No station",
    "cost": "No cost",
    "unusual": "Unusual",
}
FILLS = ("full", "partial")
# Each sort that goes by a figure: that figure, and whether the highest comes first.
_BY_FIGURE = {
    "price_low": ("unit_cents", False),
    "price_high": ("unit_cents", True),
    "cost": ("cost_cents", True),
    "economy_high": ("economy_value", True),
    "economy_low": ("economy_value", False),
}
NEWEST = "newest"


def sorts(economy_name: str) -> dict[str, str]:
    """The sorts on offer, as the dropdown words them for a car's units."""
    return {
        NEWEST: "Newest first",
        "oldest": "Oldest first",
        "price_low": "Lowest price",
        "price_high": "Highest price",
        "cost": "Highest cost",
        "economy_high": f"Best {economy_name}",
        "economy_low": f"Lowest {economy_name}",
    }


@dataclass(frozen=True)
class Finder:
    start: str | None = None    # ISO dates, both included
    end: str | None = None
    state: str = ""
    city: str = ""
    station: str = ""
    look: str = ""              # a key of NEEDS_A_LOOK
    fill: str = ""              # one of FILLS
    note: str = ""
    sort: str = NEWEST

    @classmethod
    def read(cls, params: Mapping[str, str]) -> Finder:
        """From the address bar, forgivingly: anything that isn't a choice is no choice."""
        first, last = _day(params.get("from")), _day(params.get("to"))
        if first and last and first > last:
            first, last = last, first
        look, fill, sort = params.get("look"), params.get("fill"), params.get("sort")
        return cls(first, last, _tidy(params.get("state")), _tidy(params.get("city")), _tidy(params.get("station")),
                   look if look in NEEDS_A_LOOK else "", fill if fill in FILLS else "", _tidy(params.get("note")),
                   sort if sort == "oldest" or sort in _BY_FIGURE else NEWEST)

    def within(self, options: dict) -> Finder:
        """Drop a state, city or station the log doesn't hold, so nothing filters out of sight. The city has to be in
        the state, if one's chosen."""
        state = self.state if self.state in options["states"] else ""
        city = next((town["name"] for town in options["cities"]
                     if _key(town["name"]) == _key(self.city) and (not state or town["state"] == state)), "")
        station = next((name for name in options["stations"] if _key(name) == _key(self.station)), "")
        return replace(self, state=state, city=city, station=station)

    @property
    def on(self) -> int:
        """How many filters are narrowing the log. Sorting isn't one."""
        return sum(bool(part) for part in (self.start, self.end, self.state, self.city, self.station, self.look,
                                           self.fill, self.note))

    @property
    def active(self) -> bool:
        return self.on > 0

    @property
    def changed(self) -> bool:
        """Is this anything but the log as it first shows? Sorting counts here."""
        return self.active or self.sort != NEWEST

    def query(self, **more: str | int) -> str:
        """These filters as a link's query string, with anything more it needs; nothing when there's nothing to say."""
        pairs = (("from", self.start), ("to", self.end), ("state", self.state), ("city", self.city),
                 ("station", self.station), ("look", self.look), ("fill", self.fill), ("note", self.note),
                 ("sort", "" if self.sort == NEWEST else self.sort), *more.items())
        params = {key: value for key, value in pairs if value}
        return f"?{urlencode(params)}" if params else ""

    def url(self, vehicle_id: int, **more: str | int) -> str:
        """The car's fuel page with this log showing. Built from what was checked, so it can only ever lead there."""
        return f"/vehicles/{vehicle_id}/fuel{self.query(**more)}" + (f"#{ANCHOR}" if self.changed else "")

    def csv_url(self, vehicle_id: int) -> str:
        return f"/vehicles/{vehicle_id}/fuel.csv{self.query()}"

    def cleared(self, vehicle_id: int) -> str:
        """The whole log again, in the same order."""
        return f"/vehicles/{vehicle_id}/fuel{Finder(sort=self.sort).query()}#{ANCHOR}"


def choices(rows: list[dict]) -> dict:
    """What a car's log holds to filter by: each station and city once whatever its capitals, as last written (the rows
    are newest first), and each city with every state it's in."""
    stations: dict[str, str] = {}
    spelled: dict[str, str] = {}
    for row in rows:
        if row["station"]:
            stations.setdefault(_key(row["station"]), _tidy(row["station"]))
        if row["city"]:
            spelled.setdefault(_key(row["city"]), _tidy(row["city"]))
    towns = {(spelled[_key(row["city"])], row["state"]) for row in rows if row["city"]}
    return {
        "states": sorted({row["state"] for row in rows if row["state"]}),
        "cities": [{"name": name, "state": state} for name, state in sorted(towns, key=lambda t: (t[0].lower(), t[1]))],
        "stations": sorted(stations.values(), key=str.lower),
    }


def find(rows: list[dict], finder: Finder) -> list[dict]:
    """The log's rows to show, in order. ``rows`` are newest first, as the log has them."""
    return _sorted([row for row in rows if _matches(row, finder)], finder.sort)


# ---------- Helpers ----------


def _day(value: str | None) -> str | None:
    try:
        return date.fromisoformat((value or "").strip()).isoformat()
    except ValueError:
        return None


def _tidy(value: str | None) -> str:
    return " ".join((value or "").split())


def _key(value: str) -> str:
    return _tidy(value).lower()


def _matches(row: dict, finder: Finder) -> bool:
    return ((not finder.start or row["day"] >= finder.start)
            and (not finder.end or row["day"] <= finder.end)
            and (not finder.state or row["state"] == finder.state)
            and (not finder.city or _key(row["city"]) == _key(finder.city))
            and (not finder.station or _key(row["station"]) == _key(finder.station))
            and (not finder.look or _needs_a_look(row, finder.look))
            and (not finder.fill or row["partial"] == (finder.fill == "partial"))
            and all(word in row["note"].lower() for word in finder.note.lower().split()))


def _needs_a_look(row: dict, look: str) -> bool:
    """Is this fill missing what ``look`` asks about? A charge at home is missing no place: you know where it was."""
    at_home = row["place"] == "Home"
    found = {
        "location": not at_home and not row["city"] and not row["state"],
        "station": not at_home and not row["station"],
        "cost": row["cost_cents"] is None,
        "unusual": row["unusual"],
    }
    return any(found.values()) if look == "any" else found[look]


def _sorted(rows: list[dict], sort: str) -> list[dict]:
    """In the order asked for: rows without the figure go last, and rows that tie stay newest first."""
    if sort == NEWEST:
        return rows
    if sort == "oldest":
        return rows[::-1]
    figure, highest = _BY_FIGURE[sort]
    known = [row for row in rows if row[figure] is not None]
    return sorted(known, key=lambda row: row[figure], reverse=highest) + [row for row in rows if row[figure] is None]
