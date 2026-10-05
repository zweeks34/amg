"""The weekly email: what it says, how it's sent, and that it goes once a week.

Monday 2026-08-10, with the alert_fixtures car: oil and filter overdue since
July 1, wiper blades due soon (Sep 1), the cabin air filter later.
"""

from __future__ import annotations

import smtplib
from datetime import date

import alert_fixtures as af  # tests/ is on pytest's path
import pytest

from amg import config
from amg.alerts import mail, run, watch
from amg.repo import alerts, prices, vehicles

MONDAY = date(2026, 8, 10)
SMTP = config.Smtp("smtp.gmail.com", 587, "me@example.com", "abcdefghijklmnop", "me@example.com")


def _digest(conn, car, to_check=0):
    watched = [watch.look(conn, vehicles.get(conn, car), MONDAY)]
    return mail.digest(watched, to_check, "http://amg.home.arpa", run.calendar(watched, "http://amg.home.arpa"))


def test_the_digest_says_what_is_overdue_due_and_coming(conn, car):
    prices.set_yours(conn, car, ["engine_oil", "oil_filter"], "replace", "Oil and filter", 8_000)
    message = _digest(conn, car, to_check=2)
    assert message["Subject"] == "AMG: 1 overdue, 1 due soon"
    text = message.get_body(("plain",)).get_content()
    assert ("OUTBACK\nOverdue\n  • Oil and filter: overdue since Jul 1 · ~$80\n"
            "Due soon\n  • Wiper blades: by Sep 1\nComing up\n  • Cabin air filter: ~Jan 2028\n") in text
    assert ("~$240 of maintenance in the next 12 months, $80 of it overdue now: put aside $13 a month for the rest"
            " (2 jobs not priced yet).") in text                 # three oil changes at $80
    assert "2 receipts to check: http://amg.home.arpa/receipts" in text
    assert f"http://amg.home.arpa/vehicles/{car}" in text


def test_the_html_part_escapes_and_the_calendar_is_attached(conn):
    car = af.make_car(conn, name="Mum's <Outback>")
    message = _digest(conn, car)
    html = message.get_body(("html",)).get_content()
    assert "Mum&#39;s &lt;Outback&gt;" in html and "<Outback>" not in html
    assert "Oil and filter" in html and "overdue since Jul 1" in html
    (attachment,) = list(message.iter_attachments())
    assert attachment.get_content_type() == "text/calendar" and attachment.get_filename() == "amg-maintenance.ics"
    assert "BEGIN:VCALENDAR" in attachment.get_content()


def test_nothing_due_still_makes_an_email(conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Runabout"))
    alerts.switch(conn, car, True)
    message = _digest(conn, car)
    assert message["Subject"] == "AMG: nothing due this week"
    assert "No maintenance schedule yet" in message.get_body(("plain",)).get_content()


class FakeSMTP:
    """Stands in for smtplib.SMTP and SMTP_SSL, keeping what it was asked to do."""
    log: list = []
    refuse = False

    def __init__(self, host, port, timeout, context=None):
        FakeSMTP.log.append(("connect", host, port, "ssl" if context else "plain"))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context):
        FakeSMTP.log.append(("starttls",))

    def login(self, user, password):
        if FakeSMTP.refuse:
            raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")
        FakeSMTP.log.append(("login", user, password))

    def send_message(self, message):
        FakeSMTP.log.append(("send", message["From"], message["To"], message["Subject"]))


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.log, FakeSMTP.refuse = [], False
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def test_sending_starts_tls_and_logs_in(smtp):
    mail.send(mail.test_message(MONDAY), SMTP)
    assert smtp.log == [("connect", "smtp.gmail.com", 587, "plain"), ("starttls",),
                        ("login", "me@example.com", "abcdefghijklmnop"),
                        ("send", "AMG <me@example.com>", "me@example.com", "AMG: test email")]


def test_port_465_is_ssl_from_the_start(smtp):
    mail.send(mail.test_message(MONDAY), config.Smtp("smtp.gmail.com", 465, "me@example.com", "pw", "you@example.com"))
    assert smtp.log[0] == ("connect", "smtp.gmail.com", 465, "ssl") and ("starttls",) not in smtp.log


def test_a_refused_login_says_to_use_an_app_password(smtp):
    smtp.refuse = True
    with pytest.raises(mail.SendError, match="must be an app password"):
        mail.send(mail.test_message(MONDAY), SMTP)


def test_settings_come_from_the_environment(monkeypatch):
    assert config.smtp() is None
    monkeypatch.setenv("AMG_SMTP_USER", "me@example.com")
    monkeypatch.setenv("AMG_SMTP_PASSWORD", "abcd efgh ijkl mnop")      # as Gmail shows it
    assert config.smtp() == config.Smtp("smtp.gmail.com", 587, "me@example.com", "abcdefghijklmnop", "me@example.com")


# ---------- Once a week ----------


@pytest.fixture
def emails(monkeypatch):
    monkeypatch.setenv("AMG_SMTP_USER", "me@example.com")
    monkeypatch.setenv("AMG_SMTP_PASSWORD", "pw")
    sent = []
    monkeypatch.setattr(mail, "send", lambda message, settings: sent.append(message))
    return sent


def test_the_email_goes_once_a_week(conn, car, emails):
    for day in (MONDAY, date(2026, 8, 11), date(2026, 8, 16)):
        run.run(conn, day, say=lambda words: None)
    assert len(emails) == 1
    run.run(conn, date(2026, 8, 17), say=lambda words: None)     # the next Monday
    assert len(emails) == 2


def test_a_week_that_started_with_the_server_off_gets_its_email_late(conn, car, emails):
    run.run(conn, date(2026, 8, 12), say=lambda words: None)     # a Wednesday: Monday's run never happened
    assert len(emails) == 1


def test_a_failed_email_is_tried_again_the_next_day(conn, car, emails, monkeypatch):
    def refuse(message, settings):
        raise mail.SendError("Couldn't send through smtp.gmail.com:587 (timed out).")

    monkeypatch.setattr(mail, "send", refuse)
    result = run.run(conn, MONDAY, say=lambda words: None)
    assert result.failures == ["Couldn't send through smtp.gmail.com:587 (timed out)."]
    assert alerts.recent(conn)[0]["outcome"] == "failed"
    monkeypatch.setattr(mail, "send", lambda message, settings: emails.append(message))
    assert run.run(conn, date(2026, 8, 11), say=lambda words: None).email == "sent" and len(emails) == 1
