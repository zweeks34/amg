"""A car's specs card: what to buy for it, and what your receipts say was fitted.

The card has a fixed catalogue of fields, grouped in the order you'd shop for
them, plus lines you name yourself. A field can name the service types whose
receipt lines might hold its value; those lines only *suggest* one (a button
on the form), since a shop's line says what went in that day, not what the
maker specifies. They also give each group its "last fitted": the newest
confirmed visit that replaced the part.

Pure: no database, no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

ALL = frozenset({"gas", "hybrid", "ev"})
ENGINE = frozenset({"gas", "hybrid"})
CUSTOM = "custom"          # the key of a line you named yourself
MAX_SUGGESTIONS = 3


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    group: str
    example: str                     # shown as the box's placeholder
    powertrains: frozenset[str] = ALL
    codes: tuple[str, ...] = ()      # service types whose receipt lines can suggest a value
    pick: str = ""                   # what to take from those lines: part, grade, tire or length


GROUPS = ("Engine oil", "Filters", "Wipers", "Tires and wheels", "Battery and bulbs", "Fluids", "Fuel and ignition")
OTHER = "Other"

FIELDS: dict[str, Field] = {f.key: f for f in (
    Field("oil_grade", "Oil grade", "Engine oil", "0W-20 synthetic", ENGINE, ("engine_oil",), "grade"),
    Field("oil_capacity", "Oil capacity, with filter", "Engine oil", "4.4 US qt", ENGINE),
    Field("oil_filter", "Oil filter", "Engine oil", "Subaru 15208AA15A", ENGINE, ("oil_filter",), "part"),
    Field("engine_air_filter", "Engine air filter", "Filters", "Subaru 16546AA12A", ENGINE, ("engine_air_filter",), "part"),
    Field("cabin_air_filter", "Cabin air filter", "Filters", "Subaru 72880FL00A", ALL, ("cabin_air_filter",), "part"),
    Field("wiper_driver", "Driver's wiper blade", "Wipers", "26 in", ALL, ("wiper_blades",), "length"),
    Field("wiper_passenger", "Passenger's wiper blade", "Wipers", "17 in", ALL, ("wiper_blades",), "length"),
    Field("wiper_rear", "Rear wiper blade", "Wipers", "14 in", ALL, ("wiper_blades",), "length"),
    Field("tire_size", "Tire size", "Tires and wheels", "225/65R17 102H", ALL, ("tires",), "tire"),
    Field("tire_pressure", "Tire pressure, cold", "Tires and wheels", "35 psi front, 33 psi rear"),
    Field("lug_torque", "Lug nut torque", "Tires and wheels", "89 lb-ft"),
    Field("battery", "12-volt battery", "Battery and bulbs", "Group 35, 550 CCA", ALL, ("battery_12v",), "part"),
    Field("key_fob_battery", "Key fob battery", "Battery and bulbs", "CR2032"),
    Field("headlight_low", "Headlight, low beam", "Battery and bulbs", "H11", ALL, ("lights",), "part"),
    Field("headlight_high", "Headlight, high beam", "Battery and bulbs", "9005", ALL, ("lights",), "part"),
    Field("fog_light", "Fog lights", "Battery and bulbs", "H16", ALL, ("lights",), "part"),
    Field("brake_light", "Brake light", "Battery and bulbs", "7443", ALL, ("lights",), "part"),
    Field("coolant", "Engine coolant", "Fluids", "Subaru Super Coolant", ENGINE, ("engine_coolant",), "part"),
    Field("transmission_fluid", "Transmission fluid", "Fluids", "Subaru High Torque CVTF", ALL,
          ("transmission_fluid",), "part"),
    Field("differential_oil", "Differential oil", "Fluids", "75W-90 GL-5", ALL, ("differential_fluid",), "part"),
    Field("brake_fluid", "Brake fluid", "Fluids", "DOT 3", ALL, ("brake_fluid",), "part"),
    Field("fuel", "Fuel", "Fuel and ignition", "87 octane", ENGINE),
    Field("fuel_tank", "Fuel tank", "Fuel and ignition", "18.5 gal", ENGINE),
    Field("spark_plugs", "Spark plugs", "Fuel and ignition", "NGK SILZKAR7B11", ENGINE, ("spark_plugs",), "part"),
)}


def for_car(powertrain: str, with_values: Iterable[str] = ()) -> list[tuple[str, list[Field]]]:
    """The catalogue's groups for a car: the fields its powertrain has, and any field holding a value."""
    keep = set(with_values)
    groups: list[tuple[str, list[Field]]] = []
    for group in GROUPS:
        fields = [f for f in FIELDS.values() if f.group == group and (powertrain in f.powertrains or f.key in keep)]
        if fields:
            groups.append((group, fields))
    return groups


def group_codes(fields: Iterable[Field]) -> list[str]:
    """The service types a group's fields look to, in field order, once each."""
    return list(dict.fromkeys(code for f in fields for code in f.codes))


# ---------- What your receipts say ----------


_GRADE = re.compile(r"(?<!\d)(\d{1,2})\s?W\s?-?\s?(\d{2})(?!\d)", re.I)
_TIRE = re.compile(r"(?<!\d)(\d{3})\s?/\s?(\d{2})\s?Z?R\s?(\d{2})(?!\d)", re.I)
_LENGTH = re.compile(r"(?<![\d.])(1\d|2\d|3[0-2])\s?(?:in(?:ch(?:es)?)?\b|\"|'')", re.I)   # a wiper blade, 10 to 32 in


def candidates(field: Field, lines: Sequence[Mapping]) -> list[str]:
    """Values your receipt lines offer for a field, newest first, at most three.

    ``lines`` are line items that replaced one of the field's service types,
    newest first (repo.specs.fitted_lines). A part number is the best answer;
    failing one, a part line's description, but only when it has a number in
    it: "Battery H6 AGM" says which, "Battery" doesn't. A wiper blade's
    length beats its part number, since any brand's 26 in blade fits.
    """
    found: list[str] = []
    for line in lines:
        if line["code"] not in field.codes:
            continue
        text = f"{line['description']} {line['part_number']}"
        if field.pick == "grade":
            values = [f"{m[1]}W-{m[2]}" for m in _GRADE.finditer(text)]
        elif field.pick == "tire":
            values = [f"{m[1]}/{m[2]}R{m[3]}" for m in _TIRE.finditer(text)]
        elif field.pick in ("part", "length"):
            lengths = [f"{m[1]} in" for m in _LENGTH.finditer(line["description"])] if field.pick == "length" else []
            values = lengths or _part(line)
        else:
            values = []
        for value in values:
            if value.upper() not in {v.upper() for v in found}:
                found.append(value)
    return found[:MAX_SUGGESTIONS]


def _part(line: Mapping) -> list[str]:
    if line["part_number"].strip():
        return [line["part_number"].strip()]
    if line["kind"] == "part" and re.search(r"\d", line["description"]):
        return [line["description"].strip()]
    return []


@dataclass(frozen=True)
class Fitted:
    day: date
    shop: str
    event_id: int
    lines: tuple[str, ...]   # what went in, as the receipt words it


def line_words(line: Mapping) -> str:
    """'Oil filter 15208AA15A', '0W-20 full synthetic × 5'."""
    words = line["description"].strip()
    part = line["part_number"].strip()
    if part and part.upper() not in words.upper():
        words = f"{words} {part}".strip()
    quantity = line["quantity"]
    if quantity and quantity != 1:
        words += f" × {quantity:g}"
    return words


def last_fitted(lines: Sequence[Mapping], codes: Sequence[str]) -> list[Fitted]:
    """For a group's service types, the newest visit that replaced each, newest first.

    Two types replaced on one visit (oil and its filter) make one entry. Its
    lines are the part lines for those types, or every line when the visit
    has no part lines for them (a labour-only line, or "done, no receipt").
    """
    newest: dict[str, int] = {}
    for line in lines:   # newest first, so the first visit seen for a type is its newest
        if line["code"] in codes:
            newest.setdefault(line["code"], line["event_id"])
    visits = dict.fromkeys(newest[code] for code in codes if code in newest)
    fitted: list[Fitted] = []
    for event_id in visits:
        mine = [line for line in lines if line["event_id"] == event_id and newest.get(line["code"]) == event_id]
        parts = [line for line in mine if line["kind"] == "part"] or mine
        words = tuple(dict.fromkeys(line_words(line) for line in parts))
        first = mine[0]
        fitted.append(Fitted(date.fromisoformat(first["performed_on"]), first["shop"], event_id, words))
    return sorted(fitted, key=lambda f: (f.day, f.event_id), reverse=True)
