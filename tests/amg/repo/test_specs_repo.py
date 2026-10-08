"""Specs cards in the database: saving replaces, and the receipt lines that suggest values."""

from __future__ import annotations

import pytest
import report_fixtures as rf  # tests/ is on pytest's path

from amg.repo import documents, specs
from amg.repo.services import LineInput
from amg.repo.specs import SpecInput


@pytest.fixture
def car(conn):
    return rf.car(conn, "Outback", year=2016, make="Subaru", model="Outback")


def test_save_replaces_the_card_in_order(conn, car):
    manual, _ = documents.store(conn, rf.pdf_bytes("MANUAL"), "manual.pdf")
    specs.save(conn, car, [SpecInput("oil_grade", "0W-20"), SpecInput("custom", "168", label="Trunk light"),
                           SpecInput("tire_size", "225/65R17", source="read", document_id=manual["id"], page=412),
                           SpecInput("custom", "CR2450", label="Spare fob")])
    rows = specs.values(conn, car)
    assert [(r["key"], r["label"], r["value"]) for r in rows] == [
        ("oil_grade", "", "0W-20"), ("custom", "Trunk light", "168"), ("tire_size", "", "225/65R17"),
        ("custom", "Spare fob", "CR2450")]
    assert (rows[2]["source"], rows[2]["filename"], rows[2]["page"]) == ("read", "manual.pdf", 412)
    specs.save(conn, car, [SpecInput("oil_grade", "5W-30")])
    assert [(r["key"], r["value"], r["source"]) for r in specs.values(conn, car)] == [("oil_grade", "5W-30", "you")]


def test_what_a_card_cant_hold(conn, car):
    for bad in ([SpecInput("nonsense", "1")], [SpecInput("oil_grade", "0W-20"), SpecInput("oil_grade", "5W-30")],
                [SpecInput("oil_grade", " ")], [SpecInput("custom", "168")]):
        with pytest.raises(ValueError):
            specs.save(conn, car, bad)
    assert specs.values(conn, car) == []


def test_typed_values_keep_no_page(conn, car):
    specs.save(conn, car, [SpecInput("oil_grade", "0W-20", document_id=3, page=9)])
    assert (specs.values(conn, car)[0]["document_id"], specs.values(conn, car)[0]["page"]) == (None, None)


def test_fitted_lines_are_confirmed_replacements_newest_first(conn, car):
    def part(description, *codes, action="replace", part_number=""):
        made = rf.line(description, 1_000, *codes, action=action, kind="part")
        return LineInput(made.description, made.kind, part_number=part_number, amount_cents=made.amount_cents,
                         covers=made.covers)

    old = rf.visit(conn, car, "2025-03-02", shop="Midas", lines=[part("Oil filter", "oil_filter", part_number="OLD-1")])
    new = rf.visit(conn, car, "2026-08-01", shop="Valley Honda",
                   lines=[part("Oil and filter", "engine_oil", "oil_filter", part_number="15208AA15A"),
                          part("Cabin filter looked at", "cabin_air_filter", action="inspect")])
    rf.visit(conn, car, "2026-09-01", shop="Nobody", confirmed=False, lines=[part("Oil filter", "oil_filter")])
    lines = specs.fitted_lines(conn, car, ["engine_oil", "oil_filter", "cabin_air_filter"])
    assert [(l["event_id"], l["code"], l["part_number"]) for l in lines] == [
        (new, "engine_oil", "15208AA15A"), (new, "oil_filter", "15208AA15A"), (old, "oil_filter", "OLD-1")]
    assert specs.fitted_lines(conn, car, []) == []


def test_everything_names_the_car(conn, car):
    specs.save(conn, car, [SpecInput("oil_grade", "0W-20")])
    assert [(r["car"], r["key"]) for r in specs.everything(conn)] == [("Outback", "oil_grade")]
