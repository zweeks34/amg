"""What a car's alerts are about: the jobs due soon or overdue now, and which are news.

A job is a schedule item's service types and action, as the budget's prices
are; a "round" of it runs from the last service that did it to the next. Each
round can push twice — once when it comes due soon, once when it goes
overdue — and a round that went straight to overdue doesn't get a late "due
soon" after it. A missed occurrence doesn't start a new round: the job is
still undone, and the weekly email keeps saying so.

Inspections and registration ride along: one comes due 30 days before it
expires, again in its last week, and goes overdue — expired — the day after.
Its round is its expiry date, so logging the next one starts fresh. They don't
wait for the car's alerts switch, which is there because job alerts are wrong
while old receipts are still going in; a date you typed yourself isn't. A car
with its alerts off is watched for those dates alone.

Notices aren't jobs, so they stay out of the overdue and due-soon counts: a
car whose jobs fall due by mileage asks for an odometer reading once the last
is over two months old. Its round is the last reading's date, so a new
reading, then two quiet months, asks again. Each open recall NHTSA lists
for the car is pushed once, whatever the car's alerts switch says: it comes
from NHTSA, not your receipts. So is each warranty coming up on its end, 60
days (or the miles you drive in 60 days) before it: a warranty you confirmed
can't be wrong the way job alerts are while old receipts go in. Its round is
its end, by date or by miles, so a changed end warns again.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from ..engine import forecast
from ..engine.schedule import ItemStatus
from ..repo import alerts, recalls
from ..engine.follow_ups import FollowUp
from ..web import budget
from ..web import follow_ups as follow_up_words
from ..web import recalls as recall_words
from ..web import renewals as renewal_words
from ..web import status as car_status
from ..web import warranties as warranty_words
from ..web.templating import dollars
from . import ics
from .ntfy import Push

CHANNEL = "ntfy"
COMING_UP = 3     # later jobs the weekly email lists for each car
CALENDAR_MONTHS = 12


@dataclass(frozen=True)
class Watched:
    """A job — or an inspection or registration — due soon or overdue now; or a notice, such as a reading wanted."""
    vehicle_id: int
    subject: str        # the job's round, as the alert log keys it
    level: str          # due or overdue
    name: str
    when: str           # "1,200 mi overdue · due Sep 3"; "expires Oct 31 · in 26 days"
    cost: int | None
    kind: str = "job"   # job, renewal, reading, recall or warranty
    urgent: bool = False   # a recall NHTSA says not to drive (or to park outside) until it's fixed
    action: str | None = None   # a schedule job's: replace, inspect or perform

    @property
    def renewal(self) -> bool:
        return self.kind == "renewal"

    @property
    def line(self) -> str:
        return f"{self.name}: {self.when}" + (f" · ~{dollars(self.cost)}" if self.cost else "")

    @property
    def state(self) -> str:
        """Overdue, due soon, or (an inspection or registration past its date) expired."""
        if self.level == "overdue":
            return "expired" if self.renewal else "overdue"
        return "due soon"


@dataclass
class CarWatch:
    """One car, looked at today: its schedule's state, its budget, and what's due."""
    car: dict
    state: car_status.CarStatus
    plan: budget.CarBudget
    jobs: list[Watched]
    has_schedule: bool
    renewals: list[renewal_words.Row] = field(default_factory=list)   # every kind the car can need
    maintenance: bool = True    # its schedule watched too: the car's alerts are on
    notices: list[Watched] = field(default_factory=list)   # pushed like jobs, counted apart
    recommended: list[FollowUp] = field(default_factory=list)   # the shops', open, from the last 12 months

    @property
    def alerting(self) -> list[Watched]:
        """Everything a push can be about."""
        return self.jobs + self.notices

    @property
    def reading(self) -> Watched | None:
        return next((n for n in self.notices if n.kind == "reading"), None)

    @property
    def recalls(self) -> list[Watched]:
        return [n for n in self.notices if n.kind == "recall"]

    @property
    def warranties(self) -> list[Watched]:
        """Warranties ending soon."""
        return [n for n in self.notices if n.kind == "warranty"]

    @property
    def dates(self) -> list[renewal_words.Row]:
        """The inspections and registration it has a date for."""
        return [row for row in self.renewals if row.standing]

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


def reading_subject(vehicle_id: int, stale: car_status.StaleReading) -> str:
    """A reading wanted: its round is the last reading, so a new one, then two quiet months, asks again."""
    return f"{vehicle_id}:reading:{stale.last_day.isoformat() if stale.last_day else 'none'}"


def warranty_subject(vehicle_id: int, row: warranty_words.Row) -> str:
    """'3:warranty:12:2028-03-01', or '3:warranty:12:60000mi' for one ending by miles: its round is its end."""
    if row.standing.by == "miles":
        return f"{vehicle_id}:warranty:{row.id}:{row.standing.end_miles}mi"
    return f"{vehicle_id}:warranty:{row.id}:{row.standing.end_day.isoformat()}"   # type: ignore[union-attr]


def reading_words(stale: car_status.StaleReading, today: date) -> str:
    if stale.last_day is None:
        return "there's no reading yet"
    return f"the last was {stale.said(today)}" + (
        f"; AMG's guess is ~{stale.estimate:,} mi" if stale.estimate is not None else "")


def renewal_subject(vehicle_id: int, row: renewal_words.Row) -> str:
    """An inspection's or registration's round: its expiry. The last week's reminder is one of its own."""
    key = f"{vehicle_id}:renewal:{row.kind.code}:{row.records[0]['expires_on']}"
    return key + (":week" if row.standing.state == "week" else "")


def look(conn: sqlite3.Connection, car, today: date | None = None, maintenance: bool | None = None) -> CarWatch:
    """What's due on a car. Its schedule's jobs count when its alerts are on (or ``maintenance`` says so);
    its inspections and registration always."""
    today = today or date.today()
    maintenance = bool(car["alerts"]) if maintenance is None else maintenance
    end = forecast.months(today, CALENDAR_MONTHS)[-1][1]
    state = car_status.load(conn, car, today, until=end)
    plan = budget.load(conn, car, CALENDAR_MONTHS, today, state=state)
    costs = plan.item_costs()
    rank = {"overdue": 0, "due": 1}
    urgent = sorted(((s, s.current) for s in state.statuses if s.current and s.current.status in rank),
                    key=lambda pair: (rank[pair[1].status], pair[1].due_day, pair[0].item.name))
    jobs: list[Watched] = []
    for item_status, occurrence in urgent if maintenance else ():
        key = subject(car["id"], item_status)
        if any(j.subject == key for j in jobs):
            continue   # two items asking for the same job: the more urgent speaks for both
        jobs.append(Watched(car["id"], key, occurrence.status, item_status.item.name,
                            car_status.when(occurrence, state), costs.get(item_status.item.id),
                            action=item_status.item.action))
    rows = renewal_words.rows(conn, car, today, offers=False)
    for row in renewal_words.urgent(rows):
        jobs.append(Watched(car["id"], renewal_subject(car["id"], row),
                            "overdue" if row.standing.state == "expired" else "due", row.kind.name, row.when,
                            plan.fee_cost(row.kind.code), kind="renewal"))
    jobs.sort(key=lambda job: rank[job.level])   # stable: each keeps its place within overdue, then due soon
    notices: list[Watched] = [
        Watched(car["id"], f"{car['id']}:recall:{row['campaign']}", "due", recall_words.component(row["component"]),
                recall_words.when(row), None, kind="recall", urgent=bool(row["park_it"] or row["park_outside"]))
        for row in recalls.open_for(conn, car["id"])
    ]
    for row in warranty_words.load(conn, car, state.odometer, today).ending:
        name = f"{row.title} · {row.provider}" if row.provider else row.title
        notices.append(Watched(car["id"], warranty_subject(car["id"], row), "due", name,
                               row.ending[:1].lower() + row.ending[1:], None, kind="warranty"))
    if maintenance and (stale := car_status.stale_reading(state)):
        notices.append(Watched(car["id"], reading_subject(car["id"], stale), "due", "Odometer reading wanted",
                               reading_words(stale, today), None, kind="reading"))
    recommended = follow_up_words.load(conn, car, today).recent if maintenance else []
    return CarWatch(dict(car), state, plan, jobs, bool(state.items), rows, maintenance, notices, recommended)


def news(jobs: list[Watched], logged: set[tuple[str, str]]) -> list[Watched]:
    """The jobs not yet alerted at their level; an overdue alert covers due soon."""
    return [j for j in jobs if (j.subject, j.level) not in logged and (j.subject, "overdue") not in logged]


def push(watch: CarWatch, fresh: list[Watched], base_url: str) -> Push:
    """One push for a car's news: the job itself if there's one, a count and a line each if there are more."""
    name = watch.car["name"]
    page = f"{base_url}/vehicles/{watch.car['id']}"
    dated = [j for j in fresh if j.kind in ("job", "renewal")]
    overdue = sum(1 for j in dated if j.level == "overdue")
    reading = any(j.kind == "reading" for j in fresh)
    found = [j for j in fresh if j.kind == "recall"]
    ending = [j for j in fresh if j.kind == "warranty"]
    urgent = any(j.urgent for j in found)
    if len(fresh) == 1:
        job = fresh[0]
        if job.kind == "reading":
            return Push(f"{name}: odometer reading wanted", job.when[:1].upper() + job.when[1:] + ".", priority=3,
                        tags=("wrench",), click=f"{page}#add-reading")
        if job.kind == "warranty":
            return Push(f"{name}: warranty ending", job.line + ".", priority=3, tags=("hourglass",),
                        click=f"{page}#warranties")
        if job.kind == "recall":
            return Push(f"{name}: recall, don't drive it" if job.urgent else f"{name}: recall to check",
                        f"{job.name}: {job.when}", priority=5 if job.urgent else 4, tags=("warning",),
                        click=f"{page}#recalls")
        title = f"{name}: {job.name} {job.state}"
        message = job.when + (f" · ~{dollars(job.cost)}" if job.cost else "")
    else:
        counts = ([f"{overdue} overdue"] * bool(overdue) + [f"{len(dated) - overdue} due soon"] * bool(len(dated) - overdue)
                  + [f"{len(found)} recall{'s' if len(found) != 1 else ''} to check"] * bool(found)
                  + [f"{len(ending)} warrant{'ies' if len(ending) != 1 else 'y'} ending"] * bool(ending)
                  + ["odometer reading wanted"] * reading)
        title = f"{name}: {', '.join(counts)}"
        message = "\n".join(j.line for j in fresh)
    priority = 5 if urgent else 4 if overdue or found else 3
    return Push(title, message, priority=priority, tags=("warning",) if priority > 3 else ("wrench",),
                click=f"{page}#recalls" if found and len(found) == len(fresh) else page)


def take_stock(conn: sqlite3.Connection, car, today: date | None = None) -> int:
    """Log the jobs due now as known, without sending them: alerts start from now. Returns how many.

    Inspections and registration aren't held back: they've been watched all along.
    """
    jobs = [job for job in look(conn, car, today, maintenance=True).jobs if job.kind == "job"]
    for job in jobs:
        alerts.known(conn, CHANNEL, job.subject, job.level, car["id"], job.line)
    return len(jobs)


# ---------- The calendar ----------


def events(watches: list[CarWatch], base_url: str) -> list[ics.Event]:
    """Every job falling due in the next 12 months, and when each inspection and registration expires, as
    all-day events; a car's jobs only when its schedule is watched.

    Overdue (and expired) ones are left out: a file you import can't keep them
    on today. A job's UID numbers each time it falls due since the car's
    records begin — the 9th oil change — so it stays the same as dates pass,
    as the job is done late or early, and as the odometer moves a date: a
    newer file moves the event rather than adding one. An expiry's UID is the
    car's and the kind's alone, so logging the next one moves it too.
    """
    found: list[ics.Event] = []
    for watch in watches:
        today, car = watch.state.today, watch.car
        for row in watch.dates:
            expires = date.fromisoformat(row.records[0]["expires_on"])
            if expires >= today:
                found.append(ics.Event(
                    uid=f"amg-{car['id']}-{row.kind.code}@amg",
                    day=expires,
                    summary=f"{row.kind.name} expires · {car['name']}",
                    description="Good through this day. AMG reminds you 30 days before, and again in the last week.",
                    url=f"{base_url}/vehicles/{car['id']}",
                ))
        if not watch.maintenance:
            continue
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
