"""What a car's pages say about its schedule: next up, the interval chart, the garage line.

The gap engine (engine/schedule.py) decides; this turns its answer into what
a person reads — "1,200 mi overdue", "in 700 mi · by Nov 12" — and into the
chart _chart.html draws. A done mark sits where the work was done, a missed
or upcoming one where it fell (or falls) due.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from ..engine.odometer import Odometer
from ..engine.schedule import Car, Item, ItemStatus, Occurrence, Service, assess
from ..repo import odometer as readings
from ..repo import schedules, services
from .service_icons import icon_for

NEXT_UP = 6                 # rows in the next-up list, besides every overdue and due-soon one
READING_DAYS = 60           # a reading older than this is asked for, on a car with jobs due by mileage
TICKS = (5_000, 10_000, 15_000, 20_000, 25_000, 50_000)
MAX_SEGMENTS = 8


@dataclass
class CarStatus:
    vehicle_id: int
    items: dict[int, dict]          # schedule item rows by id: name, codes, category, …
    statuses: list[ItemStatus]
    odometer: Odometer
    today: date
    today_miles: int | None
    services: list[Service] = field(default_factory=list)   # the confirmed services the engine read

    @property
    def missed(self) -> int:
        return sum(len(s.missed) for s in self.statuses)

    def count(self, state: str) -> int:
        return sum(1 for s in self.statuses if s.current and s.current.status == state)

    @property
    def needs_reading(self) -> list[str]:
        return [s.item.name for s in self.statuses if s.needs_reading]


def _day(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def odometer_for(conn: sqlite3.Connection, car) -> Odometer:
    """The car's odometer model: every reading, and the in-service date at zero miles."""
    return Odometer(((date.fromisoformat(p["read_on"]), p["miles"]) for p in readings.points(conn, car["id"])),
                    in_service=_day(car["in_service_date"]))


def engine_car(car) -> Car:
    """What the gap engine needs to know about a car: when it was new, when you got it, and how it's driven."""
    return Car(_day(car["in_service_date"]), _day(car["acquired_date"]), car["acquired_miles"],
               bool(car["severe_service"]))


def load(conn: sqlite3.Connection, car, today: date | None = None, until: date | None = None) -> CarStatus:
    """Run the gap engine over one car's schedule and confirmed services, looking ahead to ``until``."""
    today = today or date.today()
    rows = schedules.items(conn, car["id"])
    items = [
        Item(row["id"], row["name"], frozenset(row["codes"]), row["action"], row["interval_miles"],
             row["interval_months"], row["first_miles"], row["first_months"], row["applies"], _day(row["counts_from"]))
        for row in rows
    ]
    done = [
        Service(row["id"], date.fromisoformat(row["performed_on"]), row["odometer"],
                {code: frozenset(actions) for code, actions in row["coverage"].items()})
        for row in services.coverage(conn, car["id"])
    ]
    odo = odometer_for(conn, car)
    vehicle = engine_car(car)
    estimate = odo.miles_on(today)
    return CarStatus(car["id"], {row["id"]: row for row in rows}, assess(items, done, odo, vehicle, today, until), odo,
                     today, None if estimate is None else round(estimate), done)


# ---------- Words ----------


def _date(day: date, today: date) -> str:
    return f"{day:%b} {day.day}" + (f", {day.year}" if day.year != today.year else "")


def when(occurrence: Occurrence, status: CarStatus) -> str:
    """How far off (or how far past) an occurrence is, in miles where known and by date."""
    day, miles, today = occurrence.due_day, occurrence.due_miles, status.today
    gap = None if miles is None or status.today_miles is None else miles - status.today_miles
    if occurrence.status == "overdue":
        if gap is not None and gap < 0:
            return f"{-gap:,} mi overdue · due {_date(day, today)}"
        return f"overdue since {_date(day, today)}"
    if occurrence.status == "due":
        return (f"in {gap:,} mi · " if gap is not None and gap > 0 else "") + f"by {_date(day, today)}"
    if occurrence.status == "later":
        return (f"in {gap:,} mi · " if gap is not None and gap > 0 else "") + f"~{day:%b %Y}"
    if occurrence.status == "gap":
        return f"missed at {miles:,} mi · {day:%b %Y}" if miles is not None else f"missed {day:%b %Y}"
    return ""


def _months(months: int) -> str:
    return f"{months // 12} yr" if months >= 24 and months % 12 == 0 else f"{months} mo"


def every(item: dict) -> str:
    """The interval, briefly, for the chart's item column: '6,000 mi · 6 mo', never broken inside a figure."""
    parts = ([f"{item['interval_miles']:,} mi"] if item["interval_miles"] else []) + (
        [_months(item["interval_months"])] if item["interval_months"] else [])
    if not parts and (item["first_miles"] or item["first_months"]):
        return "once"
    return " · ".join(parts)


# ---------- Next up ----------


def attest_url(vehicle_id: int, item_id: int, occurrence: Occurrence | None = None) -> str:
    url = f"/vehicles/{vehicle_id}/schedule-items/{item_id}/done"
    return f"{url}?due={occurrence.due_day.isoformat()}" if occurrence is not None and occurrence.status == "gap" else url


def _icon(status: CarStatus, item_id: int) -> str:
    row = status.items[item_id]
    return icon_for(row["codes"], row["category"])


def next_up(status: CarStatus, limit: int = NEXT_UP, costs: dict[int, int] | None = None) -> list[dict]:
    """Overdue first (longest overdue at the top), then due soon, then the next few later; each with its cost if known."""
    rank = {"overdue": 0, "due": 1, "later": 2}
    current = sorted(
        ((s, s.current) for s in status.statuses if s.current),
        key=lambda pair: (rank[pair[1].status], pair[1].due_day, pair[0].item.name),
    )
    urgent = [pair for pair in current if pair[1].status != "later"]
    chosen = urgent + [pair for pair in current if pair[1].status == "later"][:max(0, limit - len(urgent))]
    return [
        {
            "item_id": item_status.item.id,
            "name": item_status.item.name,
            "action": item_status.item.action,
            "status": occurrence.status,
            "when": when(occurrence, status),
            "attest_url": attest_url(status.vehicle_id, item_status.item.id) if occurrence.status == "overdue" else None,
            "cost": (costs or {}).get(item_status.item.id),
            "icon": _icon(status, item_status.item.id),
        }
        for item_status, occurrence in chosen
    ]


def missed(status: CarStatus) -> list[dict]:
    """Every missed occurrence, most recent first, each with a way to say it was done after all."""
    rows = [
        {"name": s.item.name, "when": when(o, status), "attest_url": attest_url(status.vehicle_id, s.item.id, o),
         "due_day": o.due_day}
        for s in status.statuses for o in s.missed
    ]
    return sorted(rows, key=lambda row: row["due_day"], reverse=True)


def picks(status: CarStatus) -> list[dict]:
    """The jobs a service's line can be tagged for: overdue and due soon first, as next up orders them, then the
    rest in schedule order. Each with the service types it's matched on and its action, so a line tagged from it
    meets it."""
    rank = {"overdue": 0, "due": 1}
    urgent = sorted(((s, s.current) for s in status.statuses if s.current and s.current.status in rank),
                    key=lambda pair: (rank[pair[1].status], pair[1].due_day, pair[0].item.name))
    first = {s.item.id for s, _ in urgent}
    ordered = urgent + [(s, None) for s in status.statuses if s.item.id not in first]
    return [
        {"id": s.item.id, "name": s.item.name, "codes": list(status.items[s.item.id]["codes"]), "action": s.item.action,
         "when": when(occurrence, status) if occurrence else ""}
        for s, occurrence in ordered
    ]


def summary(status: CarStatus) -> dict:
    """The garage card's line: counts, and the one thing to do next."""
    first = next_up(status, limit=1)
    return {"overdue": status.count("overdue"), "due": status.count("due"), "missed": status.missed,
            "next": first[0] if first else None}


# ---------- Asking for a reading ----------


@dataclass(frozen=True)
class StaleReading:
    """The odometer hasn't been read for a while, on a car with jobs due by mileage."""
    last_day: date | None       # None: no reading at all
    days: int | None
    estimate: int | None        # today's mileage, by the odometer model

    def said(self, today: date) -> str:
        """'Jun 2, 4 months ago'; empty when there's no reading."""
        return f"{_date(self.last_day, today)}, {ago(self.days)}" if self.last_day and self.days else ""


def ago(days: int) -> str:
    months = round(days / 30.44)
    if months < 2:
        return f"{days} days ago"
    return f"{months} months ago" if months < 24 else f"{months // 12} years ago"


def stale_reading(status: CarStatus) -> StaleReading | None:
    """A reading to ask for: the last is over READING_DAYS old, or there's none, and a job falls due by mileage."""
    if not any(s.item.interval_miles or s.item.first_miles for s in status.statuses):
        return None
    read = [day for day, miles in status.odometer.points if miles > 0]   # the in-service date stands in at zero
    if not read:
        return StaleReading(None, None, None)
    days = (status.today - read[-1]).days
    return StaleReading(read[-1], days, status.today_miles) if days > READING_DAYS else None


# ---------- The interval chart ----------


def _span(here: int) -> tuple[int, int]:
    """The axis length and tick step: past today by enough to show what's coming.

    Something due far off (coolant at 137,500) isn't stretched for; next up lists it.
    """
    want = here + max(12_000, here * 0.15)
    for step in TICKS:
        if want / step <= MAX_SEGMENTS:
            return int(-(-want // step) * step), step
    step = TICKS[-1]
    return int(-(-want // step) * step), step


def _miles(occurrence: Occurrence, odometer: Odometer) -> int | None:
    if occurrence.status == "done" and occurrence.service is not None:
        service = occurrence.service
        if service.miles is not None:
            return service.miles
        estimate = odometer.miles_on(service.day)
        return None if estimate is None else round(estimate)
    return occurrence.due_miles


def chart(status: CarStatus, vehicle_name: str) -> dict | None:
    """The interval chart for _chart.html, or None when the odometer can't place anything."""
    here = status.today_miles
    if here is None:
        return None
    span, step = _span(here)
    groups: list[dict] = []
    ordered = sorted(status.statuses, key=lambda s: (status.items[s.item.id]["category_sort"],
                                                   status.items[s.item.id]["category"],
                                                   status.items[s.item.id]["position"]))
    for item_status in ordered:
        row = status.items[item_status.item.id]
        marks = []
        for occurrence in item_status.occurrences:
            if occurrence.status == "before":
                continue
            miles = _miles(occurrence, status.odometer)
            if miles is None or miles > span:
                continue
            href, day = None, occurrence.due_day
            if occurrence.status == "done" and occurrence.service is not None:
                href, day = f"/services/{occurrence.service.id}", occurrence.service.day
            elif occurrence.status in ("gap", "overdue"):
                href = attest_url(status.vehicle_id, item_status.item.id, occurrence)
            marks.append({"miles": miles, "status": occurrence.status, "href": href, "late": occurrence.late,
                          "day": day.isoformat()})
        if not groups or groups[-1]["label"] != row["category"]:
            groups.append({"label": row["category"], "rows": []})
        groups[-1]["rows"].append({"name": row["name"], "every": every(row), "marks": marks,
                                   "icon": _icon(status, item_status.item.id)})
    return {
        "vehicle": vehicle_name,
        "here": here,
        "span": span,
        "ticks": list(range(0, span + 1, step)),
        "groups": groups,
    }
