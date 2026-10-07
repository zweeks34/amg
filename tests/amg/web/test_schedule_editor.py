from __future__ import annotations

import json

from amg.ingest.schedule_drafts import blank_item
from amg.web import schedule_editor as se

TYPES = {"engine_oil": {"name": "Engine oil"}, "oil_filter": {"name": "Oil filter"}}


def _row(**changes):
    return {**se.editor_row(blank_item(name="Engine oil", codes=["engine_oil"], interval_miles=6000,
                                       interval_months=6)), **changes}


def test_an_item_round_trips_through_the_editor():
    item = blank_item(id=4, name="Coolant", codes=["engine_oil"], interval_miles=75_000, interval_months=72,
                      first_miles=137_500, first_months=132, source="manual", document_id=9, page=1,
                      marked_miles=[6000, 7500])
    row = se.editor_row(item)
    assert (row["interval_miles"], row["first_miles"], row["marked"], row["show_first"]) == ("75,000", "137,500",
                                                                                            "6k, 7.5k", True)
    (parsed,), errors = se.parse_items(se.clean_items(json.dumps([row])), TYPES, documents={9})
    assert errors == [None]
    assert {k: parsed[k] for k in ("id", "interval_miles", "interval_months", "first_miles", "first_months",
                                   "document_id", "page")} == {
        "id": 4, "interval_miles": 75_000, "interval_months": 72, "first_miles": 137_500, "first_months": 132,
        "document_id": 9, "page": 1}


def test_errors_line_up_with_the_posted_rows():
    rows = [_row(), se.blank_row(), _row(interval_months="soon"), _row(covers=[]), _row(interval_miles="",
                                                                                       interval_months="")]
    items, errors = se.parse_items(rows, TYPES, documents=set())
    assert len(items) == 4 and len(errors) == 5
    assert errors[:3] == [None, None, "Enter whole months, like 6."]
    assert errors[3].startswith("Add the service") and errors[4].startswith("Give it an interval")


def test_a_left_out_row_needs_no_service_or_interval():
    items, errors = se.parse_items([_row(covers=[], interval_miles="", interval_months="", included=False)], TYPES,
                                   documents=set())
    assert errors == [None] and not items[0]["included"]


def test_a_document_the_draft_doesnt_cite_is_dropped():
    (item,), _ = se.parse_items([_row(document_id=99, page=3)], TYPES, documents={9})
    assert (item["document_id"], item["page"]) == (None, None)


def test_a_row_is_named_after_its_services_and_junk_is_cleaned():
    rows = se.clean_items(json.dumps([{"name": "", "covers": ["engine_oil", "oil_filter", 5], "action": "explode",
                                       "applies": "sometimes", "source": "hacker", "interval_months": "6"}, "junk"]))
    (item,), _ = se.parse_items(rows, TYPES, documents=set())
    assert (item["name"], item["action"], item["applies"], item["source"]) == (
        "Engine oil, Oil filter", "replace", "always", "you")
    assert se.clean_items("not json") == []


# ---------- Count from ----------


def test_a_count_from_date_round_trips_through_the_editor():
    row = se.editor_row(blank_item(name="Washer fluid", codes=["engine_oil"], interval_months=3,
                                   counts_from="2026-10-06"))
    assert (row["counts_from"], row["show_start"]) == ("2026-10-06", True)
    (parsed,), errors = se.parse_items(se.clean_items(json.dumps([row])), TYPES, documents=set())
    assert errors == [None] and parsed["counts_from"] == "2026-10-06"
    assert se.blank_row()["counts_from"] == "" and not se.blank_row()["show_start"]


def test_a_count_from_date_cant_be_in_the_future_or_on_a_one_off():
    rows = [_row(counts_from="2999-01-01"), _row(counts_from="soon"),
            _row(interval_miles="", interval_months="", first_months="120", counts_from="2026-10-06")]
    _, errors = se.parse_items(rows, TYPES, documents=set())
    assert errors == ["That date is in the future.", "Enter a date like 2016-08-15.",
                      "Only a repeating item can count from a date."]
