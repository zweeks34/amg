from __future__ import annotations

import io
from types import SimpleNamespace

from amg import auth, cli, db
from amg.repo import vehicles


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


def test_backup_and_restore_round_trip(conn, tmp_path, monkeypatch, capsys):
    vehicles.create(conn, vehicles.VehicleFields(name="Outback"))
    out = tmp_path / "zips"
    out.mkdir()
    assert cli.main(["backup", "--out", str(out)]) == 0
    [zipped] = out.glob("amg-backup-*.zip")
    assert "1 car(s)" in capsys.readouterr().out

    monkeypatch.setenv("AMG_DATA_DIR", str(tmp_path / "fresh"))
    assert cli.main(["restore", str(zipped)]) == 0
    assert "Restored 1 car(s)" in capsys.readouterr().out
    restored = db.connect()
    assert restored.execute("SELECT name FROM vehicles").fetchone()[0] == "Outback"
    restored.close()


def test_backup_goes_to_the_backups_folder_by_default(conn, data_dir):
    assert cli.main(["backup", "--no-files"]) == 0
    [zipped] = (data_dir / "backups").glob("amg-backup-*-database-only.zip")
    assert zipped.stat().st_size > 0


def test_restore_over_a_database_without_replace_changes_nothing(conn, tmp_path, capsys):
    assert cli.main(["backup", "--out", str(tmp_path / "b.zip")]) == 0
    assert cli.main(["restore", str(tmp_path / "b.zip")]) == 1
    assert "Nothing was changed" in capsys.readouterr().err


def test_root_is_turned_away_from_the_app_users_data(monkeypatch, capsys):
    monkeypatch.setattr(cli, "os", SimpleNamespace(geteuid=lambda: 0))
    monkeypatch.setattr(cli.config, "data_dir", lambda: SimpleNamespace(stat=lambda: SimpleNamespace(st_uid=999)))
    assert cli.main(["backup"]) == 1
    assert "`amg` command" in capsys.readouterr().err


def test_root_on_its_own_data_and_other_users_are_let_through(monkeypatch):
    monkeypatch.setattr(cli.config, "data_dir", lambda: SimpleNamespace(stat=lambda: SimpleNamespace(st_uid=0)))
    monkeypatch.setattr(cli, "os", SimpleNamespace(geteuid=lambda: 0))
    assert cli._wrong_user() is None
    monkeypatch.setattr(cli, "os", SimpleNamespace(geteuid=lambda: 1000))
    assert cli._wrong_user() is None
