"""Finding a confirmed receipt: search it, narrow by car and year, and sort.

Search reads what you confirmed: the shop, the invoice number, each line and
the service types it covers, recommendations, notes, the car and the file
name. Every word has to turn up somewhere in a receipt for it to match, so
"midas brake" finds the brake jobs at Midas; a word that's an amount ("412.37",
"$1,234") also matches the total.

Under each match go the lines that matched, so a search says why it found what
it found. The shop, the car and the total are on the row already, so a word
found there needs no line of its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from urllib.parse import urlencode

from markupsafe import Markup, escape

SORTS = {
    "newest": "Newest first",
    "oldest": "Oldest first",
    "total": "Highest total",
    "confirmed": "Recently confirmed",
}
SHOWN = 3      # matching lines under a row; any more are counted
LONG = 120     # text longer than this is cut down to the part around the match
_AMOUNT = re.compile(r"\$?[\d,]*\d(\.\d{1,2})?")


@dataclass(frozen=True)
class Finder:
    q: str = ""
    car: int | None = None
    year: int | None = None
    sort: str = "newest"

    @classmethod
    def read(cls, q: str | None = None, car: str | None = None, year: str | None = None,
             sort: str | None = None) -> Finder:
        """From the address bar, forgivingly: anything that isn't a choice is no choice."""
        return cls(" ".join((q or "").split()), _number(car), _number(year), sort if sort in SORTS else "newest")

    def within(self, options: dict) -> Finder:
        """Drop a car or year the page doesn't offer, so nothing filters out of sight."""
        cars = [car["id"] for car in options["cars"]]
        return replace(self, car=self.car if len(cars) > 1 and self.car in cars else None,
                       year=self.year if len(options["years"]) > 1 and self.year in options["years"] else None)

    @property
    def words(self) -> list[str]:
        return self.q.lower().split()

    @property
    def active(self) -> bool:
        """Is anything narrowing the list? Sorting alone isn't."""
        return bool(self.q or self.car or self.year)

    def url(self) -> str:
        params: dict[str, str | int] = {key: value for key, value in
                                        (("q", self.q), ("car", self.car), ("year", self.year)) if value}
        if self.sort != "newest":
            params["sort"] = self.sort
        return "/receipts" + (f"?{urlencode(params)}" if params else "")

    def cleared(self) -> str:
        """Every confirmed receipt again, in the same order."""
        return Finder(sort=self.sort).url()


def choices(confirmed: list[dict]) -> dict:
    """The cars and years the confirmed receipts cover: cars in use first, years newest first."""
    cars: dict[int, tuple[bool, str]] = {}
    for receipt in confirmed:
        if receipt["vehicle_id"]:
            cars[receipt["vehicle_id"]] = (bool(receipt["vehicle_archived"]), receipt["vehicle_name"] or "")
    order = sorted(cars.items(), key=lambda item: (item[1][0], item[1][1].lower()))
    return {
        "cars": [{"id": car_id, "name": name + (" (archived)" if archived else "")} for car_id, (archived, name) in order],
        "years": sorted({int(r["performed_on"][:4]) for r in confirmed if r["performed_on"]}, reverse=True),
    }


def find(confirmed: list[dict], finder: Finder, type_names: dict[str, str]) -> list[dict]:
    """The receipts to show, in order, each with ``found``: the lines that matched."""
    rows = []
    for receipt in confirmed:
        if finder.car and receipt["vehicle_id"] != finder.car:
            continue
        if finder.year and not (receipt["performed_on"] or "").startswith(f"{finder.year}-"):
            continue
        found = _search(receipt, finder.words, type_names)
        if found is None:
            continue
        rows.append({**receipt, "found": found[:SHOWN], "more": max(0, len(found) - SHOWN)})
    return _sorted(rows, finder.sort)


def highlight(text: str, words: list[str]) -> Markup:
    """The text, escaped, with every searched word in it marked."""
    words = sorted({w for w in words if w}, key=len, reverse=True)   # longest first: "pads" before "pad"
    if not words:
        return escape(text)
    out, last = Markup(), 0
    for match in re.finditer("|".join(re.escape(w) for w in words), text, re.IGNORECASE):
        out += escape(text[last:match.start()]) + Markup("<mark>") + escape(match.group()) + Markup("</mark>")
        last = match.end()
    return out + escape(text[last:])


# ---------- Helpers ----------


def _number(value: str | None) -> int | None:
    value = (value or "").strip()
    return int(value) if value.isascii() and value.isdigit() else None


def _facts(receipt: dict, type_names: dict[str, str]) -> list[tuple[str, str, str]]:
    """What a receipt says that a match can be shown by: (label, text, the service types it covers)."""
    def names(codes) -> str:
        return ", ".join(type_names[code] for code in codes if code in type_names)

    facts = [("", line.get("description") or "", names(c["code"] for c in line.get("covers") or []))
             for line in receipt["lines"]]
    facts += [("Recommended", rec.get("description") or "", names(rec.get("codes") or []))
              for rec in receipt["recommendations"]]
    facts += [(label, text, "") for label, text in
              (("Note", receipt["notes"]), ("Invoice", receipt["invoice_number"]), ("File", receipt["filename"])) if text]
    return facts


def _search(receipt: dict, words: list[str], type_names: dict[str, str]) -> list[dict] | None:
    """The matching lines for a receipt every word turns up in; None if one doesn't."""
    if not words:
        return []
    facts = _facts(receipt, type_names)
    row = f"{receipt['shop'] or ''}\n{receipt['vehicle_name'] or ''}".lower()
    text = "\n".join([row] + [part for fact in facts for part in fact]).lower()
    total = "" if receipt["total_cents"] is None else f"{receipt['total_cents'] / 100:.2f}"
    unseen = []   # words the row doesn't already show: only these need a line to say why
    for word in words:
        amount = word.lstrip("$").replace(",", "") if _AMOUNT.fullmatch(word) else ""
        on_total = bool(amount) and amount in total
        if word not in text and not on_total:
            return None
        if word not in row and not on_total:
            unseen.append(word)
    found = []
    for label, said, covers in facts:
        in_text = [w for w in unseen if w in said.lower()]
        in_covers = [w for w in unseen if w in covers.lower() and w not in in_text]   # why "Fluid flush" matched "coolant"
        if in_text or in_covers:
            found.append({
                "label": label,
                "text": highlight(_cut(said, in_text), words),
                "covers": highlight(covers, words) if in_covers else None,
            })
    return found


def _cut(text: str, words: list[str]) -> str:
    """A long text cut down to about LONG characters around its first match, at word breaks."""
    if len(text) <= LONG:
        return text
    lower = text.lower()
    at = min((lower.find(w) for w in words), default=0)
    start = max(0, min(at - LONG // 3, len(text) - LONG))
    end = start + LONG
    if start > 0:
        start = text.find(" ", start) + 1 or start
    if end < len(text):
        end = text.rfind(" ", start, end) if " " in text[start:end] else end
    return ("…" if start > 0 else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def _sorted(rows: list[dict], sort: str) -> list[dict]:
    if sort == "oldest":
        return sorted(rows, key=lambda r: (r["performed_on"] or "", r["id"]))
    if sort == "total":    # receipts without a total go last
        return sorted(rows, key=lambda r: (r["total_cents"] is not None, r["total_cents"] or 0,
                                           r["performed_on"] or "", r["id"]), reverse=True)
    if sort == "confirmed":
        return sorted(rows, key=lambda r: (r["confirmed_at"] or "", r["id"]), reverse=True)
    return sorted(rows, key=lambda r: (r["performed_on"] or "", r["id"]), reverse=True)
