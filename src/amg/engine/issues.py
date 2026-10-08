"""Issues: which visit to ask about.

An issue is something you noticed wrong with a car. A later visit closes
nothing by itself: a shop can look at a rattle and miss it. Instead AMG asks
about the newest visit on or after the day you noticed it, until you answer:
fixed then closes it, still there keeps it open and is kept as what's been
tried. A visit the same day counts, since that's often the visit for it.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Visit:
    id: int
    day: date
    shop: str


def since(noticed_on: date, visits: Iterable[Visit]) -> list[Visit]:
    """The visits on or after the day it was noticed, newest first."""
    return sorted((v for v in visits if v.day >= noticed_on), key=lambda v: (v.day, v.id), reverse=True)


def to_ask(noticed_on: date, visits: Iterable[Visit], checked: Collection[int]) -> Visit | None:
    """The newest visit since it was noticed, unless you've said it was still there after that one."""
    newest = next(iter(since(noticed_on, visits)), None)
    return None if newest is None or newest.id in checked else newest
