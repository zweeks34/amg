"""What a report covers: its view, and the car, dates, service and shop it's narrowed to.

Filters live in the address bar, so every report is a link you can keep. They
are read forgivingly, as the receipts page reads its finder: a date that isn't
one is no date, From after To is taken the right way round, and a car or
service the page doesn't offer is dropped rather than left filtering out of
sight.

A service is a type's code ("brake_pads") or a whole category
("category:Brakes"). Every filter set has to match.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from urllib.parse import urlencode

VIEWS = {"history": "History", "spending": "Spending", "fuel": "Fuel"}
CATEGORY = "category:"


@dataclass(frozen=True)
class Filters:
    view: str = "history"
    car: int | None = None
    start: str | None = None     # ISO dates, both included
    end: str | None = None
    service: str = ""
    shop: str = ""

    @classmethod
    def read(cls, view: str | None = None, car: str | None = None, start: str | None = None, end: str | None = None,
             service: str | None = None, shop: str | None = None) -> Filters:
        first, last = _day(start), _day(end)
        if first and last and first > last:
            first, last = last, first
        return cls(view if view in VIEWS else "history", _number(car), first, last, (service or "").strip(),
                   " ".join((shop or "").split()))

    def within(self, cars: list[int], services: list[str]) -> Filters:
        """Drop a car or service the page doesn't offer."""
        return replace(self, car=self.car if self.car in cars else None,
                       service=self.service if self.service in services else "")

    @property
    def category(self) -> str | None:
        return self.service[len(CATEGORY):] if self.service.startswith(CATEGORY) else None

    @property
    def uses_service(self) -> bool:
        """Do the service and shop filters apply? Fuel has neither."""
        return self.view != "fuel"

    @property
    def active(self) -> bool:
        """Is anything narrowing this view?"""
        return bool(self.car or self.start or self.end or (self.uses_service and (self.service or self.shop)))

    def matches(self, cover: dict) -> bool:
        """Is one of a line's service types the service asked for, or in its category?"""
        if (category := self.category) is not None:
            return cover["category"] == category
        return cover["code"] == self.service

    def covers(self, line: dict) -> bool:
        """Does a line do the service asked for? With none asked for, every line does."""
        return not self.service or any(self.matches(cover) for cover in line["covers"])

    def params(self) -> dict[str, str | int]:
        pairs = [("car", self.car), ("from", self.start), ("to", self.end)]
        if self.uses_service:
            pairs += [("service", self.service), ("shop", self.shop)]
        return {key: value for key, value in pairs if value}

    def url(self, view: str | None = None) -> str:
        """This report's address — or another view's, keeping what it shares with this one."""
        target = replace(self, view=view) if view else self
        params = {"view": target.view} if target.view != "history" else {}
        params.update(target.params())
        return "/reports" + (f"?{urlencode(params)}" if params else "")

    def csv_url(self) -> str:
        params = self.params()
        return f"/reports/{self.view}.csv" + (f"?{urlencode(params)}" if params else "")

    def cleared(self) -> str:
        """This view with nothing narrowing it."""
        return Filters(view=self.view).url()


def service_options(types: list, categories: list[str]) -> list[dict]:
    """The service picker: each category in use, as a whole and type by type, in catalogue order."""
    groups: dict[str, list] = {}
    for row in types:
        groups.setdefault(row["category"], []).append(row)
    order = {name: n for n, name in enumerate(categories)}
    return [
        {"category": category,
         "options": [{"value": CATEGORY + category, "label": f"Any {_lower_first(category)} work"}]
                    + [{"value": row["code"], "label": row["name"]} for row in rows]}
        for category, rows in sorted(groups.items(), key=lambda item: (order.get(item[0], len(order)), item[0]))
    ]


def service_label(service: str, type_names: dict[str, str]) -> str:
    """A service as a sentence names it: "brakes", "brake pads"."""
    if service.startswith(CATEGORY):
        return _lower_first(service[len(CATEGORY):])
    return _lower_first(type_names.get(service, service))


def span_words(start: str | None, end: str | None) -> str:
    """The dates asked for, in words: "Jan 2019 – Oct 2026", "from Jan 2019", "to Oct 2026"."""
    first = _month(start) if start else None
    last = _month(end) if end else None
    if first and last:
        return first if first == last else f"{first} – {last}"
    if first:
        return f"from {first}"
    return f"to {last}" if last else ""


# ---------- Helpers ----------


def _number(value: str | None) -> int | None:
    value = (value or "").strip()
    return int(value) if value.isascii() and value.isdigit() else None


def _day(value: str | None) -> str | None:
    try:
        return date.fromisoformat((value or "").strip()).isoformat()
    except ValueError:
        return None


def _month(day: str) -> str:
    return f"{date.fromisoformat(day):%b %Y}"


def _lower_first(text: str) -> str:
    """Sentence case inside a sentence, keeping acronyms: "Hybrid and EV" → "hybrid and EV"; "12-volt battery" stays."""
    return text if text[:2].isupper() else text[:1].lower() + text[1:]
