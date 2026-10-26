"""Which alerts go out, and that each goes out once. The car is alert_fixtures'."""

from __future__ import annotations

from datetime import date

import alert_fixtures as af  # tests/ is on pytest's path

from amg.alerts import ntfy, run, watch
from amg.repo import alerts, vehicles
from amg.repo.schedules import ItemInput

JUNE_10, JULY_2 = af.JUNE_10, af.JULY_2


def _run(conn, day):
    return run.run(conn, day, say=lambda words: None)


def test_a_job_coming_due_is_pushed_once(conn, car, pushes):
    _run(conn, JUNE_10)
    assert [p.title for p in pushes] == ["Outback: REPLACE Oil and filter due soon"]   # what to do, first
    assert pushes[0].message == "by Jul 1" and pushes[0].priority == 3
    assert [row["title"] for row in alerts.recent(conn)] == ["REPLACE Oil and filter: by Jul 1"]   # as logged
    assert pushes[0].click == f"http://amg.home.arpa/vehicles/{car}"
    _run(conn, JUNE_10)
    _run(conn, date(2026, 6, 11))
    assert len(pushes) == 1


def test_due_soon_then_overdue_is_two_pushes(conn, car, pushes):
    _run(conn, JUNE_10)
    _run(conn, JULY_2)
    assert [p.title for p in pushes] == ["Outback: REPLACE Oil and filter due soon",
                                         "Outback: REPLACE Oil and filter overdue"]
    assert pushes[1].priority == 4 and pushes[1].tags == ("warning",)


def test_straight_to_overdue_gets_no_late_due_soon(conn, car, pushes):
    _run(conn, JULY_2)
    _run(conn, date(2026, 7, 3))
    assert [p.title for p in pushes] == ["Outback: REPLACE Oil and filter overdue"]
    assert watch.news([watch.Watched(car, "x", "due", "Oil", "", None)], {("x", "overdue")}) == []


def test_a_missed_round_rolls_on_without_a_second_push(conn, car, pushes):
    _run(conn, JULY_2)
    _run(conn, date(2027, 1, 3))                        # July's oil change missed; January's now overdue
    assert [p.title for p in pushes if "Oil" in p.title] == ["Outback: REPLACE Oil and filter overdue"]


def test_doing_the_job_starts_a_new_round(conn, car, pushes):
    _run(conn, JULY_2)
    af.oil_change(conn, car, date(2026, 7, 5))
    _run(conn, date(2026, 7, 6))
    _run(conn, date(2026, 12, 10))                      # next due 2027-01-05; the wipers went overdue in September
    assert [p.title for p in pushes] == ["Outback: REPLACE Oil and filter overdue", "Outback: 1 overdue, 1 due soon"]
    assert "REPLACE Oil and filter: by Jan 5, 2027 · ~$61" in pushes[1].message   # the $60 oil change, in December's money


def test_a_new_schedule_with_the_same_jobs_doesnt_alert_again(conn, car, pushes):
    _run(conn, JUNE_10)
    af.schedule(conn, car, [ItemInput("Engine oil & filter", "replace", ["oil_filter", "engine_oil"], interval_months=6),
                          af.CABIN])
    _run(conn, JUNE_10)
    assert len(pushes) == 1


def test_turning_alerts_on_takes_stock_without_sending(conn, car, pushes):
    alerts.switch(conn, car, False)
    alerts.switch(conn, car, True)
    assert watch.take_stock(conn, vehicles.get(conn, car), date(2026, 8, 10)) == 2   # oil overdue, wipers due
    _run(conn, date(2026, 8, 10))
    assert pushes == []
    _run(conn, date(2026, 9, 2))                        # the wipers go overdue: that's news
    assert [p.title for p in pushes] == ["Outback: REPLACE Wiper blades overdue"]


def test_a_car_with_alerts_off_sends_nothing(conn, car, pushes):
    alerts.switch(conn, car, False)
    _run(conn, JULY_2)
    assert pushes == []


def test_several_new_jobs_make_one_push(conn, car, pushes):
    _run(conn, date(2026, 8, 10))                       # oil overdue; wipers (Sep 1) due soon
    (push,) = pushes
    assert push.title == "Outback: 1 overdue, 1 due soon"
    assert push.message == "REPLACE Oil and filter: overdue since Jul 1\nREPLACE Wiper blades: by Sep 1"
    assert push.priority == 4


def test_a_failed_push_is_tried_again_next_run(conn, car, monkeypatch):
    monkeypatch.setenv("AMG_NTFY_TOPIC", "amg-test")

    def refuse(push, settings):
        raise ntfy.SendError("Couldn't reach ntfy.sh (offline).")

    monkeypatch.setattr(ntfy, "send", refuse)
    result = _run(conn, JUNE_10)
    assert not result.ok and result.failures == ["Couldn't reach ntfy.sh (offline)."]
    (row,) = alerts.recent(conn)
    assert (row["outcome"], row["error"]) == ("failed", "Couldn't reach ntfy.sh (offline).")

    sent: list = []
    monkeypatch.setattr(ntfy, "send", lambda push, settings: sent.append(push))
    assert _run(conn, date(2026, 6, 11)).ok and len(sent) == 1


def test_an_alert_another_run_is_sending_isnt_sent_twice(conn, car, pushes):
    state = watch.look(conn, vehicles.get(conn, car), JUNE_10)
    (job,) = state.jobs
    alerts.claim(conn, watch.CHANNEL, job.subject, job.level, car, job.line)   # a run that died mid-send
    _run(conn, JUNE_10)
    assert pushes == []
