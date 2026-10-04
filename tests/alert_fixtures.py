"""A car for the alert tests. tests/ is on pytest's path, so: import alert_fixtures as af.

New on 2026-01-01, no odometer readings, so everything is judged by months.
Oil and filter every 6 months falls due 2026-07-01: due soon from June 1 (30
days out), overdue from July 1. Wiper blades first at 8 months, 2026-09-01:
due soon from August 2. The cabin air filter every 24 months, 2028-01-01:
later throughout.
"""

from __future__ import annotations

from datetime import date

from amg.repo import alerts, schedules, services, vehicles
from amg.repo.schedules import ItemInput

JUNE_10, JULY_2 = date(2026, 6, 10), date(2026, 7, 2)
OIL = ItemInput("Oil and filter", "replace", ["engine_oil", "oil_filter"], interval_months=6)
WIPERS = ItemInput("Wiper blades", "replace", ["wiper_blades"], interval_months=6, first_months=8)
CABIN = ItemInput("Cabin air filter", "replace", ["cabin_air_filter"], interval_months=24)


def schedule(conn, car, items):
    draft_id = schedules.create_draft(conn, car, "template", draft={"origin": "template", "items": []})
    schedules.confirm(conn, draft_id, car, items, {"origin": "template", "items": []})


def oil_change(conn, car, day, cents=6_000):
    return services.create_event(conn, car, services.EventInput(
        performed_on=day.isoformat(), source="shop", shop="Corner Garage",
        lines=[services.LineInput("Oil and filter", "labor", amount_cents=cents,
                                  covers=[services.Coverage("engine_oil", "replace"),
                                          services.Coverage("oil_filter", "replace")])]))


def make_car(conn, name="Outback", on=True):
    car = vehicles.create(conn, vehicles.VehicleFields(name=name, in_service_date="2026-01-01"))
    schedule(conn, car, [OIL, WIPERS, CABIN])
    alerts.switch(conn, car, on)
    return car
