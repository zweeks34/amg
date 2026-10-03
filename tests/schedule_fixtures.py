"""Builders shared by the schedule tests. tests/ is on pytest's path, so: import schedule_fixtures as sfx."""

from __future__ import annotations

from amg.ingest.manuals import ScheduleExtraction, ScheduleRow, TableColumn

# The sample manual's columns: 6 to 132 thousand miles, paired with 6 to 132 months.
COLUMNS = [TableColumn(miles=m * 1000, months=m) for m in range(6, 133, 6)]


def row(name="Engine oil", codes=("engine_oil",), action="replace", marks=(), severe=False, applies=True,
        why_not="", page=1, note="", **written) -> ScheduleRow:
    """One schedule entry; ``marks`` in thousands of miles, ``written`` as every_/first_ fields."""
    fields = dict(every_miles=None, every_months=None, first_miles=None, first_months=None)
    fields.update(written)
    return ScheduleRow(name=name, page=page, service_codes=list(codes), action=action,
                       marked_at_miles=[m * 1000 for m in marks], severe=severe, note=note,
                       applies_to_vehicle=applies, why_not=why_not, **fields)


def reading(*rows, columns=COLUMNS, uncertain="") -> ScheduleExtraction:
    return ScheduleExtraction(printed_for="2016 MY All Vehicles", table_columns=columns, items=list(rows),
                              severe_conditions="Repeated short trips\nTowing", uncertain=uncertain)


def sample() -> ScheduleExtraction:
    """A few rows of the sample manual, as Claude read them."""
    return reading(
        row("Engine oil", ("engine_oil",), marks=range(6, 133, 6)),
        row("Spark plug", ("spark_plugs",), marks=(60, 120)),
        row("Engine coolant", ("engine_coolant",), first_miles=137_500, first_months=132, every_miles=75_000,
            every_months=72),
        row("Timing Belt (WRX/WRX STI)", ("timing_belt",), marks=(96,), applies=False, why_not="WRX/WRX STI only"),
        row("Engine oil", ("engine_oil",), severe=True, every_miles=3000, every_months=3, page=2),
    )
