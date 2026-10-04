from __future__ import annotations

from amg.repo import alerts, vehicles


def _car(conn, name="Outback"):
    return vehicles.create(conn, vehicles.VehicleFields(name=name))


def test_alerts_are_off_until_switched_on_and_archived_cars_send_none(conn):
    outback, forester = _car(conn), _car(conn, "Forester")
    assert alerts.cars_on(conn) == []
    alerts.switch(conn, outback, True)
    alerts.switch(conn, forester, True)
    vehicles.archive(conn, forester)
    assert [car["name"] for car in alerts.cars_on(conn)] == ["Outback"]
    alerts.switch(conn, outback, False)
    assert alerts.cars_on(conn) == []


def test_an_alert_can_be_claimed_once(conn):
    car = _car(conn)
    first = alerts.claim(conn, "ntfy", "1:engine_oil:replace:new", "due", car, "Oil due")
    assert first is not None
    assert alerts.claim(conn, "ntfy", "1:engine_oil:replace:new", "due", car, "Oil due") is None   # going out
    alerts.mark(conn, first, "sent")
    assert alerts.claim(conn, "ntfy", "1:engine_oil:replace:new", "due", car, "Oil due") is None   # gone
    assert alerts.claim(conn, "ntfy", "1:engine_oil:replace:new", "overdue", car, "Oil overdue") is not None
    assert alerts.claim(conn, "email", "1:engine_oil:replace:new", "due", car, "Oil due") is not None
    assert alerts.logged(conn, "ntfy") == {("1:engine_oil:replace:new", "due"), ("1:engine_oil:replace:new", "overdue")}


def test_a_failed_send_is_given_back_for_the_next_run(conn):
    car = _car(conn)
    alert_id = alerts.claim(conn, "ntfy", "s", "due", car, "Oil due")
    alerts.mark(conn, alert_id, "failed", "Couldn't reach ntfy.sh")
    assert alerts.logged(conn, "ntfy") == set()
    assert alerts.claim(conn, "ntfy", "s", "due", car, "Oil due again") == alert_id
    (row,) = alerts.recent(conn)
    assert (row["outcome"], row["error"], row["title"], row["vehicle_name"]) == ("sending", "", "Oil due again", "Outback")


def test_held_back_alerts_count_as_sent_but_arent_news(conn):
    car = _car(conn)
    alerts.known(conn, "ntfy", "s", "overdue", car, "Oil overdue")
    alerts.known(conn, "ntfy", "s", "overdue", car, "Oil overdue")       # turned on twice
    assert alerts.logged(conn, "ntfy") == {("s", "overdue")}
    assert alerts.claim(conn, "ntfy", "s", "overdue", car, "Oil overdue") is None
    assert alerts.recent(conn) == []


def test_the_last_run_is_remembered(conn):
    assert alerts.last_run(conn) is None
    alerts.set_last_run(conn, "2026-10-05T08:00", "1 push, no email due", True)
    assert alerts.last_run(conn) == {"at": "2026-10-05T08:00", "summary": "1 push, no email due", "ok": True}


def test_a_deleted_car_takes_its_alerts_with_it(conn):
    car = _car(conn)
    alerts.claim(conn, "ntfy", "s", "due", car, "Oil due")
    conn.execute("DELETE FROM vehicles WHERE id = ?", (car,))
    assert conn.execute("SELECT count(*) FROM alert_log").fetchone()[0] == 0
