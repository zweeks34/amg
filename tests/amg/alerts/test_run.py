"""The daily run as the timer and `amg alerts` start it."""

from __future__ import annotations

from datetime import date

import pytest

from amg import cli
from amg.alerts import ntfy, run
from amg.repo import alerts

MONDAY = date(2026, 8, 10)   # oil and filter overdue, wiper blades due soon


class _Monday(date):
    @classmethod
    def today(cls):
        return MONDAY


@pytest.fixture
def on_monday(monkeypatch):
    monkeypatch.setattr(run, "date", _Monday)


def test_a_dry_run_says_what_would_go_and_records_nothing(conn, car, capsys):
    said: list[str] = []
    result = run.run(conn, MONDAY, dry_run=True, say=said.append)
    assert said[0] == "Pushes aren't set up (AMG_NTFY_TOPIC is empty): showing what they would say."
    assert said[1] == ("Would push: Outback: 1 overdue, 1 due soon\n"
                       "  REPLACE Oil and filter: overdue since Jul 1\n  REPLACE Wiper blades: by Sep 1")
    assert said[2].startswith("Would email (email not set up):\nAMG: 1 overdue, 1 due soon\n")
    assert result.email == "would send"
    assert conn.execute("SELECT count(*) FROM alert_log").fetchone()[0] == 0 and alerts.last_run(conn) is None


def test_a_channel_that_isnt_set_up_is_skipped_and_said(conn, car):
    said: list[str] = []
    result = run.run(conn, MONDAY, say=said.append)
    assert said == ["Pushes aren't set up (AMG_NTFY_TOPIC is empty).",
                    "The weekly email isn't set up (AMG_SMTP_USER and AMG_SMTP_PASSWORD)."]
    assert result.ok and result.summary() == "nothing new to push; email not set up"
    assert alerts.logged(conn, "ntfy") == set()          # nothing claimed: it all goes once it's set up


def test_no_cars_on_says_how_to_turn_them_on(conn):
    said: list[str] = []
    run.run(conn, MONDAY, say=said.append)
    assert said == ["No car has alerts turned on, an inspection or registration date, an open recall or a warranty "
                    "ending. Turn alerts on from the Alerts page, or add the dates on a car's page."]
    assert alerts.last_run(conn)["summary"] == "nothing new to push; no cars on"


def test_the_run_records_itself_and_exits_1_when_a_send_fails(conn, car, on_monday, monkeypatch, capsys):
    monkeypatch.setenv("AMG_NTFY_TOPIC", "amg-test")

    def refuse(push, settings):
        raise ntfy.SendError("Couldn't reach ntfy.sh (offline).")

    monkeypatch.setattr(ntfy, "send", refuse)
    assert run.main([]) == 1
    last = alerts.last_run(conn)
    assert not last["ok"] and "failed: Couldn't reach ntfy.sh (offline)." in last["summary"]
    assert "Push for Outback failed" in capsys.readouterr().out

    monkeypatch.setattr(ntfy, "send", lambda push, settings: None)
    assert run.main([]) == 0
    assert alerts.last_run(conn)["summary"] == "1 push; email not set up"


def test_amg_alerts_runs_it(conn, car, on_monday, capsys):
    assert cli.main(["alerts", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Would push: Outback: 1 overdue, 1 due soon" in out and out.rstrip().endswith("Dry run: 1 push; weekly email would go")
