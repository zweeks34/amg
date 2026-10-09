"""A receipt's draft: your editable copy of what Claude read.

Pure functions only — no database. The draft starts as Claude's reading
(amounts turned into cents, line text matched against what you've tagged
before) and becomes whatever you correct it to. Confirming writes a service
event *from* the draft; the draft itself stays, so the receipt can be reopened
and corrected again later.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from ..repo.services import Coverage, EventInput, LineInput
from . import vin as vins
from .receipts import ReceiptExtraction, ReceiptWarranty

# Where a line's service types came from, shown beside them on review.
COVERS_SOURCES = ("claude", "learned", "you")


@dataclass
class Draft:
    document_kind: str = "invoice"
    shop: str = ""
    invoice_number: str = ""
    performed_on: str | None = None
    odometer: int | None = None
    printed_vin: str = ""        # as printed — evidence, not the car's VIN
    printed_plate: str = ""
    printed_vehicle: str = ""
    delivery_date: str | None = None
    next_service_date: str | None = None
    next_service_miles: int | None = None
    # {description, kind, part_number, quantity, amount_cents, covers: [{code, action}], covers_source}
    lines: list[dict] = field(default_factory=list)
    # {description, codes: [code], quoted_cents}
    recommendations: list[dict] = field(default_factory=list)
    # {description, provider, months, miles, lifetime, codes: [code], found}. ``found``: the day the look
    # through older receipts found it, not yet checked; it counts once you save the receipt. '' otherwise.
    warranties: list[dict] = field(default_factory=list)
    subtotal_cents: int | None = None
    tax_cents: int | None = None
    total_cents: int | None = None
    notes: str = ""
    read_note: str = ""          # what Claude found uncertain; shown, not edited

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Draft:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def cents(dollars: float | None) -> int | None:
    return None if dollars is None else round(dollars * 100)


def phrase(description: str) -> str:
    """A line's text reduced to what identifies it across receipts.

    Lower case, with digits and punctuation dropped and spaces collapsed, so
    "Added 4 QTS Standard Motor Oil" and "ADDED 5 QTS STANDARD MOTOR OIL" are the
    same phrase. Matching is exact on what's left: a shop's own wording repeats
    from visit to visit, and that repetition is what this is for.
    """
    text = re.sub(r"[^a-z]+", " ", description.lower())
    return re.sub(r"\s+", " ", text).strip()


def from_extraction(
    extraction: ReceiptExtraction,
    types: dict[str, dict],
    learned: dict[str, list[dict]] | None = None,
) -> Draft:
    """The first draft of a receipt, from Claude's reading.

    ``types`` maps code → service type (for default actions); ``learned`` maps
    phrase → covers you confirmed before, which win over Claude's suggestion.
    """
    learned = learned or {}
    lines = []
    for line in extraction.lines:
        known = phrase(line.description)
        if known and known in learned:
            covers = [c for c in learned[known] if c["code"] in types]
            source = "learned"
        else:
            covers = [{"code": code, "action": _action(line.action, types[code])}
                      for code in dict.fromkeys(line.service_codes) if code in types]
            source = "claude"
        lines.append({
            "description": line.description.strip(),
            "kind": line.kind,
            "part_number": line.part_number or "",
            "quantity": line.quantity,
            "amount_cents": cents(line.amount),
            "covers": covers,
            "covers_source": source,
        })
    recommendations = [
        {
            "description": rec.description.strip(),
            "codes": [code for code in dict.fromkeys(rec.service_codes) if code in types],
            "quoted_cents": cents(rec.quoted_amount),
        }
        for rec in extraction.recommendations
    ]
    done = list(dict.fromkeys(c["code"] for line in lines for c in line["covers"] if c["action"] != "inspect"))
    warranties = [warranty_row(w, types, done) for w in extraction.warranties]
    return Draft(
        document_kind=extraction.document_kind,
        shop=(extraction.shop_name or "").strip(),
        invoice_number=(extraction.invoice_number or "").strip(),
        performed_on=extraction.date,
        odometer=extraction.odometer,
        printed_vin=vins.normalize(extraction.vin or ""),
        printed_plate=normalize_plate(extraction.plate or ""),
        printed_vehicle=(extraction.vehicle or "").strip(),
        delivery_date=extraction.delivery_date,
        next_service_date=extraction.next_service_date,
        next_service_miles=extraction.next_service_miles,
        lines=lines,
        recommendations=recommendations,
        warranties=warranties,
        subtotal_cents=cents(extraction.subtotal),
        tax_cents=cents(extraction.tax),
        total_cents=cents(extraction.total),
        read_note=extraction.uncertain.strip(),
    )


def warranty_row(warranty: ReceiptWarranty, types: dict[str, dict], done: list[str], found: str = "") -> dict:
    """A warranty as a draft row. One that names no services covers what the visit replaced or performed.

    ``found`` is the day the look through older receipts found it: it waits
    to be checked until then.
    """
    codes = [code for code in dict.fromkeys(warranty.service_codes) if code in types] or done
    months = warranty.months if warranty.months and warranty.months > 0 else None
    miles = warranty.miles if warranty.miles and warranty.miles > 0 else None
    return {
        "description": warranty.description.strip(),
        "provider": (warranty.provider or "").strip(),
        "months": months,
        "miles": miles,
        "lifetime": warranty.lifetime and months is None and miles is None,
        "codes": list(codes),
        "found": found,
    }


def _action(read: str, service_type: dict) -> str:
    """Claude's action, except that an inspection-only type is never 'replaced'."""
    if service_type["default_action"] == "inspect" and read != "inspect":
        return "inspect"
    return read


def normalize_plate(plate: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", plate.upper())


def to_event(draft: Draft) -> EventInput:
    """The service event a confirmed draft records."""
    return EventInput(
        performed_on=draft.performed_on or "",
        source="receipt",
        odometer=draft.odometer,
        shop=draft.shop,
        invoice_number=draft.invoice_number,
        tax_cents=draft.tax_cents,
        total_cents=draft.total_cents,
        notes=draft.notes,
        lines=[
            LineInput(
                description=line["description"],
                kind=line["kind"],
                part_number=line.get("part_number", ""),
                quantity=line.get("quantity"),
                amount_cents=line.get("amount_cents"),
                covers=[Coverage(c["code"], c["action"]) for c in line["covers"]],
            )
            for line in draft.lines
        ],
    )


def learnable(draft: Draft) -> dict[str, list[dict]]:
    """phrase → covers for every line worth remembering on confirm."""
    result: dict[str, list[dict]] = {}
    for line in draft.lines:
        key = phrase(line["description"])
        if len(key) >= 3:
            result[key] = [{"code": c["code"], "action": c["action"]} for c in line["covers"]]
    return result


def mismatches(draft: Draft, car: dict) -> list[str]:
    """Where the receipt's printed details disagree with the car you chose.

    Shown as notes on review. They never change the car, and never block
    confirming: shops print the wrong car often enough that the person who
    owns it is the authority.
    """
    notes = []
    if draft.printed_vin and car.get("vin") and draft.printed_vin != car["vin"]:
        notes.append(f"The receipt prints VIN {draft.printed_vin}, which isn't {car['name']}'s VIN.")
    if draft.printed_plate and car.get("plate") and draft.printed_plate != normalize_plate(car["plate"]):
        notes.append(f"The receipt prints plate {draft.printed_plate}, which isn't {car['name']}'s plate.")
    printed = draft.printed_vehicle.lower()
    if printed and car.get("model") and car["model"].lower() not in printed:
        notes.append(f"The receipt describes the car as “{draft.printed_vehicle}”.")
    return notes
