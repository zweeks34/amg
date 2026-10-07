"""Generic schedules to start from when there's no manual to read.

Deliberately middle-of-the-road intervals for a modern car of each
powertrain — not any maker's. They're for a car whose manual is lost, and as
a starting point to correct; a template goes through the same review as a
manual's schedule, and its items stay labelled as the template's.

Items that only some cars have (a timing belt, AWD's differentials) are
included but left out, so they're one tap away rather than missing.
"""

from __future__ import annotations

from .schedule_drafts import ScheduleDraft, blank_item

LABELS = {"gas": "Gasoline", "hybrid": "Hybrid", "ev": "Electric"}

READ_NOTE = ("A generic schedule, not your car maker's. Check each item against your owner's manual if you can, "
             "and change what differs.")

SEVERE_CONDITIONS = "\n".join([
    "Mostly short trips, under 5 miles",
    "Stop-and-go traffic or long idling",
    "Towing or carrying heavy loads",
    "Dusty, muddy, gravel or salted roads",
    "Extreme heat or cold",
])


def _item(name, codes, action, miles=None, months=None, first_miles=None, first_months=None, applies="always",
          note="", included=True, why_not=""):
    return dict(name=name, codes=list(codes), action=action, interval_miles=miles, interval_months=months,
                first_miles=first_miles, first_months=first_months, applies=applies, note=note,
                included=included, why_not=why_not)


_CHASSIS = [
    _item("Tire rotation", ["tire_rotation"], "perform", miles=7_500),
    _item("Brake pads, rotors and lines", ["brake_pads", "brake_rotors", "brake_system"], "inspect", 15_000, 12),
    _item("Steering, suspension and axle boots", ["steering_suspension", "axle_boots"], "inspect", 15_000, 12),
    _item("Cabin air filter", ["cabin_air_filter"], "replace", 15_000, 12),
    _item("Wiper blades", ["wiper_blades"], "replace", months=12),
    _item("Washer fluid", ["washer_fluid"], "replace", months=3, included=False,
          why_not="Only if you want reminders: most cars warn when it runs low"),
    _item("12-volt battery", ["battery_12v"], "inspect", months=12),
]

_ENGINE = [
    _item("Engine oil and filter", ["engine_oil", "oil_filter"], "replace", 7_500, 12, applies="normal",
          note="Many cars call for anything from 5,000 to 10,000 mi."),
    _item("Engine oil and filter", ["engine_oil", "oil_filter"], "replace", 3_750, 6, applies="severe"),
    _item("Engine air filter", ["engine_air_filter"], "replace", 30_000, 36),
    _item("Spark plugs", ["spark_plugs"], "replace", miles=100_000,
          note="Iridium plugs. Older cars with copper or platinum plugs: about 30,000–60,000 mi."),
    _item("Drive belts", ["drive_belts"], "inspect", 30_000, 36),
    _item("Engine coolant", ["engine_coolant"], "replace", 50_000, 60, first_miles=100_000, first_months=120),
    _item("Cooling system and hoses", ["cooling_system"], "inspect", 30_000, 24),
    _item("Transmission fluid", ["transmission_fluid"], "inspect", 30_000, 24,
          note="Replacement intervals vary widely between transmissions."),
    _item("Timing belt", ["timing_belt"], "replace", 100_000, 120, included=False,
          why_not="Only engines with a timing belt, not a chain"),
    _item("Differential fluid", ["differential_fluid"], "replace", 30_000, 36, included=False,
          why_not="Only AWD, 4WD and rear-wheel-drive cars"),
]

_BRAKE_FLUID = _item("Brake fluid", ["brake_fluid"], "replace", months=36)

_HYBRID = [
    _item("Inverter coolant", ["inverter_coolant"], "replace", 50_000, 60, first_miles=150_000, first_months=120),
    _item("Hybrid battery cooling filter", ["hybrid_battery_filter"], "inspect", 15_000, 12,
          note="Clean it more often with pets or dust in the car."),
    _item("Hybrid battery", ["hybrid_battery"], "inspect", months=12),
]

_EV = [
    _item("Brake fluid", ["brake_fluid"], "replace", months=24),
    _item("Battery coolant", ["ev_battery_coolant"], "replace", 100_000, 120,
          note="Varies widely between makers; some fill it for life."),
    _item("High-voltage battery", ["ev_battery"], "inspect", months=12),
    _item("Cooling system and hoses", ["cooling_system"], "inspect", 30_000, 24),
    _item("Air conditioning", ["air_conditioning"], "perform", months=24,
          note="Desiccant bag or A/C service, where the maker calls for one."),
]

_ITEMS = {
    "gas": [*_ENGINE, _BRAKE_FLUID, *_CHASSIS],
    "hybrid": [*_ENGINE, _BRAKE_FLUID, *_HYBRID, *_CHASSIS],
    "ev": [*_EV, *_CHASSIS],
}


def draft(powertrain: str) -> ScheduleDraft:
    """A fresh copy of a template as a draft, its items labelled as the template's."""
    if powertrain not in _ITEMS:
        raise ValueError(f"No template for {powertrain!r}.")
    return ScheduleDraft(
        origin="template",
        printed_for=f"AMG's generic {LABELS[powertrain].lower()} schedule",
        severe_conditions=SEVERE_CONDITIONS,
        read_note=READ_NOTE,
        items=[blank_item(**{**values, "codes": list(values["codes"])}, source="template")
               for values in _ITEMS[powertrain]],
    )
