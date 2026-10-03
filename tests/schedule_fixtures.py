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


# ---------- A car to hand-check the gap engine against ----------
#
# Driven 30 mi a day from new, so day n is at n × 30 miles. Five schedule items and
# five services; tests/amg/web/test_status.py works out every mark of its chart by hand.

def steady_car(conn, start):
    """The hand-checked car, new on ``start``: (vehicle id, day number → date, {day number: service id})."""
    from datetime import timedelta

    from amg.repo import schedules, services, vehicles
    from amg.repo.schedules import ItemInput

    def day(n):
        return start + timedelta(days=n)

    car = vehicles.create(conn, vehicles.VehicleFields(name="Steady", year=2020, make="Test", model="Car",
                                                       in_service_date=start.isoformat()))
    items = [
        ItemInput("Engine oil and filter", "replace", ["engine_oil", "oil_filter"], interval_miles=6000, interval_months=12),
        ItemInput("Engine coolant", "replace", ["engine_coolant"], interval_miles=30_000, interval_months=36,
                  first_miles=50_000, first_months=60),
        ItemInput("Brake inspection", "inspect", ["brake_pads", "brake_rotors"], interval_miles=12_000, interval_months=12),
        ItemInput("Tire rotation", "perform", ["tire_rotation"], interval_miles=6000),
        ItemInput("Cabin air filter", "replace", ["cabin_air_filter"], interval_months=12),
    ]
    draft_id = schedules.create_draft(conn, car, "template", draft={"origin": "template", "items": []})
    schedules.confirm(conn, draft_id, car, items, {"origin": "template", "items": []})

    def visit(n, *covers):
        lines = [services.LineInput(description=code, covers=[services.Coverage(code, action)]) for code, action in covers]
        return services.create_event(conn, car, services.EventInput(performed_on=day(n).isoformat(), source="shop",
                                                                    shop="Corner Garage", odometer=n * 30, lines=lines))

    visits = {
        190: visit(190, ("engine_oil", "replace"), ("tire_rotation", "perform"), ("multipoint_inspection", "inspect")),
        380: visit(380, ("cabin_air_filter", "replace")),
        400: visit(400, ("engine_oil", "replace")),
        640: visit(640, ("engine_oil", "replace"), ("tire_rotation", "perform")),
        900: visit(900, ("tire_rotation", "perform"), ("brake_pads", "inspect")),
    }
    return car, day, visits
