"""Finding a confirmed receipt, on hand-made rows shaped like the inbox's.

The four receipts:

* 1: Midas, 2024-03-11, $412.37, the Outback: front brake pads and rotors, and
  a recommendation for the rear pads. Confirmed second.
* 2: Corner Garage, 2019-08-15, $77.79, the Outback, invoice A100: an oil
  change and a "fluid flush" that replaced the coolant. Confirmed last.
* 3: Midas, 2022-05-02, $1,234.00, the Forester (archived): a timing belt.
  Confirmed first.
* 4: Discount Tire, 2022-05-02 (the same day as 3, added after it), no
  total, the Outback. Confirmed third.
"""

from __future__ import annotations

from amg.web import receipt_finder as rf
from amg.web.receipt_finder import Finder

TYPES = {"brake_pads": "Brake pads", "engine_coolant": "Engine coolant", "engine_oil": "Engine oil"}
OUTBACK, FORESTER = (1, "Outback", False), (2, "Forester", True)


def _receipt(receipt_id, day, shop, total, lines=(), recs=(), notes="", car=OUTBACK, invoice="", confirmed=""):
    return {
        "id": receipt_id, "performed_on": day, "shop": shop, "total_cents": total,
        "vehicle_id": car[0], "vehicle_name": car[1], "vehicle_archived": int(car[2]),
        "lines": [{"description": text, "covers": [{"code": c, "action": "replace"} for c in codes]}
                  for text, codes in lines],
        "recommendations": [{"description": text, "codes": list(codes)} for text, codes in recs],
        "notes": notes, "invoice_number": invoice, "filename": f"scan-{receipt_id}.pdf",
        "confirmed_at": confirmed,
    }


RECEIPTS = [
    _receipt(1, "2024-03-11", "Midas", 41_237,
             lines=[("Front brake pads and rotors", ["brake_pads"]), ("Shop supplies", [])],
             recs=[("Rear pads at 3 mm", ["brake_pads"])], confirmed="2026-01-05T00:00:00Z"),
    _receipt(2, "2019-08-15", "Corner Garage", 7_779,
             lines=[("Oil change", ["engine_oil"]), ("Fluid flush", ["engine_coolant"])], invoice="A100",
             confirmed="2026-01-09T00:00:00Z"),
    _receipt(3, "2022-05-02", "Midas", 123_400, lines=[("Timing belt kit", [])], car=FORESTER,
             confirmed="2026-01-01T00:00:00Z"),
    _receipt(4, "2022-05-02", "Discount Tire", None, lines=[("Mount and balance", [])],
             confirmed="2026-01-07T00:00:00Z"),
]


def _ids(finder: Finder) -> list[int]:
    return [r["id"] for r in rf.find(RECEIPTS, finder, TYPES)]


def test_newest_receipt_date_comes_first_and_each_sort_orders_its_own_way():
    assert _ids(Finder()) == [1, 4, 3, 2]                          # same day: the one added last first
    assert _ids(Finder(sort="oldest")) == [2, 3, 4, 1]
    assert _ids(Finder(sort="total")) == [3, 1, 2, 4]              # no total goes last
    assert _ids(Finder(sort="confirmed")) == [2, 4, 1, 3]


def test_every_word_has_to_turn_up_somewhere_in_the_receipt():
    assert _ids(Finder(q="midas brake")) == [1]                    # the shop and a line
    assert _ids(Finder(q="MIDAS timing")) == [3]
    assert _ids(Finder(q="midas oil")) == []
    assert _ids(Finder(q="forester")) == [3]                       # the car
    assert _ids(Finder(q="a100")) == [2]                           # the invoice number
    assert _ids(Finder(q="scan-4")) == [4]                         # the file


def test_a_service_type_finds_the_line_that_covered_it():
    (row,) = rf.find(RECEIPTS, Finder(q="coolant"), TYPES)
    (hit,) = row["found"]
    assert (hit["label"], hit["text"], hit["covers"]) == ("", "Fluid flush", "Engine <mark>coolant</mark>")


def test_an_amount_matches_the_total():
    assert _ids(Finder(q="412.37")) == [1]
    assert _ids(Finder(q="$412.37")) == [1]
    assert _ids(Finder(q="1,234")) == [3]
    assert _ids(Finder(q="$77")) == [2]


def test_the_lines_that_matched_go_under_the_row_with_the_words_marked():
    (row,) = rf.find(RECEIPTS, Finder(q="pads"), TYPES)
    assert [(hit["label"], hit["text"], hit["covers"]) for hit in row["found"]] == [
        ("", "Front brake <mark>pads</mark> and rotors", None),   # the line's own words say why: no type
        ("Recommended", "Rear <mark>pads</mark> at 3 mm", None),
    ]
    (shop_only,) = rf.find(RECEIPTS, Finder(q="garage"), TYPES)
    assert shop_only["found"] == []                                # the shop is on the row already
    assert all(row["found"] == [] for row in rf.find(RECEIPTS, Finder(), TYPES))


def test_a_word_the_row_already_shows_needs_no_line_to_say_why():
    rows = [{**RECEIPTS[0], "filename": "midas-2024-03-11.pdf"}]
    (row,) = rf.find(rows, Finder(q="midas"), TYPES)
    assert row["found"] == []                                      # not the file, though it says Midas too
    (row,) = rf.find(rows, Finder(q="midas front"), TYPES)
    assert [hit["text"] for hit in row["found"]] == ["<mark>Front</mark> brake pads and rotors"]
    (row,) = rf.find(rows, Finder(q="412.37"), TYPES)
    assert row["found"] == []                                      # the total is on the row


def test_what_a_receipt_says_stays_text():
    rows = [_receipt(9, "2025-01-01", "Shop", 100, lines=[("Wiper <blades> & fluid", [])])]
    (row,) = rf.find(rows, Finder(q="blades"), TYPES)
    assert row["found"][0]["text"] == "Wiper &lt;<mark>blades</mark>&gt; &amp; fluid"
    assert rf.highlight("<b>", []) == "&lt;b&gt;"


def test_a_long_note_is_cut_down_to_the_part_around_the_match():
    note = " ".join(["word"] * 40) + " the coolant was low " + " ".join(["word"] * 40)
    rows = [_receipt(9, "2025-01-01", "Shop", 100, notes=note)]
    (row,) = rf.find(rows, Finder(q="coolant"), TYPES)
    (hit,) = row["found"]
    assert hit["label"] == "Note" and "the <mark>coolant</mark> was low" in hit["text"]
    assert hit["text"].startswith("…word") and hit["text"].endswith("word…") and len(hit["text"]) < 160


def test_more_than_three_matches_are_counted():
    rows = [_receipt(9, "2025-01-01", "Shop", 100, lines=[(f"Filter {n}", []) for n in range(5)])]
    (row,) = rf.find(rows, Finder(q="filter"), TYPES)
    assert len(row["found"]) == 3 and row["more"] == 2


def test_car_and_year_narrow_together():
    assert _ids(Finder(car=1)) == [1, 4, 2]
    assert _ids(Finder(year=2022)) == [4, 3]
    assert _ids(Finder(car=1, year=2022)) == [4]
    assert _ids(Finder(q="midas", year=2022)) == [3]


def test_the_address_bar_is_read_forgivingly_and_written_without_defaults():
    assert Finder.read("  brake   pads ", "x", "²", "bogus") == Finder("brake pads", None, None, "newest")
    assert Finder.read(None, " 3 ", "2024", "total") == Finder("", 3, 2024, "total")
    assert Finder().url() == "/receipts"
    assert Finder("brake pads", 3, 2024, "total").url() == "/receipts?q=brake+pads&car=3&year=2024&sort=total"
    assert Finder("brake", 3, sort="oldest").cleared() == "/receipts?sort=oldest"
    assert not Finder(sort="total").active and Finder(year=2024).active


def test_the_choices_are_the_cars_and_years_there_are():
    options = rf.choices(RECEIPTS)
    assert options == {"cars": [{"id": 1, "name": "Outback"}, {"id": 2, "name": "Forester (archived)"}],
                       "years": [2024, 2022, 2019]}
    assert Finder(car=7, year=2024).within(options) == Finder(year=2024)      # not a car with receipts
    one = rf.choices(RECEIPTS[:1])
    assert Finder(car=1, year=2024).within(one) == Finder()                   # nothing to choose between
