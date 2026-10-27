"""The icon for a kind of service: a drop and a filter for an oil change, a spark plug for spark plugs.

The pictures are ``static/icons.svg``; this picks one from what a job covers.
A job covering engine oil and the oil filter is an oil change. Otherwise the
first of its service types to have an icon wins, in the catalogue's order
(the order below), so "Engine air filter and cabin air filter" is the engine
air filter. Your own service types, and anything else, take their category's
icon; failing that, the wrench.
"""

from __future__ import annotations

from collections.abc import Iterable

# Every type in the catalogue (migrations 0003 and 0010), in its order.
BY_CODE = {
    "engine_oil": "oil",
    "oil_filter": "oil-filter",
    "engine_air_filter": "air-filter",
    "spark_plugs": "spark-plug",
    "drive_belts": "belt",
    "timing_belt": "belt",
    "valve_clearance": "valve",
    "engine_coolant": "coolant",
    "cooling_system": "coolant",
    "fuel_system": "fuel",
    "fuel_filter": "fuel",
    "transmission_fluid": "gear",
    "differential_fluid": "gear",
    "transfer_case_fluid": "gear",
    "clutch": "gear",
    "brake_fluid": "brake-fluid",
    "brake_pads": "brake",
    "brake_rotors": "brake",
    "brake_system": "brake-fluid",
    "tire_rotation": "rotation",
    "tires": "tire",
    "wheel_alignment": "alignment",
    "wheel_balance": "tire",
    "tire_repair": "tire",
    "wheel_bearings": "tire",
    "steering_suspension": "steering",
    "axle_boots": "spring",
    "shocks_struts": "spring",
    "battery_12v": "battery",
    "wiper_blades": "wiper",
    "washer_fluid": "washer",
    "lights": "lamp",
    "cabin_air_filter": "cabin-filter",
    "air_conditioning": "snowflake",
    "inverter_coolant": "coolant",
    "hybrid_battery": "hv-battery",
    "hybrid_battery_filter": "hv-battery",
    "ev_battery_coolant": "coolant",
    "ev_battery": "hv-battery",
    "multipoint_inspection": "clipboard",
    "state_inspection": "clipboard",
    "emissions_test": "exhaust",
    "exhaust": "exhaust",
    "recall": "flag",
    "software_update": "chip",
    "other": "wrench",
}

BY_CATEGORY = {
    "Engine": "engine",
    "Drivetrain": "gear",
    "Brakes": "brake",
    "Tires and wheels": "tire",
    "Steering and suspension": "spring",
    "Electrical": "battery",
    "Cabin": "cabin-filter",
    "Hybrid and EV": "hv-battery",
    "Inspections and other": "clipboard",
}

OIL_CHANGE = "oil-change"
FALLBACK = "wrench"


def icon_for(codes: Iterable[str], category: str | None = None) -> str:
    """The icon's name in icons.svg for a job covering these service types (in this category, if known)."""
    codes = set(codes or ())
    if {"engine_oil", "oil_filter"} <= codes:
        return OIL_CHANGE
    for code, icon in BY_CODE.items():
        if code in codes:
            return icon
    return BY_CATEGORY.get(category or "", FALLBACK)
