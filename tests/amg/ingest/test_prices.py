from __future__ import annotations

from datetime import date

import pytest
import receipt_fixtures as fx  # tests/ is on pytest's path

from amg.engine import forecast
from amg.ingest import background, claude
from amg.ingest import prices as pricer
from amg.ingest.prices import JobPrice, PriceEstimates
from amg.repo import prices, schedules, services, vehicles
from amg.repo.schedules import ItemInput

CAR = {"year": 2016, "make": "Subaru", "model": "Outback", "trim": "2.5i Limited", "engine": "2.5L 4-cyl",
       "powertrain": "gas"}
JOBS = [
    {"key": "j1", "name": "Spark plugs", "action": "replace", "types": ["Spark plugs"]},
    {"key": "j2", "name": "Drive belts", "action": "replace", "types": ["Drive belts"]},
]


def test_the_prompt_names_the_car_the_jobs_and_what_you_paid():
    text = pricer.prompt(CAR, JOBS, [{"name": "Oil and filter", "cents": 7_721, "count": 3},
                                     {"name": "Tire rotation", "cents": 2_574, "count": 1}])
    assert "2016 Subaru Outback 2.5i Limited, 2.5L 4-cyl, gasoline" in text
    assert "- j1: Spark plugs (replace: Spark plugs)" in text
    assert "- Oil and filter: $77 (median of 3 visits)" in text
    assert "- Tire rotation: $26\n" in text + "\n"
    assert "paid" not in pricer.prompt(CAR, JOBS, [])


def test_each_range_is_checked_and_a_skipped_job_says_so():
    answer = PriceEstimates(prices=[
        JobPrice(key=" j1 ", low_usd=180, high_usd=320.5, note="4 iridium plugs, 1 h"),
        JobPrice(key="j3", low_usd=1, high_usd=2, note="not asked for"),
    ])
    read = pricer.check(answer, ["j1", "j2"])
    assert read.prices == {"j1": pricer.Priced(18_000, 32_050, "4 iridium plugs, 1 h")}
    assert read.missing == {"j2": "Claude gave no price for this. Ask again, or set your own."}


@pytest.mark.parametrize("low, high", [(0, 100), (300, 200), (100, 25_000)])
def test_a_range_that_makes_no_sense_is_refused(low, high):
    read = pricer.check(PriceEstimates(prices=[JobPrice(key="j1", low_usd=low, high_usd=high, note="")]), ["j1"])
    assert read.prices == {} and read.missing["j1"].startswith("Claude's range didn't make sense")


def test_anchors_are_what_you_paid_most_often_first():
    items = [
        {"name": "Oil and filter", "codes": ["engine_oil", "oil_filter"], "action": "replace"},
        {"name": "Oil and filter (severe)", "codes": ["oil_filter", "engine_oil"], "action": "replace"},  # same job
        {"name": "Tire rotation", "codes": ["tire_rotation"], "action": "perform"},
        {"name": "Spark plugs", "codes": ["spark_plugs"], "action": "replace"},   # never paid for
    ]
    oil = ((("engine_oil", "replace"), ("oil_filter", "replace")))
    visits = [forecast.Visit(n, 1, date(2026, 1, 1), (forecast.Line(cents, "labor", dict(covers)),))
              for n, (cents, covers) in enumerate([(7_000, oil), (8_000, oil), (2_500, (("tire_rotation", "perform"),))], 1)]
    assert pricer.anchors(items, visits, date(2026, 1, 1)) == [
        {"name": "Oil and filter", "cents": 7_500, "count": 2}, {"name": "Tire rotation", "cents": 2_500, "count": 1}]


# ---------- Asking, in the background ----------


@pytest.fixture
def inline_jobs(monkeypatch):
    monkeypatch.setattr(background, "spawn", background.run)


@pytest.fixture
def outback(conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Outback", year=2016, make="Subaru", model="Outback"))
    items = [ItemInput("Engine oil and filter", "replace", ["engine_oil", "oil_filter"], interval_miles=6_000),
             ItemInput("Spark plugs", "replace", ["spark_plugs"], interval_miles=60_000),
             ItemInput("Drive belts", "replace", ["drive_belts"], interval_miles=60_000)]
    draft_id = schedules.create_draft(conn, car, "template", draft={"origin": "template", "items": []})
    schedules.confirm(conn, draft_id, car, items, {"origin": "template", "items": []})
    services.create_event(conn, car, services.EventInput(
        performed_on=date.today().isoformat(), source="shop", lines=[services.LineInput(
            "Oil change", "labor", amount_cents=6_600,
            covers=[services.Coverage("engine_oil", "replace"), services.Coverage("oil_filter", "replace")])]))
    return car


def _wanted():
    return [(["spark_plugs"], "replace", "Spark plugs"), (["drive_belts"], "replace", "Drive belts")]


def _rows(conn, car):
    return {r["name"]: r for r in prices.for_car(conn, car)}


def test_claude_prices_a_cars_jobs_in_one_call(conn, outback, inline_jobs, monkeypatch):
    asked = []

    def fake_parse(schema, system, content, effort, max_tokens):
        asked.append(content[0]["text"])
        keys = [line.split(":")[0][2:] for line in content[0]["text"].splitlines() if line.startswith("- j")]
        return PriceEstimates(prices=[JobPrice(key=keys[0], low_usd=180, high_usd=320, note="4 plugs")]), fx.USAGE

    monkeypatch.setattr(claude, "parse", fake_parse)
    background.price(conn, outback, _wanted())

    assert len(asked) == 1
    assert "- Engine oil and filter: $66" in asked[0]   # your own price, to calibrate
    rows = _rows(conn, outback)
    plugs, belts = rows["Spark plugs"], rows["Drive belts"]
    assert (plugs["status"], plugs["low_cents"], plugs["high_cents"], plugs["note"]) == ("done", 18_000, 32_000, "4 plugs")
    assert plugs["cost_usd"] == pytest.approx(fx.USAGE.cost_usd)   # the one it priced carries the call's cost
    assert (belts["status"], belts["error"]) == ("failed", "Claude gave no price for this. Ask again, or set your own.")


def test_a_failed_call_marks_every_job_failed_with_the_reason(conn, outback, inline_jobs, monkeypatch):
    def fail(*args, **kwargs):
        raise claude.ClaudeError("Claude took too long to answer. Try reading it again.")

    monkeypatch.setattr(claude, "parse", fail)
    background.price(conn, outback, _wanted())
    assert {(r["status"], r["error"]) for r in _rows(conn, outback).values()} == {
        ("failed", "Claude took too long to answer. Try reading it again.")}


def test_no_api_key_says_where_to_put_one(conn, outback, inline_jobs, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    background.price(conn, outback, _wanted())
    errors = {r["error"] for r in _rows(conn, outback).values()}
    assert len(errors) == 1 and errors.pop().startswith("No Anthropic API key is set, so AMG can't ask Claude.")


def test_an_unexpected_error_never_leaves_a_price_asking(conn, outback, inline_jobs, monkeypatch):
    monkeypatch.setattr(claude, "parse", lambda *a, **k: 1 / 0)
    background.price(conn, outback, _wanted())
    assert {r["status"] for r in _rows(conn, outback).values()} == {"failed"}
    assert "ZeroDivisionError" in _rows(conn, outback)["Spark plugs"]["error"]
