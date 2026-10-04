"""What a car's alerts are about: the jobs due soon or overdue now, and which are news.

A job is a schedule item's service types and action, as the budget's prices
are; a "round" of it runs from the last service that did it to the next. Each
round can push twice — once when it comes due soon, once when it goes
overdue — and a round that went straight to overdue doesn't get a late "due
soon" after it. A missed occurrence doesn't start a new round: the job is
still undone, and the weekly email keeps saying so.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from ..engine import forecast
from ..engine.schedule import ItemStatus
from ..repo import alerts
from ..web import budget
from ..web import status as car_status
from ..web.templating import dollars
from . import ics
from .ntfy import Push

CHANNEL = "ntfy"
COMING_UP = 3     # later jobs the weekly email lists for each car
CALENDAR_MONTHS = 12


@dataclass(frozen=True)
class Watched:
    """A job due soon or overdue now."""
    vehicle_id: int
    subject: str        # the job's round, as the alert log keys it
    level: str          # due or overdue
    name: str
    when: str           # "1,200 mi overdue · due Sep 3"
    cost: int | None

    @property
    def line(self) -> str:
        return f"{self.name}: {self.when}" + (f" · ~{dollars(self.cost)}" if self.cost else "")


@dataclass
class CarWatch:
    """One car, looked at today: its schedule's state, its budget, and what's due."""
    car: dict
    state: car_status.CarStatus
    plan: budget.CarBudget
    jobs: list[Watched]
    has_schedule: bool

    @property
    def overdue(self) -> list[Watched]:
        return [j for j in self.jobs if j.level == "overdue"]

    @property
    def due(self) -> list[Watched]:
        return [j for j in self.jobs if j.level == "due"]

    @property
    def coming_up(self) -> list[dict]:
        every = car_status.next_up(self.state, limit=len(self.state.statuses), costs=self.plan.item_costs())
        return [row for row in every if row["status"] == "later"][:COMING_UP]


def subject(vehicle_id: int, item_status: ItemStatus) -> str:
    """The job's round: which car, which job, and the last service that did it."""
    item = item_status.item
    codes = ",".join(sorted(item.codes)) or f"item{item.id}"   # a job with no service types is its own
    done = item_status.last_done
    since = f"s{done.service.id}" if done is not None and done.service is not None else "new"
    return f"{vehicle_id}:{codes}:{item.action}:{since}"


def look(conn: sqlite3.Connection, car, today: date | None = None) -> CarWatch:
    today = today or date.today()
    end = forecast.months(today, CALENDAR_MONTHS)[-1][1]
    state = car_status.load(conn, car, today, until=end)
    plan = budget.load(conn, car, CALENDAR_MONTHS, today, state=state)
    costs = plan.item_costs()
    rank = {"overdue": 0, "due": 1}
    urgent = sorted(((s, s.current) for s in state.statuses if s.current and s.current.status in rank),
                    key=lambda pair: (rank[pair[1].status], pair[1].due_day, pair[0].item.name))
    jobs: list[Watched] = []
    for item_status, occurrence in urgent:
        key = subject(car["id"], item_status)
        if any(j.subject == key for j in jobs):
            continue   # two items asking for the same job: the more urgent speaks for both
        jobs.append(Watched(car["id"], key, occurrence.status, item_status.item.name,
                            car_status.when(occurrence, state), costs.get(item_status.item.id)))
    return CarWatch(dict(car), state, plan, jobs, bool(state.items))


def news(jobs: list[Watched], logged: set[tuple[str, str]]) -> list[Watched]:
    """The jobs not yet alerted at their level; an overdue alert covers due soon."""
    return [j for j in jobs if (j.subject, j.level) not in logged and (j.subject, "overdue") not in logged]


def push(watch: CarWatch, fresh: list[Watched], base_url: str) -> Push:
    """One push for a car's news: the job itself if there's one, a count and a line each if there are more."""
    name = watch.car["name"]
    overdue = sum(1 for j in fresh if j.level == "overdue")
    if len(fresh) == 1:
        job = fresh[0]
        title = f"{name}: {job.name} {'overdue' if overdue else 'due soon'}"
        message = job.when + (f" · ~{dollars(job.cost)}" if job.cost else "")
    else:
        counts = [f"{overdue} overdue"] * bool(overdue) + [f"{len(fresh) - overdue} due soon"] * bool(len(fresh) - overdue)
        title = f"{name}: {len(fresh)} jobs — {', '.join(counts)}"
        message = "\n".join(j.line for j in fresh)
    return Push(title, message, priority=4 if overdue else 3, tags=("warning",) if overdue else ("wrench",),
                click=f"{base_url}/vehicles/{watch.car['id']}")


def take_stock(conn: sqlite3.Connection, car, today: date | None = None) -> int:
    """Log what's due now as known, without sending it: alerts start from now. Returns how many."""
    watch = look(conn, car, today)
    for job in watch.jobs:
        alerts.known(conn, CHANNEL, job.subject, job.level, car["id"], job.line)
    return len(watch.jobs)


# ---------- The calendar ----------


def events(watches: list[CarWatch], base_url: str) -> list[ics.Event]:
    """Every job falling due in the next 12 months, as all-day events.

    Overdue ones are left out: a file you import can't keep them on today. The
    UID numbers each time the job falls due since the car's records begin —
    the 9th oil change — so it stays the same as dates pass, as the job is done
    late or early, and as the odometer moves a date: a newer file moves the
    event rather than adding one.
    """
    found: list[ics.Event] = []
    for watch in watches:
        today, car = watch.state.today, watch.car
        end = forecast.months(today, CALENDAR_MONTHS)[-1][1]
        costs = watch.plan.item_costs()
        seen: set[tuple[str, str]] = set()
        for item_status in watch.state.statuses:
            item = item_status.item
            codes = "+".join(sorted(item.codes)) or f"item{item.id}"
            if (codes, item.action) in seen:
                continue   # two items asking for the same job: one set of events
            seen.add((codes, item.action))
            by_miles = bool(item.interval_miles or item.first_miles)
            cost = costs.get(item.id)
            for n, occurrence in enumerate(item_status.occurrences, start=1):
                if occurrence.status not in ("due", "later") or not today < occurrence.due_day <= end:
                    continue
                parts = []
                if by_miles and occurrence.due_miles is not None:
                    parts.append(f"Due at {occurrence.due_miles:,} mi or by this date, whichever comes first. "
                                 "The date is estimated from how much you drive.")
                if cost:
                    parts.append(f"About {dollars(cost)}.")
                found.append(ics.Event(
                    uid=f"amg-{car['id']}-{codes}-{item.action}-{n}@amg",
                    day=occurrence.due_day,
                    summary=f"{item.name} · {car['name']}",
                    description=" ".join(parts),
                    url=f"{base_url}/vehicles/{car['id']}",
                ))
    return sorted(found, key=lambda e: (e.day, e.summary))
