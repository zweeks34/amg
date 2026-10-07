from __future__ import annotations

import pytest
from schedule_fixtures import COLUMNS, reading, row  # tests/ is on pytest's path

from amg.ingest import schedule_drafts as sd
from amg.ingest import schedule_templates as templates

TYPES = {code: {"code": code, "name": code.replace("_", " ").capitalize()} for code in (
    "engine_oil", "oil_filter", "engine_coolant", "spark_plugs", "transmission_fluid", "timing_belt", "brake_pads",
    "brake_rotors", "axle_boots",
)}


def _only(draft):
    (item,) = draft.items
    return item


# ---------- Marks to intervals ----------


def test_evenly_marked_every_column():
    found = sd.intervals_from_marks([m * 1000 for m in range(6, 133, 6)], COLUMNS)
    assert (found.every_miles, found.every_months, found.first_miles, found.first_months) == (6000, 6, None, None)
    assert not found.uneven


def test_marks_that_start_late_are_a_first_then_every():
    found = sd.intervals_from_marks([30_000, 90_000], COLUMNS)   # the BRZ's ATF inspection
    assert (found.first_miles, found.every_miles, found.first_months, found.every_months) == (30_000, 60_000, 30, 60)


def test_a_single_mark_repeats_past_the_table():
    found = sd.intervals_from_marks([96_000], COLUMNS)
    assert (found.every_miles, found.every_months, found.first_miles) == (96_000, 96, None)


def test_uneven_marks_are_flagged():
    found = sd.intervals_from_marks([30_000, 60_000, 120_000], COLUMNS)
    assert found.uneven and found.every_miles == 30_000


def test_uneven_marks_warn_on_review():
    _, warnings = sd.from_extraction(reading(row("Drive belt", ("drive_belts",), "inspect", marks=(30, 60, 120))),
                                     {**TYPES, "drive_belts": {"name": "Drive belts"}}, "manual")
    assert any("uneven steps" in w for w in warnings)


# ---------- From a reading ----------


def test_the_coolant_line_is_a_first_then_every():
    draft, _ = sd.from_extraction(reading(row("Engine coolant", ("engine_coolant",), first_miles=137_500,
                                              first_months=132, every_miles=75_000, every_months=72)), TYPES, "manual")
    item = _only(draft)
    assert (item["first_miles"], item["first_months"], item["interval_miles"], item["interval_months"]) == (
        137_500, 132, 75_000, 72)
    assert sd.interval_words(item) == "first at 137,500 mi or 11 years, then every 75,000 mi or 6 years"


def test_a_first_that_equals_the_interval_is_dropped():
    item = _only(sd.from_extraction(reading(row(every_miles=6000, every_months=6, first_miles=6000,
                                                first_months=6)), TYPES, "manual")[0])
    assert (item["first_miles"], item["first_months"]) == (None, None)


def test_rows_for_other_models_are_left_out_with_the_reason():
    draft, _ = sd.from_extraction(reading(
        row("Spark plug", ("spark_plugs",), marks=(60, 120)),
        row("Timing belt (WRX/WRX STI)", ("timing_belt",), marks=(96,), applies=False, why_not="WRX/WRX STI only"),
    ), TYPES, "manual")
    timing = draft.items[1]
    assert not timing["included"] and timing["why_not"] == "WRX/WRX STI only"
    assert [item.name for item in sd.to_items(draft)] == ["Spark plug"]


def test_unknown_codes_are_dropped_with_a_warning():
    draft, warnings = sd.from_extraction(reading(row(codes=("engine_oil", "blinker_fluid"), marks=(6, 12))),
                                         TYPES, "manual")
    assert _only(draft)["codes"] == ["engine_oil"]
    assert any("blinker_fluid" in w for w in warnings)


def test_a_row_with_no_interval_is_flagged():
    _, warnings = sd.from_extraction(reading(row()), TYPES, "manual")
    assert any("No interval" in w for w in warnings)


def test_manual_items_keep_their_page_and_document_but_drafts_dont():
    manual = _only(sd.from_extraction(reading(row(marks=(6, 12), page=2)), TYPES, "manual", document_id=7,
                                      pages=[1, 2])[0])
    assert (manual["source"], manual["document_id"], manual["page"]) == ("manual", 7, 2)
    drafted = _only(sd.from_extraction(reading(row(marks=(6, 12), page=2)), TYPES, "claude")[0])
    assert (drafted["source"], drafted["document_id"], drafted["page"]) == ("claude", None, None)


def test_a_page_claude_wasnt_shown_is_dropped():
    item = _only(sd.from_extraction(reading(row(marks=(6, 12), page=9)), TYPES, "manual", 7, pages=[1, 2])[0])
    assert item["page"] is None


# ---------- Severe service ----------


def test_a_severe_interval_stands_in_for_the_normal_one():
    draft, _ = sd.from_extraction(reading(
        row("Engine oil", ("engine_oil",), marks=range(6, 133, 6)),
        row("Engine oil filter", ("oil_filter",), marks=range(6, 133, 6)),
        row("Engine oil and filter", ("engine_oil", "oil_filter"), severe=True, every_miles=3000, every_months=3),
    ), TYPES, "manual")
    assert [item["applies"] for item in draft.items] == ["normal", "normal", "severe"]
    assert [sd.in_effect(item, severe_service=True) for item in draft.items] == [False, False, True]
    assert [sd.in_effect(item, severe_service=False) for item in draft.items] == [True, True, False]


def test_a_severe_replacement_doesnt_replace_a_normal_inspection():
    draft, _ = sd.from_extraction(reading(
        row("Transmission gear oil", ("transmission_fluid",), "inspect", marks=(30, 60, 90, 120)),
        row("Transmission gear oil", ("transmission_fluid",), "replace", severe=True, every_miles=15_000,
            every_months=15),
    ), TYPES, "manual")
    assert [item["applies"] for item in draft.items] == ["always", "severe"]


def test_a_severe_row_left_out_pairs_with_nothing():
    draft, _ = sd.from_extraction(reading(
        row(marks=range(6, 133, 6)),
        row(severe=True, every_miles=3000, applies=False, why_not="Turbo only"),
    ), TYPES, "manual")
    assert draft.items[0]["applies"] == "always"


# ---------- Round trips and words ----------


def test_whichever_comes_first_survives_items_and_back():
    draft, _ = sd.from_extraction(reading(row(marks=range(6, 133, 6))), TYPES, "manual", document_id=3)
    stored = [{**vars(item), "id": 11} for item in sd.to_items(draft)]
    again = sd.to_items(sd.from_items(stored, origin="manual", keep_ids=True))
    assert (again[0].id, again[0].interval_miles, again[0].interval_months) == (11, 6000, 6)
    copied = sd.from_items(stored)
    assert copied.items[0]["id"] is None and copied.items[0]["document_id"] == 3


@pytest.mark.parametrize(("values", "words"), [
    ((6000, 6, None, None), "every 6,000 mi or 6 months"),
    ((None, 24, None, None), "every 2 years"),
    ((30_000, None, None, None), "every 30,000 mi"),
    ((None, None, 1000, None), "once, at 1,000 mi"),
    ((None, None, None, None), "no interval"),
])
def test_interval_words(values, words):
    keys = ("interval_miles", "interval_months", "first_miles", "first_months")
    assert sd.interval_words(dict(zip(keys, values))) == words


def test_a_draft_survives_json():
    draft, _ = sd.from_extraction(reading(row(marks=(6, 12))), TYPES, "manual")
    assert sd.ScheduleDraft.from_dict(draft.to_dict()) == draft


# ---------- Templates ----------


@pytest.mark.parametrize("powertrain", ["gas", "hybrid", "ev"])
def test_templates_use_known_types_for_their_powertrain(conn, powertrain):
    from amg.repo import services

    types = {row["code"]: row for row in services.list_types(conn, powertrain)}
    draft = templates.draft(powertrain)
    assert draft.items and all(item["source"] == "template" for item in draft.items)
    for item in draft.items:
        assert item["codes"] and all(code in types for code in item["codes"]), item["name"]
        assert sd.interval_words(item) != "no interval", item["name"]


@pytest.mark.parametrize("powertrain", ["gas", "hybrid", "ev"])
def test_templates_offer_washer_fluid_left_out(powertrain):
    fluid = next(item for item in templates.draft(powertrain).items if item["codes"] == ["washer_fluid"])
    assert not fluid["included"] and fluid["interval_months"] == 3
    assert fluid["why_not"] == "Only if you want reminders: most cars warn when it runs low"


def test_a_template_draft_is_a_fresh_copy():
    first = templates.draft("gas")
    first.items[0]["codes"].append("tires")
    assert "tires" not in templates.draft("gas").items[0]["codes"]


def test_the_hybrid_template_adds_to_the_gasoline_one():
    gas = {item["name"] for item in templates.draft("gas").items}
    hybrid = {item["name"] for item in templates.draft("hybrid").items}
    assert gas < hybrid and "Inverter coolant" in hybrid
    assert "Engine oil and filter" not in {item["name"] for item in templates.draft("ev").items}
