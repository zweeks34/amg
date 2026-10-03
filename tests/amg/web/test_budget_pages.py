"""The budget pages, the garage's line about them, and setting prices.

The car: new 400 days ago and driven 30 mi a day, so it's at 12,000 mi
today, when it had its oil changed: $60, plus $4 of shop supplies and $4 of
tax, so $68. Its schedule:

* Oil and filter, every 6,000 mi or 12 months: next at 18,000 (in 200 days).
* Tire rotation, every 5,000 mi, never done: missed at 5,000, overdue since
  10,000, then due at 15,000 (in 100 days) and 20,000 (in 267 days). Priced
  from the Forester's $25 rotation today.
* Cabin air filter, every 12 months, never done: overdue now, and due again
  in about 330 days. Nothing prices it.
* Brake lines, inspected every 12 months: overdue now and in about 330 days.
  An inspection: part of a visit.

So over 12 months: $68 + 3 × $25 = $143 of maintenance, $25 of it due now,
and ($143 − $25) / 12 = $9.83 a month to put aside.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from amg.ingest import background, claude
from amg.ingest.prices import JobPrice, PriceEstimates
from amg.repo import fuel, prices, schedules, services, vehicles
from amg.repo.schedules import ItemInput
from amg.web import budget

TODAY = date.today()


def _visit(conn, car, lines, odometer=None, tax=None):
    return services.create_event(conn, car, services.EventInput(
        performed_on=TODAY.isoformat(), source="shop", shop="Corner Garage", odometer=odometer, tax_cents=tax,
        lines=[services.LineInput(text, kind, amount_cents=cents,
                                  covers=[services.Coverage(code, action) for code, action in covers])
               for text, kind, cents, covers in lines]))


def _schedule(conn, car, items):
    draft_id = schedules.create_draft(conn, car, "template", draft={"origin": "template", "items": []})
    schedules.confirm(conn, draft_id, car, items, {"origin": "template", "items": []})


@pytest.fixture
def car(conn):
    car = vehicles.create(conn, vehicles.VehicleFields(
        name="Outback", year=2016, make="Subaru", model="Outback",
        in_service_date=(TODAY - timedelta(days=400)).isoformat()))
    _schedule(conn, car, [
        ItemInput("Oil and filter", "replace", ["engine_oil", "oil_filter"], interval_miles=6_000, interval_months=12),
        ItemInput("Tire rotation", "perform", ["tire_rotation"], interval_miles=5_000),
        ItemInput("Cabin air filter", "replace", ["cabin_air_filter"], interval_months=12),
        ItemInput("Brake lines", "inspect", ["brake_system"], interval_months=12),
    ])
    _visit(conn, car, [("Oil and filter", "labor", 6_000, [("engine_oil", "replace"), ("oil_filter", "replace")]),
                       ("Shop supplies", "fee", 400, [])], odometer=12_000, tax=400)
    other = vehicles.create(conn, vehicles.VehicleFields(name="Forester"))
    _visit(conn, other, [("Rotate tires", "labor", 2_500, [("tire_rotation", "perform")])])
    return car


def test_the_figures_match_the_worked_example(conn, car):
    plan = budget.load(conn, vehicles.get(conn, car))
    assert (plan.maintenance, plan.due_now, plan.per_month, plan.unpriced) == (14_300, 2_500, 983, 2)
    assert plan.fuel is None
    assert [j["name"] for j in plan.to_ask] == ["Cabin air filter"]   # not the inspection
    assert sorted(plan.item_costs().values()) == [2_500, 6_800]


def test_a_cars_budget_says_what_each_price_comes_from(signed_in, car):
    page = signed_in.get(f"/vehicles/{car}/budget").text
    assert "$10<span class=\"figure__unit\"> a month</span>" in page
    assert ">$25<" in page and "3 overdue jobs" in page                # due now: only the rotation has a price
    assert ">$143<" in page and "next 12 months, 2 not priced" in page
    assert f"Paid {TODAY:%b %Y}" in page                               # oil and filter, on this car
    assert "Paid on your Forester" in page                            # the rotation
    assert "No price yet" in page and "Usually part of a visit" in page
    assert "2 upcoming jobs have no price yet" in page
    assert "Log fill-ups with their cost to budget for fuel." in page
    assert "Ask Claude to price 1 job" in page
    assert page.count('<span class="bitem__name">Tire rotation</span>') == 3


def test_your_price_changes_the_total_and_removing_it_brings_amgs_back(signed_in, car):
    form = {"codes": "engine_oil,oil_filter", "action": "replace", "name": "Oil and filter", "months": "12"}
    saved = signed_in.post(f"/vehicles/{car}/prices", data={**form, "price": "$100", "do": "save"}, follow_redirects=False)
    assert saved.status_code == 303 and saved.headers["location"] == f"/vehicles/{car}/budget#prices"
    page = signed_in.get(f"/vehicles/{car}/budget").text
    assert ">$175<" in page and "Your price" in page and "Use AMG's estimate" in page

    signed_in.post(f"/vehicles/{car}/prices", data={**form, "do": "remove"})
    assert ">$143<" in signed_in.get(f"/vehicles/{car}/budget").text


@pytest.mark.parametrize("typed, message", [
    ("", "Enter what one visit costs, like 89.99."),
    ("1O5", "Enter an amount like 89.99."),
    ("-5", "A price can&#39;t be below zero."),
    ("90000", "That&#39;s more than any one job costs. Check for an extra digit."),
])
def test_a_price_that_isnt_one_is_refused_on_its_row(signed_in, car, typed, message):
    response = signed_in.post(f"/vehicles/{car}/prices", data={
        "codes": "cabin_air_filter", "action": "replace", "name": "Cabin air filter", "price": typed, "do": "save"})
    assert response.status_code == 422
    assert message in response.text and f'value="{typed}"' in response.text
    assert "editing: true" in response.text                              # that row's editor is open


def test_asking_claude_queues_the_unpriced_jobs_and_the_page_waits(signed_in, conn, car, monkeypatch):
    monkeypatch.setattr(background, "spawn", lambda job_id: None)   # the thread hasn't got to it yet
    response = signed_in.post(f"/vehicles/{car}/prices/ask", data={"months": "24"}, follow_redirects=False)
    assert response.headers["location"] == f"/vehicles/{car}/budget?months=24#prices"
    (row,) = prices.for_car(conn, car)
    assert (row["codes"], row["source"], row["status"]) == ("cabin_air_filter", "claude", "queued")
    page = signed_in.get(f"/vehicles/{car}/budget").text
    assert "Claude is pricing 1 job" in page and 'hx-trigger="every 3s"' in page
    assert "Ask Claude" not in page

    monkeypatch.setattr(claude, "parse", lambda *a, **k: (
        PriceEstimates(prices=[JobPrice(key=f"j{row['id']}", low_usd=40, high_usd=80, note="OEM filter")]),
        claude.Usage("claude-opus-5-5", 1_000, 200, 0, 0, 5.0, "req")))
    background.run(row["job_id"])
    page = signed_in.get(f"/vehicles/{car}/budget").text
    assert "Claude&#39;s estimate, $40–80" in page and "OEM filter" in page and "hx-trigger" not in page
    assert ">$263<" in page                                            # 143 + two cabin filters at $60


def test_pricing_cut_off_by_a_restart_can_be_asked_again(signed_in, conn, car, monkeypatch):
    monkeypatch.setattr(background, "spawn", lambda job_id: None)
    signed_in.post(f"/vehicles/{car}/prices/ask", data={})
    conn.execute("UPDATE jobs SET heartbeat_at = '2000-01-01T00:00:00Z'")
    page = signed_in.get(f"/vehicles/{car}/budget").text
    assert "Pricing stopped part-way" in page and "Ask Claude to price 1 job" in page and "hx-trigger" not in page


def test_the_horizon_is_twelve_months_two_years_or_three(signed_in, car):
    page = signed_in.get(f"/vehicles/{car}/budget?months=24").text
    assert 'href="/vehicles/%d/budget?months=24" aria-current="page"' % car in page and "next 2 years" in page
    assert "next 12 months" in signed_in.get(f"/vehicles/{car}/budget?months=7").text


def test_the_garage_and_the_car_page_show_the_budget(signed_in, car):
    garage = signed_in.get("/").text
    assert 'href="/budget"' in garage and "~$143 of maintenance ($25 of it overdue now)" in garage
    page = signed_in.get(f"/vehicles/{car}").text
    assert "~$143 of maintenance in the next 12 months, $25 of it overdue now: put aside" in page
    assert "~$25" in page                                              # the overdue rotation's cost in next up


def test_the_whole_garage_adds_up_and_leaves_archived_cars_out(signed_in, conn, car):
    other = next(c for c in vehicles.garage(conn)[0] if c["name"] == "Forester")
    _schedule(conn, other["id"], [ItemInput("Tire rotation", "perform", ["tire_rotation"], interval_months=6)])
    gone = vehicles.create(conn, vehicles.VehicleFields(name="Old Civic"))
    vehicles.archive(conn, gone)
    page = signed_in.get("/budget").text
    assert "Outback" in page and "Forester" in page and "Old Civic" not in page
    assert ">$168<" in page                                            # 143 + the Forester's rotation, in six months


def test_a_car_with_no_schedule_budgets_fuel_alone(signed_in, conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Runabout"))
    for n in range(4):
        day = TODAY - timedelta(days=30 * (3 - n))
        fuel.create(conn, car, fuel.FillInput(day.isoformat(), 10_000 + 300 * n, "gas", 10.0, 3_000))
    page = signed_in.get(f"/vehicles/{car}/budget").text
    assert "Runabout has no maintenance schedule yet, so only fuel is budgeted." in page
    assert "~10 mi a day at 10.0¢ a mile, last 12 months" in page
    assert "Prices" not in page


def test_the_bars_scale_to_a_round_figure_and_label_the_months():
    from amg.engine import forecast

    def month_list(count):
        found = [forecast.Month(start, end) for start, end in forecast.months(date(2026, 10, 3), count)]
        oil = forecast.Due(1, "Oil", forecast.Job(frozenset({"engine_oil"}), "replace"), "later", date(2026, 10, 9),
                           date(2026, 10, 9), None)
        found[0].items.append((oil, forecast.Price(120_000, 120_000, 120_000, "yours")))
        found[3].items.append((oil, forecast.Price(30_000, 30_000, 30_000, "yours")))
        return found

    chart = budget.chart(month_list(12), 10_000, 12)
    assert [bar["h"] for bar in chart["bars"]][:4] == [80.0, 0.0, 0.0, 20.0]   # on a $1,500 scale
    assert [(t["y"], t["label"]) for t in chart["ticks"]] == [(33.33, "$500"), (66.67, "$1,000"), (100.0, "$1,500")]
    assert chart["line"] == 6.67 and not chart["dense"]
    assert [bar["label"] for bar in chart["bars"]][:4] == ["Oct", "Nov", "Dec", "Jan"]

    dense = budget.chart(month_list(24), 10_000, 24)
    assert dense["dense"] and [(i, b["label"]) for i, b in enumerate(dense["bars"]) if b["label"]] == [(3, "2027"), (15, "2028")]
    assert budget.chart([forecast.Month(date(2026, 10, 3), date(2026, 10, 31))], 0, 12) is None   # nothing to draw
