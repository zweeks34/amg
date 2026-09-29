from __future__ import annotations

import io

from amg import auth, cli, db


def test_set_password_from_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("a long enough password\n"))
    assert cli.main(["set-password"]) == 0
    conn = db.connect()
    assert auth.check_password(conn, "a long enough password")
    conn.close()


def test_set_password_refuses_short_input(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert cli.main(["set-password"]) == 1
    assert "Nothing was changed" in capsys.readouterr().err


def test_migrate_reports_up_to_date_on_second_run(capsys):
    cli.main(["migrate"])
    cli.main(["migrate"])
    assert "up to date" in capsys.readouterr().out
