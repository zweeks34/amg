"""Inspections and registration in the alerts: pushed at 30 days, in the last week and once expired, each once;
whatever the car's alerts switch says."""

from __future__ import annotations

from datetime import date

import alert_fixtures as af  # tests/ is on pytest's path
import pytest

from amg.alerts import mail, run, watch
from amg.repo import alerts, renewals, vehicles
from amg.repo.renewals import RenewalInput

BASE = "http://amg.home.arpa"


@pytest.fixture
def bolt(conn):
    """No schedule, alerts off: watched for its dates alone."""
    return vehicles.create(conn, vehicles.VehicleFields(name="Bolt", powertrain="ev"))


def _run(conn, day):
    return run.run(conn, day, say=lambda words: None)


def test_pushed_a_month_out_in_the_last_week_and_once_expired(conn, bolt, pushes):
    renewals.create(conn, bolt, RenewalInput("registration", "2026-10-31"))
    for day in (date(2026, 9, 30), date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 24), date(2026, 10, 25),
                date(2026, 10, 31), date(2026, 11, 1), date(2026, 11, 2)):
        _run(conn, day)
    assert [(p.title, p.message, p.priority) for p in pushes] == [
        ("Bolt: Registration due soon", "expires Oct 31 · in 30 days", 3),
        ("Bolt: Registration due soon", "expires Oct 31 · in 7 days", 3),
        ("Bolt: Registration expired", "expired Oct 31 · 1 day ago", 4),
    ]
    assert pushes[0].click == f"{BASE}/vehicles/{bolt}"


def test_logging_the_next_one_starts_fresh(conn, bolt, pushes):
    renewals.create(conn, bolt, RenewalInput("registration", "2026-10-31"))
    _run(conn, date(2026, 11, 1))
    renewals.create(conn, bolt, RenewalInput("registration", "2027-10-31", "2026-11-03"))
    _run(conn, date(2026, 11, 4))                       # renewed: nothing to say
    _run(conn, date(2027, 10, 1))
    assert [p.title for p in pushes] == ["Bolt: Registration expired", "Bolt: Registration due soon"]
    assert pushes[1].message == "expires Oct 31 · in 30 days"


def test_first_seen_in_its_last_week_is_one_push_not_two(conn, bolt, pushes):
    renewals.create(conn, bolt, RenewalInput("safety", "2026-10-31"))
    _run(conn, date(2026, 10, 28))
    _run(conn, date(2026, 10, 29))
    assert [p.message for p in pushes] == ["expires Oct 31 · in 3 days"]


def test_reminders_go_with_the_cars_alerts_off_and_its_jobs_dont(conn, pushes):
    car = af.make_car(conn, on=False)                   # oil and filter due soon on June 10
    renewals.create(conn, car, RenewalInput("registration", "2026-06-30"))
    _run(conn, af.JUNE_10)
    assert [(p.title, p.message) for p in pushes] == [("Outback: Registration due soon", "expires Jun 30 · in 20 days")]


def test_with_the_cars_alerts_on_they_share_its_push(conn, car, pushes):
    renewals.create(conn, car, RenewalInput("registration", "2026-06-30"))
    _run(conn, af.JUNE_10)
    assert [p.title for p in pushes] == ["Outback: 2 due soon"]
    assert pushes[0].message.splitlines() == ["REPLACE Oil and filter: by Jul 1",
                                              "Registration: expires Jun 30 · in 20 days"]   # no word: not a job


def test_turning_alerts_on_takes_stock_of_jobs_only(conn, pushes):
    car = af.make_car(conn, on=False)
    renewals.create(conn, car, RenewalInput("registration", "2026-06-30"))
    alerts.switch(conn, car, True)
    assert watch.take_stock(conn, vehicles.get(conn, car), af.JUNE_10) == 1     # the oil change, held back
    _run(conn, af.JUNE_10)
    assert [p.title for p in pushes] == ["Outback: Registration due soon"]


def test_archived_cars_and_cars_with_nothing_to_watch_are_left_out(conn, bolt):
    assert alerts.cars_watched(conn) == []
    renewals.create(conn, bolt, RenewalInput("safety", "2027-03-31"))
    other = af.make_car(conn, name="Civic", on=True)
    assert [c["name"] for c in alerts.cars_watched(conn)] == ["Bolt", "Civic"]
    vehicles.archive(conn, bolt)
    assert [c["id"] for c in alerts.cars_watched(conn)] == [other]


# ---------- The weekly email ----------


def test_the_email_lists_them_and_a_car_with_alerts_off_shows_only_its_dates(conn, bolt):
    car = af.make_car(conn, on=False)
    renewals.create(conn, car, RenewalInput("registration", "2026-06-30"))
    renewals.create(conn, car, RenewalInput("emissions", "2026-06-01"))
    renewals.create(conn, bolt, RenewalInput("safety", "2027-03-31"))
    renewals.create(conn, bolt, RenewalInput("registration", "2026-11-30"))
    watches = [watch.look(conn, c, af.JUNE_10) for c in alerts.cars_watched(conn)]
    assert mail.subject(watches) == "AMG: 1 overdue, 1 due soon"
    text = mail.text(watches, 0, BASE)
    assert ("BOLT\nNothing due: Safety inspection expires Mar 31, 2027; Registration expires Nov 30.\n"
            "Maintenance alerts are off for this car.\n") in text
    assert ("OUTBACK\nOverdue\n  • Emissions inspection: expired Jun 1 · 9 days ago\n"
            "Due soon\n  • Registration: expires Jun 30 · in 20 days\nMaintenance alerts are off for this car.\n") in text
    assert "Oil and filter" not in text and "when inspections and registrations expire" in text
    html = mail.digest(watches, 0, BASE, run.calendar(watches, BASE)).get_body(("html",)).get_content()
    assert "Registration <span" in html and "Maintenance alerts are off for this car." in html
    assert "Nothing due: Safety inspection expires Mar 31, 2027; Registration expires Nov 30." in html


def test_a_car_with_no_schedule_and_alerts_on(conn, bolt):
    alerts.switch(conn, bolt, True)
    renewals.create(conn, bolt, RenewalInput("registration", "2026-06-30"))
    text = mail.text([watch.look(conn, vehicles.get(conn, bolt), af.JUNE_10)], 0, BASE)
    assert "Due soon\n  • Registration: expires Jun 30 · in 20 days\nNo maintenance schedule yet, so no jobs to watch." in text


# ---------- The calendar ----------


def test_each_expiry_is_an_event_that_moves_when_renewed(conn, bolt):
    renewals.create(conn, bolt, RenewalInput("registration", "2026-10-31"))
    renewals.create(conn, bolt, RenewalInput("safety", "2026-09-30"))          # expired: left out
    renewals.create(conn, bolt, RenewalInput("emissions", "2029-03-31"))       # years off: in all the same

    def found(day):
        return [(e.uid, e.day, e.summary) for e in watch.events([watch.look(conn, vehicles.get(conn, bolt), day)], BASE)]

    assert found(date(2026, 10, 5)) == [
        (f"amg-{bolt}-registration@amg", date(2026, 10, 31), "Registration expires · Bolt"),
        (f"amg-{bolt}-emissions@amg", date(2029, 3, 31), "Emissions inspection expires · Bolt"),
    ]
    renewals.create(conn, bolt, RenewalInput("registration", "2027-10-31", "2026-10-20"))
    assert found(date(2026, 10, 21))[0] == (f"amg-{bolt}-registration@amg", date(2027, 10, 31),
                                            "Registration expires · Bolt")


def test_a_car_with_alerts_off_brings_only_its_dates_to_the_emailed_calendar(conn):
    car = af.make_car(conn, on=False)
    renewals.create(conn, car, RenewalInput("registration", "2026-06-30"))
    summaries = [e.summary for e in watch.events([watch.look(conn, vehicles.get(conn, car), af.JUNE_10)], BASE)]
    assert summaries == ["Registration expires · Outback"]
    every = watch.events([watch.look(conn, vehicles.get(conn, car), af.JUNE_10, maintenance=True)], BASE)
    assert "Oil and filter · Outback" in [e.summary for e in every]     # the Alerts page's download: every job


def test_a_reminder_says_what_it_cost_last_time(conn, bolt, pushes):
    renewals.create(conn, bolt, RenewalInput("registration", "2026-10-31", "2025-10-20", 4_075))
    _run(conn, date(2026, 10, 1))
    assert [(p.title, p.message) for p in pushes] == [("Bolt: Registration due soon", "expires Oct 31 · in 30 days · ~$41")]
    text = mail.text([watch.look(conn, vehicles.get(conn, bolt), date(2026, 10, 1))], 0, BASE)
    assert "  • Registration: expires Oct 31 · in 30 days · ~$41\n" in text
