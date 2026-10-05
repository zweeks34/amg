"""The History report: which services match, which of their lines, and what they came to.

The car and the dates are narrowed in SQL (repo/reports.visits); the shop and
the service here. A shop is matched on who did the work as the pages name it —
the shop, "Your own work" or "Done, no receipt" — so "own work" finds the jobs
you did yourself. A service keeps the visits with a line that did it, and of
those visits shows only the lines that did; the rest are counted.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..repo import reports
from ..web.templating import who
from .filters import Filters

OTHER = "Other"   # a line with no service type


@dataclass
class History:
    visits: list[dict]      # newest first; each with who, shown, others, others_cents, matched_cents, paid
    by_service: bool        # narrowed to a service: only matching lines are shown and counted

    @property
    def count(self) -> int:
        return len(self.visits)

    @property
    def paid_cents(self) -> int:
        """What the visits came to, whole."""
        return sum(visit["paid"] or 0 for visit in self.visits)

    @property
    def matched_cents(self) -> int:
        """What the shown lines came to: with a service asked for, what was spent on it."""
        return sum(visit["matched_cents"] for visit in self.visits)

    @property
    def first(self) -> str | None:
        return self.visits[-1]["performed_on"] if self.visits else None

    @property
    def last(self) -> str | None:
        return self.visits[0]["performed_on"] if self.visits else None


def load(conn: sqlite3.Connection, filters: Filters) -> History:
    return select(reports.visits(conn, filters.car, filters.start, filters.end), filters)


def select(visits: list[dict], filters: Filters) -> History:
    """The visits the shop and service filters keep, each with the lines to show."""
    by_service = bool(filters.service) and filters.uses_service
    shop = filters.shop.lower() if filters.uses_service else ""
    chosen = []
    for visit in visits:
        if shop and shop not in who(visit).lower():
            continue
        shown = [line for line in visit["lines"] if filters.covers(line)] if by_service else visit["lines"]
        if by_service and not shown:
            continue
        others = [line for line in visit["lines"] if line not in shown]
        chosen.append({
            **visit,
            "who": who(visit),
            "shown": shown,
            "others": len(others),
            "others_cents": _sum(others),
            "matched_cents": _sum(shown),
            "paid": paid(visit),
        })
    return History(chosen, by_service)


def paid(visit: dict) -> int | None:
    """What a visit cost: its total, or with none written down, its lines and tax. None when nothing has an amount."""
    if visit["total_cents"] is not None:
        return visit["total_cents"]
    amounts = [line["amount_cents"] for line in visit["lines"] if line["amount_cents"] is not None]
    if visit["tax_cents"] is not None:
        amounts.append(visit["tax_cents"])
    return sum(amounts) if amounts else None


def category(line: dict, filters: Filters) -> str:
    """The category a line's money goes under: its first service type's (the first that was asked for, when one
    was), in catalogue order; a line with no type is Other."""
    covers = [cover for cover in line["covers"] if filters.matches(cover)] if filters.service else line["covers"]
    return covers[0]["category"] if covers else OTHER


def _sum(lines: list[dict]) -> int:
    return sum(line["amount_cents"] or 0 for line in lines)
