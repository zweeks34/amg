"""VINs: checking one, and asking NHTSA which car it belongs to.

The check is local and exact for any North American VIN since 1981: 17
characters, never I, O or Q, and position 9 a check digit computed from the
other sixteen. A wrong check digit almost always means one mistyped character,
which is worth catching before the VIN is saved and decoded into the wrong car.

Decoding uses NHTSA's vPIC service — free, no key, and the same data the
federal recall system uses. It is only ever a convenience: if it is down or
does not know the VIN, every field can be typed by hand.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

VPIC_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"

_VALUES = {
    **{str(d): d for d in range(10)},
    **dict(zip("ABCDEFGH", range(1, 9))),
    **dict(zip("JKLMN", range(1, 6))),
    "P": 7, "R": 9,
    **dict(zip("STUVWXYZ", range(2, 10))),
}
_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)

# Makes vPIC returns in capitals that should stay that way.
_UPPERCASE_MAKES = {"BMW", "GMC", "MINI", "RAM", "AMC", "MG"}


class VinLookupError(Exception):
    """The VIN could not be decoded; the message says why, in words for the page."""


@dataclass
class Decoded:
    year: int | None
    make: str
    model: str
    trim: str
    engine: str
    powertrain: str


def normalize(vin: str) -> str:
    return re.sub(r"[\s-]+", "", vin or "").upper()


def check_digit(vin: str) -> str:
    total = sum(_VALUES[ch] * weight for ch, weight in zip(vin, _WEIGHTS))
    remainder = total % 11
    return "X" if remainder == 10 else str(remainder)


def problem(vin: str) -> str | None:
    """Why this (normalized) VIN can't be right, or None if it checks out."""
    if len(vin) != 17:
        return f"A VIN has 17 characters; this one has {len(vin)}."
    if set(vin) & set("IOQ"):
        return "VINs never use the letters I, O or Q. Check for a 1 or a 0."
    if not re.fullmatch(r"[A-Z0-9]{17}", vin):
        return "A VIN is only letters and digits."
    if vin[8] != check_digit(vin):
        return "This VIN's check digit doesn't match, so one character is probably mistyped."
    return None


def decode(vin: str, timeout: float = 10.0) -> Decoded:
    request = urllib.request.Request(VPIC_URL.format(vin=vin), headers={"User-Agent": "AMG/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
        raise VinLookupError(
            "Couldn't reach NHTSA's VIN service. Fill in the details by hand, or try again later."
        ) from err
    return parse(payload)


def parse(payload: dict) -> Decoded:
    """Turn a vPIC DecodeVinValues response into the fields AMG keeps."""
    results = payload.get("Results") or [{}]
    r = {k: (v or "").strip() if isinstance(v, str) else v for k, v in results[0].items()}
    if not r.get("Make"):
        raise VinLookupError("NHTSA doesn't recognise this VIN. Fill in the details by hand.")

    make = r["Make"] if r["Make"] in _UPPERCASE_MAKES else r["Make"].title()
    year = int(r["ModelYear"]) if str(r.get("ModelYear", "")).isdigit() else None
    return Decoded(
        year=year,
        make=make,
        model=r.get("Model", ""),
        trim=r.get("Trim") or r.get("Series") or "",
        engine=_engine(r),
        powertrain=_powertrain(r),
    )


def _engine(r: dict) -> str:
    parts = []
    try:
        if r.get("DisplacementL"):
            parts.append(f"{float(r['DisplacementL']):.1f}L")
    except ValueError:
        pass
    if r.get("EngineCylinders"):
        parts.append(f"{r['EngineCylinders']}-cyl")
    if (r.get("Turbo") or "").lower() == "yes":
        parts.append("turbo")
    if not parts and _powertrain(r) == "ev":
        return "Electric"
    return " ".join(parts)


def _powertrain(r: dict) -> str:
    level = (r.get("ElectrificationLevel") or "").upper()
    fuel = (r.get("FuelTypePrimary") or "").lower()
    if level.startswith(("BEV", "FCEV")) or fuel == "electric":
        return "ev"
    if "HEV" in level:  # HEV, Strong HEV, Mild HEV, PHEV
        return "hybrid"
    return "gas"
