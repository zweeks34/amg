"""The odometer model: a car's mileage on any day, from the readings it has.

Readings come from everywhere a mileage was written down — typed in, on a
service, when you got the car — plus the in-service date at zero miles. Between
two readings the car is taken to have driven at a steady pace; after the last
one it carries on at its recent pace; before the first it runs back along the
first stretch, never below zero.

With no readings there's nothing to go on, and every answer is None: callers
judge by months alone.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date, timedelta

# The recent pace is taken over the last year of readings, if they span at
# least two months; otherwise over the whole history.
RECENT_DAYS = 365
MIN_SPAN_DAYS = 60

_EPSILON = 1e-9   # so 30.000000001 days of floating-point arithmetic is 30, not 31


class Odometer:
    def __init__(self, readings: Iterable[tuple[date, int]], in_service: date | None = None):
        by_day: dict[date, int] = {}
        for day, miles in readings:
            by_day[day] = max(miles, by_day.get(day, miles))
        if in_service is not None and (not by_day or in_service < min(by_day)):
            by_day.setdefault(in_service, 0)
        points: list[tuple[date, int]] = []
        for day, miles in sorted(by_day.items()):
            if points and miles < points[-1][1]:
                continue   # a reading that runs backwards; the app refuses these, but never bend the model on one
            points.append((day, miles))
        self.points = points

    def __bool__(self) -> bool:
        """True when the model can place a mileage on a date: two readings, at least."""
        return len(self.points) >= 2

    def rate(self) -> float | None:
        """Miles a day, recently."""
        if len(self.points) < 2:
            return None
        last_day = self.points[-1][0]
        recent = [p for p in self.points if (last_day - p[0]).days <= RECENT_DAYS]
        span = recent if len(recent) >= 2 and (recent[-1][0] - recent[0][0]).days >= MIN_SPAN_DAYS else self.points
        days = (span[-1][0] - span[0][0]).days
        return (span[-1][1] - span[0][1]) / days if days > 0 else None

    def miles_on(self, day: date) -> float | None:
        """The odometer on a day: a reading, between readings, or projected."""
        if not self.points:
            return None
        if len(self.points) == 1:
            return float(self.points[0][1]) if day == self.points[0][0] else None
        (first_day, first_miles), (second_day, second_miles) = self.points[0], self.points[1]
        if day <= first_day:
            pace = (second_miles - first_miles) / (second_day - first_day).days
            return max(0.0, first_miles - pace * (first_day - day).days)
        last_day, last_miles = self.points[-1]
        if day >= last_day:
            rate = self.rate()
            return None if rate is None else last_miles + rate * (day - last_day).days
        for (d0, m0), (d1, m1) in zip(self.points, self.points[1:]):
            if d0 <= day <= d1:
                return m0 + (m1 - m0) * (day - d0).days / (d1 - d0).days
        return None  # unreachable: the day is between the first and last readings

    def day_at(self, miles: float) -> date | None:
        """The day the car reached (or will reach) a mileage: the first day at or past it."""
        if len(self.points) < 2:
            return None
        first_day, first_miles = self.points[0]
        if miles <= first_miles:
            second_day, second_miles = self.points[1]
            if second_miles == first_miles:
                return first_day
            pace = (second_miles - first_miles) / (second_day - first_day).days
            return first_day - timedelta(days=math.floor((first_miles - miles) / pace + _EPSILON))
        last_day, last_miles = self.points[-1]
        if miles > last_miles:
            rate = self.rate()
            if not rate or rate <= 0:
                return None   # the car isn't being driven; it never gets there
            return last_day + timedelta(days=math.ceil((miles - last_miles) / rate - _EPSILON))
        for (d0, m0), (d1, m1) in zip(self.points, self.points[1:]):
            if m0 < miles <= m1:
                return d0 + timedelta(days=math.ceil((miles - m0) / (m1 - m0) * (d1 - d0).days - _EPSILON))
        return last_day
