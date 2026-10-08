"""Recalls: asking NHTSA which it lists for a car's year, make and model.

NHTSA's recalls service is free and needs no key, like the VIN decoder. It
lists recalls by model year, not by VIN, so a recall for some of a year's cars
(a range of build dates) is listed for all of them, and AMG never sends the
VIN. Whether one fits this car is for you, the dealer, or nhtsa.gov/recalls
with the VIN, to say.

Model names are NHTSA's own ("OUTBACK", "MODEL 3"). So AMG first asks which of
the year's models from that make have recalls, and matches the car's model to
one: exactly, else the longest NHTSA name the car's model starts with
("Outback Limited" is an OUTBACK). With no match there are no recalls to ask
for, and the car's page lists NHTSA's names so a naming difference shows.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime

MODELS_URL = "https://api.nhtsa.gov/products/vehicle/models?modelYear={year}&make={make}&issueType=r"
RECALLS_URL = "https://api.nhtsa.gov/recalls/recallsByVehicle?make={make}&model={model}&modelYear={year}"
TIMEOUT = 10.0   # seconds
UNREACHABLE = "Couldn't reach NHTSA's recall service."


class RecallLookupError(Exception):
    """NHTSA couldn't be asked; the message says why, in words for the page."""


@dataclass(frozen=True)
class Recall:
    campaign: str             # NHTSA's campaign number, "19V910000"
    reported_on: str | None   # ISO date NHTSA received the report
    component: str
    summary: str
    consequence: str
    remedy: str
    park_it: bool             # don't drive it until it's fixed
    park_outside: bool        # park it outside, away from buildings


@dataclass(frozen=True)
class Lookup:
    model: str                # NHTSA's model name the car matched; '' for none
    listed: tuple[str, ...]   # NHTSA's models of that year and make with recalls
    recalls: tuple[Recall, ...]


def _get(url: str) -> dict:
    """The one place AMG talks to NHTSA's recall service. Tests swap it out (tests/conftest.py)."""
    request = urllib.request.Request(url, headers={"User-Agent": "AMG/0.1", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as err:
        if err.code in (400, 404):
            return {}   # NHTSA's answer when it lists nothing for the question
        raise RecallLookupError(f"{UNREACHABLE} It answered {err.code}.") from err
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
        raise RecallLookupError(UNREACHABLE) from err


def models(year: int, make: str) -> tuple[str, ...]:
    payload = _get(MODELS_URL.format(year=year, make=urllib.parse.quote(make.strip())))
    return tuple(sorted({(row.get("model") or "").strip().upper() for row in payload.get("results") or []} - {""}))


def match(model: str, listed: tuple[str, ...]) -> str:
    """NHTSA's name for the car's model: the same name, else the longest it starts with; '' for none."""
    wanted = " ".join(model.upper().split())
    if wanted in listed:
        return wanted
    return max((name for name in listed if wanted.startswith(name + " ")), key=len, default="")


def lookup(year: int, make: str, model: str) -> Lookup:
    listed = models(year, make)
    matched = match(model, listed)
    if not matched:
        return Lookup("", listed, ())
    payload = _get(RECALLS_URL.format(make=urllib.parse.quote(make.strip()), model=urllib.parse.quote(matched),
                                      year=year))
    return Lookup(matched, listed, tuple(parse(payload)))


def parse(payload: dict) -> list[Recall]:
    """A recallsByVehicle response as recalls, each campaign once."""
    found: dict[str, Recall] = {}
    for row in payload.get("results") or []:
        campaign = _text(row.get("NHTSACampaignNumber"))
        if campaign and campaign not in found:
            found[campaign] = Recall(
                campaign=campaign, reported_on=_day(row.get("ReportReceivedDate")),
                component=_text(row.get("Component")), summary=_text(row.get("Summary")),
                consequence=_text(row.get("Consequence")), remedy=_text(row.get("Remedy")),
                park_it=row.get("parkIt") is True, park_outside=row.get("parkOutSide") is True,
            )
    return list(found.values())


def campaign_words(campaign: str) -> str:
    """NHTSA's campaign number as it's usually written: 19V910000 → 19V-910."""
    found = re.fullmatch(r"(\d{2}[A-Z])(\d{3})000", campaign)
    return f"{found[1]}-{found[2]}" if found else campaign


def _text(value) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _day(value) -> str | None:
    """NHTSA writes dates day first, '19/12/2019'; anything else unreadable is no date."""
    text = _text(value)[:10]
    for pattern in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return None
