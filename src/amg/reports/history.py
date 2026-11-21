"""The History report: which services match, which of their lines, and what they came to.

The car and the dates are narrowed in SQL (repo/reports.visits); the shop and
the service here. A shop is matched on who did the work as the pages name it —
the shop, "Your own work" or "Done, no receipt" — so "own work" finds the jobs
you did yourself. A service keeps the visits with a line that did it, and of
those visits shows only the lines that did; the rest are counted.

Each visit also carries how far and how long it came after the one before it
for the same car, among the visits shown (so narrowed to brakes, it's the
brake job before), and its main category: where most of its shown lines'
money went. The page groups the visits by year.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from ..repo import reports
from ..web.budget import colour
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

    def years(self) -> list[dict]:
        """The visits by year, newest first: {"year", "visits", "count", "paid"}, paid as the figure counts it."""
        found: dict[str, list[dict]] = {}
        for visit in self.visits:
            found.setdefault(visit["performed_on"][:4], []).append(visit)
        return [{"year": year, "visits": visits, "count": len(visits),
                 "paid": sum((v["matched_cents"] if self.by_service else v["paid"] or 0) for v in visits)}
                for year, visits in found.items()]

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
            "main": main_category(shown),
        })
    for visit in chosen:
        visit["tone"] = colour(visit["main"]) if visit["main"] else ""
    before: dict[int, dict] = {}
    for visit in reversed(chosen):              # oldest first
        earlier = before.get(visit["vehicle_id"])
        visit["since"] = since_words(earlier, visit) if earlier else ""
        before[visit["vehicle_id"]] = visit
    return History(chosen, by_service)


def main_category(lines: list[dict]) -> str | None:
    """Where most of the lines' money went, by category; with no amounts, the first line's that has one."""
    spent: dict[str, int] = {}
    for line in lines:
        if line["covers"]:
            name = line["covers"][0]["category"]
            spent[name] = spent.get(name, 0) + abs(line["amount_cents"] or 0)
    if not spent:
        return None
    return max(spent, key=lambda name: spent[name]) if any(spent.values()) else next(iter(spent))


def since_words(earlier: dict, later: dict) -> str:
    """How far and how long one visit came after another: "+5,210 mi · 6 mo", "3 wk", "2 yr 1 mo"."""
    parts = []
    if earlier["odometer"] is not None and later["odometer"] is not None and later["odometer"] >= earlier["odometer"]:
        parts.append(f"+{later['odometer'] - earlier['odometer']:,} mi")
    first, last = date.fromisoformat(earlier["performed_on"]), date.fromisoformat(later["performed_on"])
    months = (last.year - first.year) * 12 + last.month - first.month - (last.day < first.day)
    if months >= 24:
        parts.append(f"{months // 12} yr" + (f" {months % 12} mo" if months % 12 else ""))
    elif months >= 1:
        parts.append(f"{months} mo")
    elif (days := (last - first).days) >= 14:
        parts.append(f"{days // 7} wk")
    else:
        parts.append("same day" if days == 0 else f"{days} day" + ("s" if days != 1 else ""))
    return " · ".join(parts)


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
