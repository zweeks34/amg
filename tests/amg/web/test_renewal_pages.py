"""Inspections and registration on the car page and the garage: the words, the forms, a receipt's offer."""

from __future__ import annotations

import html
from datetime import date, timedelta

import pytest
import report_fixtures as rf  # tests/ is on pytest's path

from amg.engine.renewals import Standing, end_of_month
from amg.repo import renewals, vehicles
from amg.repo.renewals import RenewalInput
from amg.web import renewals as words

TODAY = date.today()
OCT_5 = date(2026, 10, 5)


def day(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def short(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}" + (f", {d.year}" if d.year != TODAY.year else "")


@pytest.fixture
def car(conn):
    return rf.car(conn, "Outback")


def inspection(conn, car, on, cents=2_000, shop="Midas", confirmed=True):
    return rf.visit(conn, car, on, shop=shop, confirmed=confirmed,
                    lines=[rf.line("State inspection", cents, "state_inspection", action="perform")])


# ---------- The words ----------


def test_each_row_in_words(conn, car):
    renewals.create(conn, car, RenewalInput("safety", "2026-11-30"))
    renewals.create(conn, car, RenewalInput("emissions", "2026-10-31"))
    renewals.create(conn, car, RenewalInput("registration", "2026-09-30"))
    rows = {row.kind.code: row for row in words.rows(conn, vehicles.get(conn, car), OCT_5)}
    assert [(r.said, r.mark, r.mark_label) for r in rows.values()] == [
        ("Expires Nov 30", "later", "Later"),
        ("Expires Oct 31 · in 26 days", "due", "Due soon"),
        ("Expired Sep 30 · 5 days ago", "overdue", "Expired"),
    ]
    assert [r.kind.code for r in words.urgent(list(rows.values()))] == ["registration", "emissions"]


@pytest.mark.parametrize(("expires", "said"), [
    (date(2026, 10, 5), "expires today"),
    (date(2026, 10, 6), "expires Oct 6 · in 1 day"),
    (date(2027, 1, 31), "expires Jan 31, 2027"),
    (date(2026, 10, 4), "expired Oct 4 · 1 day ago"),
    (date(2025, 1, 31), "expired Jan 31, 2025"),     # long gone: the date says it
])
def test_when(expires, said):
    from amg.engine.renewals import standing
    assert words.when(standing(expires, OCT_5), expires, OCT_5) == said


def test_an_electric_car_has_no_emissions_row_unless_it_has_one_logged(conn):
    ev = rf.car(conn, "Bolt", powertrain="ev")
    assert [r.kind.code for r in words.rows(conn, vehicles.get(conn, ev))] == ["safety", "registration"]
    renewals.create(conn, ev, RenewalInput("emissions", "2027-03-31"))
    assert [r.kind.code for r in words.rows(conn, vehicles.get(conn, ev))] == ["safety", "emissions", "registration"]


def test_what_the_forms_start_with(conn, car):
    rows = {r.kind.code: r for r in words.rows(conn, vehicles.get(conn, car), OCT_5)}
    assert rows["safety"].form == {"done_on": "", "expires_on": "", "cost": "", "note": ""}    # from the sticker
    assert rows["safety"].action == "Add the expiry date" and "guessed" not in rows["safety"].hint
    renewals.create(conn, car, RenewalInput("registration", "2026-10-31", "2025-10-20"))
    row = words.rows(conn, vehicles.get(conn, car), OCT_5)[-1]
    assert (row.form["done_on"], row.form["expires_on"]) == ("2026-10-05", "2027-10-31")
    assert row.action == "Log a renewal" and row.hint.endswith("AMG guessed this one: check it against the card.")


# ---------- The car page ----------


def test_the_car_page_block(signed_in, conn, car):
    renewals.create(conn, car, RenewalInput("registration", day(10), cost_cents=4_075, note="Online"))
    page = html.unescape(signed_in.get(f"/vehicles/{car}").text)
    assert 'id="renewals-heading">Inspections and registration</h2>' in page
    assert "Not tracked" in page and "Add the expiry date" in page and "Log a renewal" in page
    assert f"Expires {short(day(10))} · in 10 days" in page
    assert f"Expires <span class=\"mono\">{day(10)}</span>" in page and "$40.75 · Online" in page
    assert 'id="f-safety-expires_on"' in page and 'id="f-registration-expires_on"' in page   # their own ids


def test_no_block_on_an_archived_car(signed_in, conn, car):
    vehicles.archive(conn, car)
    assert "Inspections and registration" not in signed_in.get(f"/vehicles/{car}").text
    response = signed_in.post(f"/vehicles/{car}/renewals", data={"kind": "safety", "expires_on": day(30)},
                              follow_redirects=False)
    assert response.status_code == 404


def test_adding_the_first_date(signed_in, conn, car):
    response = signed_in.post(f"/vehicles/{car}/renewals",
                              data={"kind": "safety", "done_on": "", "expires_on": day(300), "cost": "", "note": ""},
                              follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == f"/vehicles/{car}#renewals"
    [row] = renewals.for_car(conn, car)["safety"]
    assert (row["done_on"], row["expires_on"], row["cost_cents"], row["service_event_id"]) == (None, day(300), None, None)


def test_logging_a_renewal(signed_in, conn, car):
    renewals.create(conn, car, RenewalInput("registration", day(10)))
    signed_in.post(f"/vehicles/{car}/renewals", data={"kind": "registration", "done_on": day(0),
                                                      "expires_on": day(375), "cost": "$40.75", "note": ""})
    current = renewals.for_car(conn, car)["registration"][0]
    assert (current["expires_on"], current["cost_cents"]) == (day(375), 4_075)
    assert "in 10 days" not in html.unescape(signed_in.get(f"/vehicles/{car}").text)


@pytest.mark.parametrize(("data", "error"), [
    ({"expires_on": ""}, "Enter the date it expires."),
    ({"done_on": day(-3), "expires_on": day(-4)}, "That's before it was done."),
    ({"done_on": day(2), "expires_on": day(400)}, "That date is in the future."),
    ({"expires_on": day(300), "cost": "twenty"}, "Enter an amount like 89.99."),
    ({"expires_on": day(300), "cost": "-5"}, "Enter what it cost, like 20.00."),
])
def test_a_form_with_errors_comes_back_open(signed_in, conn, car, data, error):
    response = signed_in.post(f"/vehicles/{car}/renewals", data={"kind": "emissions", **data})
    page = html.unescape(response.text)
    assert response.status_code == 422 and error in page
    # The emissions form is open with what was typed; the others stay shut.
    before = page.split('value="emissions"')[0]
    assert page.count("{ open: true }") == 1 and before.rfind("{ open: true }") > before.rfind('value="safety"')
    assert renewals.for_car(conn, car) == {}


def test_an_unknown_kind_is_refused(signed_in, car):
    assert signed_in.post(f"/vehicles/{car}/renewals", data={"kind": "insurance", "expires_on": day(30)}).status_code == 400


# ---------- An inspection in the service history ----------


def test_a_receipt_is_offered_and_logged(signed_in, conn, car):
    service = inspection(conn, car, day(-40))
    guess = _plus_year_end(day(-40))     # a year on from the receipt, to the month's end
    page = html.unescape(signed_in.get(f"/vehicles/{car}").text)
    assert f'Your service history shows <a href="/services/{service}">a state inspection at Midas on {short(day(-40))}</a>.' in page
    form = page.split('value="safety"')[1].split("</form>")[0]
    assert f'name="service_event_id" value="{service}"' in form
    assert f'value="{day(-40)}"' in form and f'value="{guess}"' in form and 'value="20.00"' in form
    signed_in.post(f"/vehicles/{car}/renewals", data={"kind": "safety", "service_event_id": str(service),
                                                      "done_on": day(-40), "expires_on": guess, "cost": "20.00"})
    [row] = renewals.for_car(conn, car)["safety"]
    assert (row["service_event_id"], row["cost_cents"]) == (service, 2_000)
    assert "Your service history shows" not in signed_in.get(f"/vehicles/{car}").text


def test_a_different_date_is_another_inspection(signed_in, conn, car):
    service = inspection(conn, car, day(-40))
    signed_in.post(f"/vehicles/{car}/renewals", data={"kind": "safety", "service_event_id": str(service),
                                                      "done_on": day(-30), "expires_on": day(330)})
    assert renewals.for_car(conn, car)["safety"][0]["service_event_id"] is None


def test_another_cars_service_is_never_linked(signed_in, conn, car):
    other = inspection(conn, rf.car(conn, "Civic"), day(-40))
    signed_in.post(f"/vehicles/{car}/renewals", data={"kind": "safety", "service_event_id": str(other),
                                                      "done_on": day(-40), "expires_on": day(330)})
    assert renewals.for_car(conn, car)["safety"][0]["service_event_id"] is None


def test_no_offer_when_it_would_not_move_the_expiry(signed_in, conn, car):
    inspection(conn, car, day(-40))
    renewals.create(conn, car, RenewalInput("safety", _plus_year_end(day(-40))))    # typed from the sticker
    assert "Your service history shows" not in signed_in.get(f"/vehicles/{car}").text


def test_no_offer_for_a_receipt_waiting_to_be_checked(signed_in, conn, car):
    inspection(conn, car, day(-40), confirmed=False)
    assert "Your service history shows" not in signed_in.get(f"/vehicles/{car}").text


def _plus_year(d: date) -> date:
    return end_of_month(date(d.year + 1, d.month, 1))


def _plus_year_end(iso: str) -> str:
    return _plus_year(date.fromisoformat(iso)).isoformat()


# ---------- Correcting ----------


def test_edit_and_delete(signed_in, conn, car):
    service = inspection(conn, car, "2026-09-02")
    renewal = renewals.create(conn, car, RenewalInput("safety", "2027-09-30", "2026-09-02", 2_000, "",
                                                      service_event_id=service))
    page = html.unescape(signed_in.get(f"/renewals/{renewal}/edit").text)
    assert "<h1 class=\"display\">Safety inspection</h1>" in page and 'value="2027-09-30"' in page
    assert f'<a href="/services/{service}">the service on 2026-09-02 at Midas</a>' in page
    response = signed_in.post(f"/renewals/{renewal}/edit", data={"done_on": "2026-09-02", "expires_on": "2027-08-31",
                                                                 "cost": "20", "note": "Punched 8/27"},
                              follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == f"/vehicles/{car}#renewals"
    row = renewals.get(conn, renewal)
    assert (row["expires_on"], row["note"], row["service_event_id"]) == ("2027-08-31", "Punched 8/27", service)
    bad = signed_in.post(f"/renewals/{renewal}/edit", data={"done_on": "2026-09-02", "expires_on": ""})
    assert bad.status_code == 422 and "Enter the date it expires." in bad.text
    signed_in.post(f"/renewals/{renewal}/delete")
    assert renewals.get(conn, renewal) is None
    assert signed_in.get(f"/renewals/{renewal}/edit").status_code == 404


def test_changing_the_date_unlinks_the_service(signed_in, conn, car):
    service = inspection(conn, car, "2026-09-02")
    renewal = renewals.create(conn, car, RenewalInput("safety", "2027-09-30", "2026-09-02", service_event_id=service))
    signed_in.post(f"/renewals/{renewal}/edit", data={"done_on": "2026-09-03", "expires_on": "2027-09-30"})
    assert renewals.get(conn, renewal)["service_event_id"] is None


# ---------- The garage ----------


def test_the_garage_card_says_what_is_due(signed_in, conn, car):
    renewals.create(conn, car, RenewalInput("registration", day(10)))
    renewals.create(conn, car, RenewalInput("safety", day(200)))       # not news
    page = html.unescape(signed_in.get("/").text)
    assert f'<span class="carcard__label">Registration</span> <span class="muted">expires {short(day(10))} · in 10 days</span>' in page
    assert '<span class="carcard__label">Safety inspection</span>' not in page
    assert "No maintenance schedule yet." in page      # said in the card with the date


def test_the_pages_need_a_session(client, conn, car):
    renewal = renewals.create(conn, car, RenewalInput("safety", day(30)))
    assert client.post(f"/vehicles/{car}/renewals", data={"kind": "safety", "expires_on": day(30)},
                       follow_redirects=False).status_code == 303
    assert client.get(f"/renewals/{renewal}/edit", follow_redirects=False).status_code == 303
    assert client.post(f"/renewals/{renewal}/delete", follow_redirects=False).status_code == 303
    assert renewals.get(conn, renewal) is not None and len(renewals.for_car(conn, car)["safety"]) == 1


def test_standing_is_what_the_rows_carry(conn, car):
    renewals.create(conn, car, RenewalInput("safety", "2026-10-12"))
    assert words.rows(conn, vehicles.get(conn, car), OCT_5)[0].standing == Standing("week", 7)
