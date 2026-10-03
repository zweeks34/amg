from __future__ import annotations

import sqlite3

import pymupdf
import pytest
import receipt_fixtures as fx  # tests/ is on pytest's path

from amg.ingest import drafts
from amg.repo import documents, jobs, prices, receipts, schedules, services, vehicles
from amg.repo.schedules import ItemInput

OIL = ("oil_filter", "engine_oil")


@pytest.fixture
def car(conn):
    return vehicles.create(conn, vehicles.VehicleFields(name="Outback", year=2016, make="Subaru", model="Outback"))


def _mine(conn, car):
    return [(r["codes"], r["action"], r["source"], r["low_cents"], r["high_cents"], r["status"])
            for r in prices.for_car(conn, car)]


def test_your_price_is_kept_per_job_with_the_codes_sorted(conn, car):
    prices.set_yours(conn, car, OIL, "replace", "Oil and filter", 8_500)
    prices.set_yours(conn, car, ["engine_oil", "oil_filter"], "replace", "Oil and filter", 9_000)   # changed, not added
    assert _mine(conn, car) == [("engine_oil,oil_filter", "replace", "you", 9_000, 9_000, "done")]

    prices.remove_yours(conn, car, OIL, "replace")
    assert _mine(conn, car) == []


def test_a_job_needs_codes_a_known_action_and_a_price_of_zero_or_more(conn, car):
    with pytest.raises(ValueError):
        prices.set_yours(conn, car, [], "replace", "Nothing", 100)
    with pytest.raises(ValueError):
        prices.set_yours(conn, car, OIL, "polish", "Oil", 100)
    with pytest.raises(ValueError):
        prices.set_yours(conn, car, OIL, "replace", "Oil", -1)


def test_yours_and_claudes_sit_side_by_side_and_removing_yours_leaves_claudes(conn, car):
    job_id = jobs.create(conn, "price_jobs")
    prices.queue_claude(conn, car, [(OIL, "replace", "Oil and filter"), (("spark_plugs",), "replace", "Spark plugs")],
                        job_id)
    claimed = prices.claim(conn, job_id)
    assert sorted(r["name"] for r in claimed) == ["Oil and filter", "Spark plugs"]
    assert prices.claim(conn, job_id) == []   # nothing left queued
    oil = next(r for r in claimed if r["codes"] == "engine_oil,oil_filter")
    plugs = next(r for r in claimed if r["codes"] == "spark_plugs")
    prices.mark_priced(conn, oil["id"], 7_000, 11_000, "Synthetic, filter included", fx.USAGE, share=2)
    prices.mark_failed(conn, plugs["id"], "Claude gave no price for this.")
    prices.set_yours(conn, car, OIL, "replace", "Oil and filter", 8_500)

    assert sorted(_mine(conn, car)) == [
        ("engine_oil,oil_filter", "replace", "claude", 7_000, 11_000, "done"),
        ("engine_oil,oil_filter", "replace", "you", 8_500, 8_500, "done"),
        ("spark_plugs", "replace", "claude", None, None, "failed"),
    ]
    row = next(r for r in prices.for_car(conn, car) if r["source"] == "claude" and r["status"] == "done")
    assert row["model"] == "claude-opus-5-5" and row["cost_usd"] == pytest.approx(fx.USAGE.cost_usd / 2)

    prices.remove_yours(conn, car, OIL, "replace")
    assert [r["source"] for r in prices.for_car(conn, car) if r["codes"] == "engine_oil,oil_filter"] == ["claude"]


def test_asking_again_requeues_a_failed_row_rather_than_adding_one(conn, car):
    first = jobs.create(conn, "price_jobs")
    prices.queue_claude(conn, car, [(("spark_plugs",), "replace", "Spark plugs")], first)
    (row,) = prices.claim(conn, first)
    prices.mark_failed(conn, row["id"], "Claude took too long to answer.")

    second = jobs.create(conn, "price_jobs")
    prices.queue_claude(conn, car, [(("spark_plugs",), "replace", "Spark plugs")], second)
    (again,) = prices.for_car(conn, car)
    assert (again["id"], again["status"], again["job_id"], again["error"]) == (row["id"], "queued", second, "")


def test_a_stalled_job_puts_its_prices_back_in_the_queue(conn, car):
    job_id = jobs.create(conn, "price_jobs")
    prices.queue_claude(conn, car, [(("spark_plugs",), "replace", "Spark plugs")], job_id)
    prices.claim(conn, job_id)   # the thread dies here
    jobs.resume(conn, job_id)
    assert [r["status"] for r in prices.for_car(conn, car)] == ["queued"]


def test_prices_outlive_the_schedule_items_that_asked_for_them(conn, car):
    def use(items):
        draft_id = schedules.create_draft(conn, car, "template", draft={"origin": "template", "items": []})
        schedules.confirm(conn, draft_id, car, items, {"origin": "template", "items": []})

    use([ItemInput("Oil and filter", "replace", list(OIL), interval_miles=6_000)])
    prices.set_yours(conn, car, OIL, "replace", "Oil and filter", 8_500)
    use([ItemInput("Engine oil and filter", "replace", list(OIL), interval_miles=3_000)])   # a new schedule
    assert _mine(conn, car) == [("engine_oil,oil_filter", "replace", "you", 8_500, 8_500, "done")]


def test_prices_go_with_the_car(conn, car):
    prices.set_yours(conn, car, OIL, "replace", "Oil and filter", 8_500)
    conn.execute("DELETE FROM vehicles WHERE id = ?", (car,))
    assert conn.execute("SELECT count(*) FROM price_book").fetchone()[0] == 0


def test_the_database_refuses_a_range_upside_down(conn, car):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO price_book (vehicle_id, codes, action, name, source, low_cents, high_cents,"
                     " created_at, updated_at) VALUES (?, 'spark_plugs', 'replace', 'Plugs', 'claude', 200, 100, 'x', 'x')",
                     (car,))


# ---------- What your receipts show ----------


def _visit(conn, car, on, lines, tax=None, confirmed=True):
    return services.create_event(conn, car, services.EventInput(
        performed_on=on, source="shop", shop="Corner Garage", tax_cents=tax, lines=lines), confirmed=confirmed)


def _line(description, cents, kind="labor", *covers):
    return services.LineInput(description=description, kind=kind, amount_cents=cents,
                              covers=[services.Coverage(code, action) for code, action in covers])


def test_visits_read_every_confirmed_visits_lines_and_what_they_covered(conn, car):
    other = vehicles.create(conn, vehicles.VehicleFields(name="Forester"))
    _visit(conn, car, "2024-03-01", [
        _line("Oil and filter", 6_000, "labor", ("engine_oil", "replace"), ("oil_filter", "replace")),
        _line("Multi-point inspection", 0, "labor", ("multipoint_inspection", "inspect")),
        _line("Shop supplies", 500, "fee"),
    ], tax=425)
    _visit(conn, other, "2023-01-05", [_line("Rotate tires", 2_000, "labor", ("tire_rotation", "perform"))])
    _visit(conn, car, "2024-06-01", [_line("Wipers", 3_000, "part", ("wiper_blades", "replace"))], confirmed=False)
    services.create_event(conn, car, services.EventInput(performed_on="2024-07-01", source="attested"))   # no lines

    found = prices.visits(conn)
    assert [(v["performed_on"], v["vehicle_id"], v["tax_cents"]) for v in found] == [
        ("2023-01-05", other, None), ("2024-03-01", car, 425)]
    assert found[1]["lines"] == [
        {"kind": "labor", "amount_cents": 6_000, "covers": {"engine_oil": "replace", "oil_filter": "replace"}},
        {"kind": "labor", "amount_cents": 0, "covers": {"multipoint_inspection": "inspect"}},
        {"kind": "fee", "amount_cents": 500, "covers": {}},
    ]


def _pdf(text):
    with pymupdf.open() as doc:
        doc.new_page(width=612, height=792).insert_text((72, 72), text)
        return doc.tobytes()


def _receipt(conn, extraction):
    document, _ = documents.store(conn, _pdf(str(id(extraction))), "scan.pdf")
    job_id = jobs.create(conn, "read_receipts")
    receipt_id = receipts.create(conn, document["id"], job_id)
    receipts.claim_next(conn, job_id)
    types = {r["code"]: dict(r) for r in services.list_types(conn)}
    draft = drafts.from_extraction(extraction, types, receipts.learned(conn))
    receipts.mark_read(conn, receipt_id, extraction.model_dump(), draft, [], fx.USAGE)
    return receipt_id


def test_quotes_come_from_a_cars_confirmed_receipts_only(conn, car):
    other = vehicles.create(conn, vehicles.VehicleFields(name="Forester"))
    recs = [
        fx.Recommendation(description="Brake fluid flush", service_codes=["brake_fluid"], quoted_amount=129.95),
        fx.Recommendation(description="Rear wiper", service_codes=["wiper_blades"], quoted_amount=None),   # no price
        fx.Recommendation(description="Check the noise", service_codes=[], quoted_amount=50.0),          # no type
    ]
    confirmed = _receipt(conn, fx.extraction(recommendations=recs))
    receipts.confirm(conn, confirmed, receipts.get(conn, confirmed)["draft"], car)
    _receipt(conn, fx.extraction(date="2017-01-01", recommendations=recs))   # read, never confirmed
    elsewhere = _receipt(conn, fx.extraction(date="2018-01-01", recommendations=recs))
    receipts.confirm(conn, elsewhere, receipts.get(conn, elsewhere)["draft"], other)

    assert prices.quotes(conn, car) == [
        {"day": "2016-08-15", "codes": ["brake_fluid"], "cents": 12_995, "description": "Brake fluid flush"}]
