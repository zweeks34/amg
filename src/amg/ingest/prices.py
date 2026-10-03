"""Claude's estimate of what jobs cost, for the budget, where your receipts don't say.

One call per car, every job it's asked about at once: what the car is, each
job, and — so the ranges fit your part of the world — what you've paid for
other work on it. Each answer is a range, what a shop would charge with parts,
labour, shop fees and tax included, and is checked before it's kept: a range
that's upside down, nothing, or beyond any maintenance job is refused, and a
job Claude skipped says so.

Nothing here touches the database; ingest/background.py stores the answer.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, Field

from ..engine import forecast
from . import claude
from .manuals import describe_car

EFFORT = "medium"
ANCHORS = 12        # of your own prices, for Claude to calibrate against
MAX_TOKENS = 8_000
MOST_USD = 20_000   # more than this for one maintenance job is a misreading, not a price

ACTION_WORDS = {"replace": "replace", "perform": "do", "inspect": "inspect"}


class JobPrice(BaseModel):
    key: str = Field(description="The job's key exactly as given, like j12.")
    low_usd: float = Field(description="What a good independent shop would charge, in US dollars.")
    high_usd: float = Field(description="What a dealer would charge, in US dollars.")
    note: str = Field(description="One short line on what the range assumes: parts, quantities, labour hours.")


class PriceEstimates(BaseModel):
    prices: list[JobPrice] = Field(description="One entry per job asked about.")


SYSTEM_PROMPT = """\
You estimate what car maintenance costs in the United States today, so an owner can budget for \
it. For each job you're given, say what a shop would charge to do it on this car: parts, labour, \
shop fees and sales tax included. Give a range: low is a good independent shop, high a dealer. \
Price the job once, as one visit would charge for it, not per year.

Where the owner's own prices are given, use them to judge local labour rates and how far above \
or below national averages this owner's shops sit, and keep your ranges consistent with them.

Price every job, even when unsure: give your best range and make it wider. In the note, name \
what the range assumes in a few words — the part or fluid and its quantity, or the labour hours \
— so the owner can check it against a quote."""


@dataclass
class Priced:
    low_cents: int
    high_cents: int
    note: str


@dataclass
class PriceRead:
    prices: dict[str, Priced] = field(default_factory=dict)   # key → Claude's range
    missing: dict[str, str] = field(default_factory=dict)     # key → why there's no price
    usage: claude.Usage | None = None


def _job_line(job: Mapping) -> str:
    types = ", ".join(job["types"])
    return f"- {job['key']}: {job['name']} ({ACTION_WORDS.get(job['action'], job['action'])}: {types})"


def prompt(car: Mapping, jobs: Sequence[Mapping], anchors: Sequence[Mapping]) -> str:
    """What Claude is asked. ``jobs`` are {key, name, action, types}; ``anchors`` {name, cents, count}."""
    parts = [f"The owner's car: {describe_car(car)}.", "", "Price these jobs:", *map(_job_line, jobs)]
    if anchors:
        parts += ["", "What this owner has paid on this car, in today's money:"]
        parts += [f"- {a['name']}: ${a['cents'] / 100:,.0f}"
                  + (f" (median of {a['count']} visits)" if a["count"] > 1 else "") for a in anchors]
    return "\n".join(parts)


def check(answer: PriceEstimates, keys: Sequence[str]) -> PriceRead:
    """Claude's answer, each range checked; a job it skipped or got wrong goes in ``missing``."""
    read = PriceRead()
    given = {p.key.strip(): p for p in answer.prices}
    for key in keys:
        price = given.get(key)
        if price is None:
            read.missing[key] = "Claude gave no price for this. Ask again, or set your own."
            continue
        low, high = round(price.low_usd * 100), round(price.high_usd * 100)
        if low <= 0 or high < low or high > MOST_USD * 100:
            read.missing[key] = (f"Claude's range didn't make sense (${price.low_usd:,.2f} to "
                                 f"${price.high_usd:,.2f}). Ask again, or set your own.")
            continue
        read.prices[key] = Priced(low, high, price.note.strip())
    return read


def ask_claude(car: Mapping, jobs: Sequence[Mapping], anchors: Sequence[Mapping] = ()) -> PriceRead:
    """Claude's range for each job; raises claude.ClaudeError when the call itself fails."""
    answer, usage = claude.parse(
        PriceEstimates,
        system=SYSTEM_PROMPT,
        content=[{"type": "text", "text": prompt(car, jobs, anchors)}],
        effort=EFFORT,
        max_tokens=MAX_TOKENS,
    )
    read = check(answer, [job["key"] for job in jobs])
    read.usage = usage
    return read


def anchors(items: Iterable[Mapping], visits: Iterable[forecast.Visit], today: date) -> list[dict]:
    """What you've paid for the jobs in a car's schedule, most often paid first — Claude's calibration."""
    visits = list(visits)
    seen, found = set(), []
    for item in items:
        job = forecast.Job(frozenset(item["codes"]), item["action"])
        if not job.codes or job.key in seen:
            continue
        seen.add(job.key)
        price = forecast.estimate(job, today, visits=visits)
        if price is not None:
            found.append({"name": item["name"], "cents": price.cents, "count": price.count})
    return sorted(found, key=lambda a: -a["count"])[:ANCHORS]
