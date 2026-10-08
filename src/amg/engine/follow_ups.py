"""Shop recommendations: which are still open.

A recommendation is work a receipt marks as recommended, declined or due next
time ("rear pads at 3 mm"). It stays open until a later service does the
work, or you close it yourself:

- A service does it when it covers one of the recommendation's service types
  by replacing it or doing it. Only looking at it isn't the work, unless the
  type is one you'd normally just inspect (a multipoint inspection). The visit
  that made the recommendation doesn't count, and nor does anything before it.
- You close one by logging it as a service from the recommendation (done), or
  by saying you're not doing it (skipped). Yours wins over the service history.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from .schedule import Service

_DOING = frozenset({"replace", "perform"})


@dataclass(frozen=True)
class Recommendation:
    receipt_id: int
    event_id: int            # the visit that made it
    day: date
    shop: str
    description: str
    codes: tuple[str, ...]
    quoted_cents: int | None
    key: str                 # its wording, normalised: how your outcome finds it


@dataclass(frozen=True)
class Outcome:
    outcome: str             # done or skipped
    event_id: int | None     # the service it was logged as


@dataclass(frozen=True)
class FollowUp:
    rec: Recommendation
    done_by: Service | None  # the later service that did the work
    yours: Outcome | None

    @property
    def open(self) -> bool:
        return self.yours is None and self.done_by is None

    @property
    def skipped(self) -> bool:
        return self.yours is not None and self.yours.outcome == "skipped"


def does(service: Service, rec: Recommendation, default_actions: Mapping[str, str]) -> bool:
    """Whether a service does a recommendation's work: see the module docstring."""
    if service.id == rec.event_id or service.day < rec.day:
        return False
    for code in rec.codes:
        actions = service.coverage.get(code)
        if actions and (actions & _DOING or default_actions.get(code) == "inspect"):
            return True
    return False


def follow(recs: Iterable[Recommendation], services: Iterable[Service], default_actions: Mapping[str, str],
           outcomes: Mapping[tuple[int, str], Outcome]) -> list[FollowUp]:
    """Each recommendation with what closed it, if anything; services oldest first, so the first that did it."""
    visits = sorted(services, key=lambda s: (s.day, s.id))
    return [
        FollowUp(rec, next((s for s in visits if does(s, rec, default_actions)), None),
                 outcomes.get((rec.receipt_id, rec.key)))
        for rec in recs
    ]
