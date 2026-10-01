"""Reading a service receipt into structured fields with Claude.

Three ways to show Claude a receipt, chosen per call:

* ``text``   — the file's own text layer, or Tesseract's OCR for pages that
               have none. Cheapest; only as good as that text.
* ``vision`` — each page as an image. Reads the page the way a person does:
               columns, stamps, handwriting, faint thermal print.
* ``both``   — the images, with the local text as a hint for small print.

Whatever comes back is a *draft*: nothing here writes to the database, and
``checks()`` lists what a person should look at before confirming it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from . import claude, ocr, pdf, vin

Mode = Literal["text", "vision", "both"]
MODES: tuple[str, ...] = ("text", "vision", "both")

# Pages whose own text layer is shorter than this are treated as having none.
MIN_TEXT_LAYER_CHARS = 40


# ---------- What Claude returns ----------


class ReceiptLine(BaseModel):
    description: str = Field(description="The line as printed, with obvious OCR noise cleaned up. Keep the shop's wording.")
    kind: Literal["labor", "part", "fee", "other"]
    part_number: str | None = Field(description="Part number if printed on this line.")
    quantity: float | None
    amount: float | None = Field(description="This line's extended amount in dollars, as printed. Negative for discounts. Null if no amount is printed for it.")
    service_codes: list[str] = Field(description="Codes from the catalogue that this line's work covers. Empty if none fit.")
    action: Literal["replace", "inspect", "perform"] = Field(description="replace: new part or fluid installed. inspect: only checked. perform: a procedure such as a rotation or alignment.")


class Recommendation(BaseModel):
    description: str
    service_codes: list[str]
    quoted_amount: float | None


DocumentKind = Literal["invoice", "estimate", "deposit", "inspection_report", "other"]
DOCUMENT_KINDS: tuple[str, ...] = ("invoice", "estimate", "deposit", "inspection_report", "other")


class ReceiptExtraction(BaseModel):
    document_kind: DocumentKind = Field(description="invoice: a bill or receipt for work done. estimate: a quote or estimate. deposit: a receipt for a deposit or prepayment. inspection_report: an inspection checklist with no charges. other: anything else.")
    shop_name: str | None
    invoice_number: str | None
    date: str | None = Field(description="The date the work was done, or the invoice date, as YYYY-MM-DD.")
    odometer: int | None = Field(description="The vehicle's mileage for this visit, in whole miles. Prefer mileage out, else mileage in.")
    vin: str | None = Field(description="The 17-character VIN if printed. VINs never contain I, O or Q, so read those as 1, 0 and 0.")
    plate: str | None = Field(description="The licence plate as printed, letters and digits only, without the state.")
    vehicle: str | None = Field(description="Year, make and model as printed, e.g. '2016 Subaru Outback'.")
    delivery_date: str | None = Field(description="The date the vehicle was first delivered or sold new, if printed (dealer invoices often show it as Delivery Date or In-Service Date), as YYYY-MM-DD.")
    next_service_date: str | None = Field(description="When the shop says the next service is due, if written on the document, as YYYY-MM-DD.")
    next_service_miles: int | None = Field(description="The mileage at which the shop says the next service is due, if written on the document.")
    lines: list[ReceiptLine] = Field(description="The document's work items and charges, in order. For an estimate or deposit, the items it lists.")
    recommendations: list[Recommendation] = Field(description="Work the document itself marks as recommended, declined, deferred or due next time.")
    subtotal: float | None
    tax: float | None
    total: float | None = Field(description="The total the customer paid or owes for this visit.")
    uncertain: str = Field(description="Anything illegible or ambiguous, in one or two short sentences. Empty if everything was clear.")


SYSTEM_PROMPT = """\
You read automobile service receipts and invoices for a car owner's personal maintenance log.

Report what the document says, not what is typical: if a value isn't printed, use null. Never invent \
amounts, dates or mileage.

What kind of document it is. Most are invoices. Some are estimates, quotes or deposit receipts — \
often marked as such, sometimes stamped "not an invoice". Say which in `document_kind`, and still \
list the document's items in `lines`: the owner decides whether the work was done.

Work done versus not done. Dealer invoices often mix in recommended or declined work, "next service \
due" reminders, multi-point inspection checklists, coupons and warranty boilerplate. Only the work \
and charges of this visit go in `lines`. Work the document marks as recommended, declined, deferred \
or "due next time" goes in `recommendations`. A multi-point inspection is one line covering \
multipoint_inspection; the checklist's individual findings are not separate lines. A handwritten or \
printed "next service due" date or mileage goes in next_service_date and next_service_miles only — \
a reminder of when to come back is not a recommendation.

Vehicle details. Copy the VIN, plate and vehicle exactly as printed, even if they look inconsistent \
with each other — shops make mistakes, and the owner sorts them out.

Amounts are dollars as printed. A line's amount is its extended price (quantity times unit price). \
`total` is what the customer paid or owes for the visit; when warranty or a coupon covers work, \
use the customer-pay figure.

Service codes come from the catalogue below and nowhere else. One line can cover several codes: \
"oil and filter change" covers engine_oil and oil_filter. Use `other` for real repairs that fit no \
code. A line that covers no maintenance (shop supplies, disposal fees, a car wash) gets an empty \
list. Choose the action by what happened: replace when a part or fluid was installed, inspect when \
it was only checked, perform for procedures such as rotations and alignments.

Ignore the customer's personal details — name, address, phone, email. Do not include them anywhere.

Catalogue (code — name, category):
{catalogue}
"""


def system_prompt(types: Iterable[Mapping]) -> str:
    catalogue = "\n".join(f"{t['code']} — {t['name']}, {t['category']}" for t in types)
    return SYSTEM_PROMPT.format(catalogue=catalogue)


# ---------- Reading one receipt ----------


@dataclass
class PageText:
    number: int
    source: str            # "text layer", "ocr", or "none"
    text: str
    ocr_confidence: float | None = None


@dataclass
class ReceiptRead:
    path: Path
    mode: str
    pages: list[PageText]
    extraction: ReceiptExtraction
    usage: claude.Usage
    warnings: list[str] = field(default_factory=list)


def local_text(path: Path, use_ocr: bool = True) -> list[PageText]:
    """Each page's text: its own text layer if it has one, else Tesseract's reading."""
    result = []
    can_ocr = use_ocr and ocr.available()
    for page in pdf.pages(path):
        if len(page.text) >= MIN_TEXT_LAYER_CHARS:
            result.append(PageText(page.number, "text layer", page.text))
        elif can_ocr:
            read = ocr.read(pdf.render(path, page.number, pdf.OCR_LONG_EDGE, fmt="png"))
            result.append(PageText(page.number, "ocr", read.text, read.confidence))
        else:
            result.append(PageText(page.number, "none", ""))
    return result


def content_blocks(path: Path, mode: str, texts: list[PageText]) -> list[dict]:
    """The user-turn content for one receipt in the given mode."""
    import base64

    blocks: list[dict] = []
    total = len(texts)
    for page in texts:
        label = f"Page {page.number} of {total}"
        if mode in ("vision", "both"):
            image = base64.standard_b64encode(pdf.render(path, page.number, pdf.VISION_LONG_EDGE)).decode()
            blocks.append({"type": "text", "text": label})
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}})
        if mode == "text" or (mode == "both" and page.text):
            heading = label if mode == "text" else f"{label}, machine-read text (may contain OCR errors; trust the image)"
            body = page.text or "(no text could be read from this page)"
            blocks.append({"type": "text", "text": f"{heading}, from {page.source}:\n<page_text>\n{body}\n</page_text>"})
    blocks.append({"type": "text", "text": "Read this receipt."})
    return blocks


def read_receipt(path: Path | str, types: list[Mapping], mode: str = "vision", effort: str = "medium") -> ReceiptRead:
    path = Path(path)
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if not pdf.is_supported(path):
        raise ValueError(f"{path.suffix} files aren't supported; use PDF, PNG, JPG or GIF.")
    texts = local_text(path, use_ocr=mode != "vision")
    extraction, usage = claude.parse(
        ReceiptExtraction,
        system=system_prompt(types),
        content=content_blocks(path, mode, texts),
        effort=effort,
    )
    known = {t["code"] for t in types}
    warnings = checks(extraction, known)
    return ReceiptRead(path, mode, texts, extraction, usage, warnings)


# ---------- What a person should look at ----------


def checks(extraction: ReceiptExtraction, known_codes: set[str]) -> list[str]:
    """Problems worth flagging on the review screen. Unknown codes are removed in place."""
    warnings: list[str] = []
    if extraction.document_kind != "invoice":
        kind = {"estimate": "an estimate or quote", "deposit": "a deposit receipt",
                "inspection_report": "an inspection report"}.get(extraction.document_kind, "something other than an invoice")
        warnings.append(f"This looks like {kind}, not an invoice. Record it only if the work was done.")
    if not extraction.date:
        warnings.append("No date found.")
    elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", extraction.date):
        warnings.append(f"The date {extraction.date!r} isn't in YYYY-MM-DD form.")
        extraction.date = None
    for name in ("delivery_date", "next_service_date"):
        value = getattr(extraction, name)
        if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            setattr(extraction, name, None)
    if extraction.odometer is None:
        warnings.append("No odometer reading found.")
    if extraction.vin:
        candidate = vin.normalize(extraction.vin)
        if problem := vin.problem(candidate):
            warnings.append(f"VIN {candidate}: {problem}")

    for item in [*extraction.lines, *extraction.recommendations]:
        unknown = [code for code in item.service_codes if code not in known_codes]
        if unknown:
            item.service_codes = [code for code in item.service_codes if code in known_codes]
            warnings.append(f"Dropped unknown service codes {unknown} from “{item.description}”.")

    amounts = [line.amount for line in extraction.lines if line.amount is not None]
    if amounts and extraction.total is not None:
        lines_sum = round(sum(amounts), 2)
        with_tax = round(lines_sum + (extraction.tax or 0), 2)
        if abs(with_tax - extraction.total) > 0.02 and abs(lines_sum - (extraction.subtotal or -1)) > 0.02:
            warnings.append(
                f"Lines add up to ${lines_sum:,.2f}"
                + (f" (${with_tax:,.2f} with tax)" if extraction.tax else "")
                + f", but the total is ${extraction.total:,.2f}."
            )
    if extraction.uncertain:
        warnings.append(f"Claude noted: {extraction.uncertain}")
    return warnings
