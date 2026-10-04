"""The Alerts page: the channels, the per-car switch, the test sends and the calendar file."""

from __future__ import annotations

import alert_fixtures as af  # tests/ is on pytest's path
import pytest

from amg.alerts import mail, ntfy
from amg.repo import alerts, vehicles


def test_channels_that_arent_set_up_say_how(signed_in):
    page = signed_in.get("/alerts").text
    assert "Not set up. Add <span class=\"mono\">AMG_NTFY_TOPIC</span>" in page
    assert "AMG_SMTP_PASSWORD</span>" in page and "Send a test" not in page
    assert "The daily run hasn't run yet." in page
    assert 'href="/alerts" aria-current="page"' in page                # the footer link


def test_channels_that_are_set_up_say_where(signed_in, monkeypatch):
    monkeypatch.setenv("AMG_NTFY_TOPIC", "amg-7f3k")
    monkeypatch.setenv("AMG_SMTP_USER", "me@example.com")
    monkeypatch.setenv("AMG_SMTP_PASSWORD", "pw")
    page = signed_in.get("/alerts").text
    assert '<span class="mono">ntfy.sh/amg-7f3k</span>' in page and "Send a test push" in page
    assert "Mondays, to me@example.com" in page and "Send a test email" in page


def test_turning_a_car_on_takes_stock_and_off_stops_it(signed_in, conn):
    car = af.make_car(conn, on=False)
    response = signed_in.post(f"/alerts/cars/{car}", data={"on": "1"}, follow_redirects=False)
    assert response.headers["location"] == f"/alerts?turned=on&car={car}"
    assert vehicles.get(conn, car)["alerts"] == 1
    assert alerts.logged(conn, "ntfy")                                  # today's due jobs, held back
    assert "Alerts are on for Outback." in signed_in.get(response.headers["location"]).text
    signed_in.post(f"/alerts/cars/{car}", data={"on": "0"})
    assert vehicles.get(conn, car)["alerts"] == 0
    assert 'aria-label="Turn on alerts for Outback"' in signed_in.get("/alerts").text


def test_an_archived_car_cant_be_switched_on(signed_in, conn):
    car = af.make_car(conn, on=False)
    vehicles.archive(conn, car)
    assert signed_in.post(f"/alerts/cars/{car}", data={"on": "1"}).status_code == 404


def test_a_test_push_says_whether_it_went(signed_in, monkeypatch):
    monkeypatch.setenv("AMG_NTFY_TOPIC", "amg-7f3k")
    sent = []
    monkeypatch.setattr(ntfy, "send", lambda push, settings: sent.append(push))
    response = signed_in.post("/alerts/test-push")
    assert "Test push sent." in response.text and sent[0].title == "AMG: test push"

    def refuse(push, settings):
        raise ntfy.SendError("Couldn't reach ntfy.sh (offline).")

    monkeypatch.setattr(ntfy, "send", refuse)
    assert "The test push didn&#39;t go. Couldn&#39;t reach ntfy.sh (offline)." in signed_in.post("/alerts/test-push").text


@pytest.mark.parametrize("setup", [False, True])
def test_a_test_email_says_whether_it_went(signed_in, monkeypatch, setup):
    if setup:
        monkeypatch.setenv("AMG_SMTP_USER", "me@example.com")
        monkeypatch.setenv("AMG_SMTP_PASSWORD", "pw")
    sent = []
    monkeypatch.setattr(mail, "send", lambda message, settings: sent.append(message))
    page = signed_in.post("/alerts/test-email").text
    if setup:
        assert "Test email sent to me@example.com." in page and sent[0]["Subject"] == "AMG: test email"
    else:
        assert "Email isn&#39;t set up yet" in page and sent == []


def test_the_calendar_downloads_and_needs_a_session(signed_in, client, conn):
    af.make_car(conn, on=False)                                          # every car, alerts or not
    response = signed_in.get("/alerts/calendar.ics")
    assert response.headers["content-type"] == "text/calendar; charset=utf-8"
    assert 'filename="amg-maintenance.ics"' in response.headers["content-disposition"]
    assert response.text.startswith("BEGIN:VCALENDAR\r\n") and "SUMMARY:Wiper blades · Outback" in response.text
    signed_in.cookies.clear()
    assert client.get("/alerts/calendar.ics", follow_redirects=False).status_code == 303


def test_the_last_run_and_what_went_out_are_shown(signed_in, conn):
    car = af.make_car(conn)
    alerts.set_last_run(conn, "2026-10-05T08:00:00-04:00", "1 push; no email due", True)
    alert_id = alerts.claim(conn, "ntfy", "s", "overdue", car, "Oil and filter: overdue since Jul 1")
    alerts.mark(conn, alert_id, "failed", "Couldn't reach ntfy.sh (offline).")
    page = signed_in.get("/alerts").text
    assert "Runs daily at 8:00. Last run:" in page and "1 push; no email due." in page
    assert "Outback · Oil and filter: overdue since Jul 1" in page and "Didn't go: Couldn&#39;t reach ntfy.sh" in page
