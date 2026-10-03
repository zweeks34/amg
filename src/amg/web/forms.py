"""Reading what people type into forms.

Each parser takes the raw text and returns the stored value, or raises
``ValueError`` with a message that can go straight under the field. An empty
field is ``None`` — whether it is allowed to be empty is the route's call.
"""

from __future__ import annotations

import re
from datetime import date, datetime


def text(value: str | None) -> str:
    return (value or "").strip()


def miles(value: str | None) -> int | None:
    """'32,610' / '32610 mi' / '32 610' → 32610."""
    raw = re.sub(r"(?i)\s*(mi|miles)\.?$", "", text(value)).replace(",", "").replace(" ", "")
    if not raw:
        return None
    if not raw.isdigit():
        raise ValueError("Enter whole miles, like 32,610.")
    number = int(raw)
    if number > 2_000_000:
        raise ValueError("That's more miles than any car drives. Check for an extra digit.")
    return number


def money(value: str | None) -> int | None:
    """'$1,234.56' / '1234.5' / '89' → cents."""
    raw = text(value).replace("$", "").replace(",", "").replace(" ", "")
    if not raw:
        return None
    negative = raw.startswith("-") or (raw.startswith("(") and raw.endswith(")"))
    raw = raw.strip("-()")
    if not re.fullmatch(r"\d+(\.\d{1,2})?|\.\d{1,2}", raw):
        raise ValueError("Enter an amount like 89.99.")
    whole, _, frac = raw.partition(".")
    cents = int(whole or 0) * 100 + int((frac + "00")[:2])
    return -cents if negative else cents


def day(value: str | None, allow_future: bool = False) -> str | None:
    """'2016-08-15' (from a date picker) or '08/15/2016' → '2016-08-15'.

    Dates of things that happened can't be in the future; a reminder of when
    something is due can (``allow_future``).
    """
    raw = text(value)
    if not raw:
        return None
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            parsed = datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
        if parsed > date.today() and not allow_future:
            raise ValueError("That date is in the future.")
        if parsed.year < 1900:
            raise ValueError("Check the year.")
        return parsed.isoformat()
    raise ValueError("Enter a date like 2016-08-15.")


def year(value: str | None) -> int | None:
    raw = text(value)
    if not raw:
        return None
    if not (raw.isdigit() and 1900 <= int(raw) <= date.today().year + 2):
        raise ValueError("Enter a model year like 2016.")
    return int(raw)


def months(value: str | None) -> int | None:
    """'6' / '24 months' → 6 / 24. Whole months, for schedule intervals."""
    raw = re.sub(r"(?i)\s*(months?|mos?)\.?$", "", text(value))
    if not raw:
        return None
    if not raw.isdigit() or int(raw) == 0:
        raise ValueError("Enter whole months, like 6.")
    if int(raw) > 600:
        raise ValueError("That's more than 50 years. Check for an extra digit.")
    return int(raw)


# Gallons or kWh: more than this went into no car, so it's a typo.
_MOST = {"gal": 100, "kWh": 300}


def amount(value: str | None, unit: str) -> float | None:
    """'11.482' / '11.482 gal' / '42.5 kWh' → 11.482. What went into a tank or battery: above zero, to 3 places."""
    raw = re.sub(r"(?i)\s*(gal|gallons?|kwh)\.?$", "", text(value)).replace(",", "").replace(" ", "")
    if not raw:
        return None
    words, example = ("gallons", "11.482") if unit == "gal" else ("kWh", "42.5")
    if not re.fullmatch(r"\d+(\.\d{1,3})?|\.\d{1,3}", raw) or float(raw) == 0:
        raise ValueError(f"Enter the {words} that went in, like {example}.")
    if float(raw) > _MOST[unit]:
        holds = "tank holds" if unit == "gal" else "battery takes"
        raise ValueError(f"That's more than a {holds}. Check for an extra digit.")
    return float(raw)


def quantity(value) -> float | None:
    """'2' / '1.5' / '-1' → a number. Receipts print -1 on credits and returns,
    such as a manufacturer's warranty credit against a tire."""
    raw = text(str(value) if value is not None else "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        raise ValueError("Enter a number.") from None
