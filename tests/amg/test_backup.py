from __future__ import annotations

import shutil
import sqlite3
import zipfile

import pymupdf
import pytest

from amg import backup, config, db
from amg.repo import documents, vehicles


def _pdf(text: str) -> bytes:
    with pymupdf.open() as doc:
        doc.new_page(width=612, height=792).insert_text((72, 72), text)
        return doc.tobytes()


def _garage(conn, car="Outback", receipts=("OIL CHANGE", "TIRE ROTATION")) -> list[str]:
    """A car and some stored receipts; returns where the files were stored."""
    vehicles.create(conn, vehicles.VehicleFields(name=car, make="Subaru", model="Outback"))
    return [documents.store(conn, _pdf(text), f"{text}.pdf")[0]["stored_as"] for text in receipts]


def _move_to(monkeypatch, tmp_path, name="restored"):
    """Point AMG at a second, empty data directory, as a fresh server would be."""
    path = tmp_path / name
    monkeypatch.setenv("AMG_DATA_DIR", str(path))
    return path


def _car_names() -> list[str]:
    conn = db.connect()
    try:
        return [row["name"] for row in conn.execute("SELECT name FROM vehicles ORDER BY id")]
    finally:
        conn.close()


# ---------- Backing up ----------


def test_backup_holds_the_database_the_stored_files_and_a_readme(conn, tmp_path):
    stored = _garage(conn)
    written = backup.write(tmp_path / "out.zip")

    with zipfile.ZipFile(written.path) as zf:
        assert set(zf.namelist()) == {backup.DATABASE, backup.README, *stored}
        assert "amg restore" in zf.read(backup.README).decode()
        zf.extract(backup.DATABASE, tmp_path / "x")
    copy = sqlite3.connect(tmp_path / "x" / backup.DATABASE)
    try:
        assert copy.execute("SELECT name FROM vehicles").fetchone()[0] == "Outback"
        assert copy.execute("PRAGMA journal_mode").fetchone()[0] == "delete"  # one file, not three
    finally:
        copy.close()
    assert written.counts == {"cars": 1, "services": 0, "files": 2}
    assert written.files == 2 and not written.missing


def test_a_database_only_backup_leaves_the_files_out(conn, tmp_path):
    _garage(conn)
    written = backup.write(tmp_path / "small.zip", include_files=False)
    with zipfile.ZipFile(written.path) as zf:
        assert set(zf.namelist()) == {backup.DATABASE, backup.README}
        assert "NOT INCLUDED" in zf.read(backup.README).decode()


def test_a_file_already_missing_is_reported_rather_than_fatal(conn, data_dir, tmp_path):
    stored = _garage(conn)
    (data_dir / stored[0]).unlink()
    written = backup.write(tmp_path / "out.zip")
    assert written.missing == [stored[0]] and written.files == 1


def test_there_is_nothing_to_back_up_before_the_database_exists(tmp_path):
    with pytest.raises(backup.BackupError):
        backup.write(tmp_path / "out.zip")
    assert not (tmp_path / "out.zip").exists()


def test_summary_counts_what_a_backup_would_hold(conn, data_dir):
    stored = _garage(conn)
    summary = backup.summary(conn)
    assert summary.counts == {"cars": 1, "services": 0, "files": 2}
    assert summary.files_bytes == sum((data_dir / name).stat().st_size for name in stored)
    assert summary.database_bytes > 0


@pytest.mark.parametrize("count, label", [
    (0, "0 bytes"), (900, "900 bytes"), (2048, "2.0 KB"), (5 * 1024**2, "5.0 MB"),
    (250 * 1024**2, "250 MB"), (3 * 1024**3, "3.0 GB"),
])
def test_size_label(count, label):
    assert backup.size_label(count) == label


# ---------- Restoring ----------


def test_a_backup_restores_into_an_empty_data_directory(conn, monkeypatch, tmp_path):
    stored = _garage(conn)
    zipped = backup.write(tmp_path / "out.zip").path
    fresh = _move_to(monkeypatch, tmp_path)

    restored = backup.restore(zipped)

    assert restored.counts == {"cars": 1, "services": 0, "files": 2}
    assert restored.files_written == 2 and restored.replaced is None
    assert restored.migrated == [] and restored.missing == []
    assert all((fresh / name).read_bytes() for name in stored)
    assert _car_names() == ["Outback"]


def test_restore_wont_overwrite_a_database_unless_asked(conn, monkeypatch, tmp_path):
    _garage(conn)
    zipped = backup.write(tmp_path / "out.zip").path
    _move_to(monkeypatch, tmp_path)
    here = db.connect()
    db.migrate(here)
    vehicles.create(here, vehicles.VehicleFields(name="Already here"))
    here.close()

    with pytest.raises(backup.RestoreError, match="--replace"):
        backup.restore(zipped)
    assert _car_names() == ["Already here"]


def test_restore_with_replace_moves_the_old_database_aside(conn, monkeypatch, tmp_path):
    _garage(conn)
    zipped = backup.write(tmp_path / "out.zip").path
    _move_to(monkeypatch, tmp_path)
    here = db.connect()
    db.migrate(here)
    vehicles.create(here, vehicles.VehicleFields(name="Already here"))
    here.close()

    restored = backup.restore(zipped, replace=True)

    assert _car_names() == ["Outback"]
    kept = sqlite3.connect(restored.replaced / backup.DATABASE)
    try:
        assert kept.execute("SELECT name FROM vehicles").fetchone()[0] == "Already here"
    finally:
        kept.close()


def test_an_older_backup_is_brought_up_to_date(data_dir, monkeypatch, tmp_path):
    early = tmp_path / "early-migrations"
    early.mkdir()
    for path in sorted(db.MIGRATIONS_DIR.glob("000[12]_*.sql")):
        shutil.copy(path, early)
    old = db.connect()
    db.migrate(old, early)
    old.close()
    zipped = backup.write(tmp_path / "old.zip").path
    _move_to(monkeypatch, tmp_path)

    restored = backup.restore(zipped)

    assert restored.migrated == [version for version, _, _ in db.migrations()][2:]


def test_a_database_only_backup_restored_elsewhere_reports_the_missing_scans(conn, monkeypatch, tmp_path):
    stored = _garage(conn)
    zipped = backup.write(tmp_path / "small.zip", include_files=False).path
    _move_to(monkeypatch, tmp_path)
    assert backup.restore(zipped).missing == stored


def _zip(path, entries: dict[str, bytes]):
    with zipfile.ZipFile(path, "w") as zf:
        for name, body in entries.items():
            zf.writestr(name, body)
    return path


def test_a_zip_with_unexpected_entries_is_refused_untouched(conn, tmp_path, monkeypatch):
    with zipfile.ZipFile(backup.write(tmp_path / "good.zip").path) as good:
        database = good.read(backup.DATABASE)
    sneaky = _zip(tmp_path / "sneaky.zip", {backup.DATABASE: database, "../evil.txt": b"x"})
    fresh = _move_to(monkeypatch, tmp_path)

    with pytest.raises(backup.RestoreError, match="evil"):
        backup.restore(sneaky)
    assert not (tmp_path / "evil.txt").exists()
    assert not config.db_path().exists()
    assert list(fresh.iterdir()) == []


def test_a_damaged_database_is_refused_and_cleaned_up(tmp_path, data_dir):
    broken = _zip(tmp_path / "broken.zip", {backup.DATABASE: b"not a database at all" * 100})
    with pytest.raises(backup.RestoreError, match="can't be read"):
        backup.restore(broken)
    assert list(data_dir.iterdir()) == []


def test_a_backup_from_a_newer_amg_is_refused(conn, tmp_path, monkeypatch):
    conn.execute("INSERT INTO schema_version (version, name, applied_at) VALUES (999, '0999_future', 'now')")
    zipped = backup.write(tmp_path / "future.zip").path
    _move_to(monkeypatch, tmp_path)
    with pytest.raises(backup.RestoreError, match="newer AMG"):
        backup.restore(zipped)


def test_a_file_that_isnt_a_zip_is_refused(tmp_path):
    not_zip = tmp_path / "notes.zip"
    not_zip.write_text("hello")
    with pytest.raises(backup.RestoreError, match="isn't a zip"):
        backup.restore(not_zip)
    with pytest.raises(backup.RestoreError):
        backup.restore(tmp_path / "nowhere.zip")
