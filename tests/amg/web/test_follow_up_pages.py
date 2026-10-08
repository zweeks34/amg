"""Shop recommendations on the car's page, the garage and the weekly email: listing, Not doing it, Log it.

Every test receipt (receipt_fixtures) recommends a brake fluid flush, quoted $129.95.
"""

from __future__ import annotations

from datetime import date, timedelta

import report_fixtures as rf  # tests/ is on pytest's path

from amg.alerts import mail, watch
from amg.repo import alerts, follow_ups, vehicles

TODAY = date.today()


def _receipt(conn, car, days_ago, name="one"):
    day = (TODAY - timedelta(days=days_ago)).isoformat()
    return rf.receipt(conn, car, rf.pdf_bytes(name.upper()), f"{name}.pdf", date=day, shop_name="Midas")


def test_the_car_page_lists_recent_ones_and_folds_older_ones(signed_in, conn):
    car = rf.car(conn, "Outback")
    recent, event = _receipt(conn, car, 30)
    _receipt(conn, car, 400, "old")
    page = signed_in.get(f"/vehicles/{car}").text
    assert 'id="follow-ups"' in page and "Shop recommendations" in page and "$260 quoted" in page
    assert "Brake fluid flush" in page and "quoted $129.95" in page and f'href="/services/{event}"' in page
    assert "1 older" in page and "Brake fluid" in page                       # its service, as a chip
    assert f"/vehicles/{car}/services/new?receipt={recent}&amp;rec=brake%20fluid%20flush" in page


def test_not_doing_it_then_undo(signed_in, conn):
    car = rf.car(conn, "Outback")
    receipt, _ = _receipt(conn, car, 30)
    response = signed_in.post("/follow-ups/skip", data={"receipt_id": receipt, "key": "brake fluid flush"},
                              follow_redirects=False)
    assert response.headers["location"] == f"/vehicles/{car}#follow-ups"
    page = signed_in.get(f"/vehicles/{car}").text
    assert "1 not doing" in page and "Nothing the shops recommended in the last 12 months is still open." in page
    signed_in.post("/follow-ups/undo", data={"receipt_id": receipt, "key": "brake fluid flush"})
    assert "not doing" not in signed_in.get(f"/vehicles/{car}").text
    assert signed_in.post("/follow-ups/skip", data={"receipt_id": receipt, "key": "nope"}).status_code == 404


def test_log_it_fills_the_form_and_saving_closes_it(signed_in, conn):
    car = rf.car(conn, "Outback")
    receipt, _ = _receipt(conn, car, 30)
    form = signed_in.get(f"/vehicles/{car}/services/new?receipt={receipt}&rec=brake%20fluid%20flush").text
    assert "Logging what Midas recommended on" in form and "Saving it closes the recommendation." in form
    assert '"description": "Brake fluid flush"' in form and '"covers": ["brake_fluid"]' in form
    other = rf.car(conn, "Civic")                       # another car's recommendation fills nothing
    assert "Logging what" not in signed_in.get(f"/vehicles/{other}/services/new?receipt={receipt}&rec=brake%20fluid%20flush").text

    lines = '[{"description": "Brake fluid flush", "kind": "labor", "amount": "", "covers": [], "inspect_only": false}]'
    response = signed_in.post(f"/vehicles/{car}/services", data={
        "performed_on": TODAY.isoformat(), "source": "diy", "lines_json": lines,
        "follow_up_receipt": str(receipt), "follow_up": "brake fluid flush"}, follow_redirects=False)
    assert response.status_code == 303
    assert follow_ups.outcomes(conn, car)[(receipt, "brake fluid flush")].outcome == "done"
    assert 'id="follow-ups"' not in signed_in.get(f"/vehicles/{car}").text


def test_a_later_service_doing_the_work_closes_it(signed_in, conn):
    car = rf.car(conn, "Outback")
    _receipt(conn, car, 30)
    rf.visit(conn, car, (TODAY - timedelta(days=5)).isoformat(), shop="Corner Garage",
             lines=[rf.line("Brake fluid exchange", 12_000, "brake_fluid")])
    assert 'id="follow-ups"' not in signed_in.get(f"/vehicles/{car}").text


def test_the_garage_counts_recent_ones(signed_in, conn):
    car = rf.car(conn, "Outback")
    _receipt(conn, car, 30)
    _receipt(conn, car, 400, "old")
    assert "1 recommended" in signed_in.get("/").text


def test_the_weekly_email_lists_the_last_12_months(conn):
    car = rf.car(conn, "Outback")
    _receipt(conn, car, 30)
    _receipt(conn, car, 400, "old")
    alerts.switch(conn, car, True)
    looked = watch.look(conn, vehicles.get(conn, car), TODAY)
    day = TODAY - timedelta(days=30)
    when = f"{day:%b} {day.day}" + (f", {day.year}" if day.year != TODAY.year else "")
    text = mail.text([looked], 0, "http://amg.home.arpa")
    assert f"Recommended by the shop\n  • Brake fluid flush: {when}, Midas · quoted $129.95\n" in text
    assert text.count("Brake fluid flush") == 1
    alerts.switch(conn, car, False)                    # old receipts may still be going in
    assert "Recommended by the shop" not in mail.text([watch.look(conn, vehicles.get(conn, car), TODAY)], 0, "")
