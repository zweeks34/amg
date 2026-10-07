from __future__ import annotations

import sqlite3

import pytest

from amg import db


def _write(directory, name, sql):
    (directory / name).write_text(sql, encoding="utf-8")


def test_migrations_apply_in_order_and_record_versions(conn):
    rows = conn.execute("SELECT version, name FROM schema_version ORDER BY version").fetchall()
    assert [tuple(r) for r in rows][0] == (1, "0001_init")
    assert conn.execute("SELECT count(*) FROM settings").fetchone()[0] == 0


def test_migrate_is_idempotent(conn):
    assert db.migrate(conn) == []


def test_database_uses_wal_and_foreign_keys(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_failing_migration_leaves_database_untouched(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    _write(migrations, "0001_ok.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    _write(migrations, "0002_bad.sql", "CREATE TABLE b (id INTEGER PRIMARY KEY);\nINSERT INTO nowhere VALUES (1);")
    conn = db.connect(tmp_path / "t.sqlite3")

    with pytest.raises(sqlite3.OperationalError):
        db.migrate(conn, migrations)

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables.isdisjoint({"a", "b", "schema_version"})
    conn.close()


def test_statement_splitter_handles_semicolons_in_strings_comments_and_triggers(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    _write(
        migrations,
        "0001_tricky.sql",
        """
        -- a comment; with a semicolon
        CREATE TABLE t (id INTEGER PRIMARY KEY, note TEXT DEFAULT 'a;b');
        CREATE TABLE log (msg TEXT);
        CREATE TRIGGER t_ins AFTER INSERT ON t BEGIN
            INSERT INTO log (msg) VALUES ('inserted;');
        END;
        -- trailing comment
        """,
    )
    conn = db.connect(tmp_path / "t.sqlite3")
    db.migrate(conn, migrations)
    conn.execute("INSERT INTO t DEFAULT VALUES")
    assert conn.execute("SELECT note FROM t").fetchone()[0] == "a;b"
    assert conn.execute("SELECT msg FROM log").fetchone()[0] == "inserted;"
    conn.close()


def test_incomplete_statement_is_rejected(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    _write(migrations, "0001_cut.sql", "CREATE TABLE t (id INTEGER PRIMARY KEY)")
    conn = db.connect(tmp_path / "t.sqlite3")
    with pytest.raises(ValueError, match="incomplete"):
        db.migrate(conn, migrations)
    conn.close()


def test_duplicate_versions_are_rejected(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    _write(migrations, "0001_a.sql", "SELECT 1;")
    _write(migrations, "0001_b.sql", "SELECT 1;")
    with pytest.raises(RuntimeError, match="share version 1"):
        db.migrations(migrations)


def test_transaction_rolls_back_on_error(conn):
    with pytest.raises(RuntimeError):
        with db.transaction(conn):
            conn.execute("INSERT INTO settings (key, value, updated_at) VALUES ('k', 'v', 'now')")
            raise RuntimeError("boom")
    assert conn.execute("SELECT count(*) FROM settings").fetchone()[0] == 0
    assert not conn.in_transaction


def test_nested_transaction_rolls_back_only_the_inner_block(conn):
    with db.transaction(conn):
        conn.execute("INSERT INTO settings (key, value, updated_at) VALUES ('outer', 'v', 'now')")
        with pytest.raises(RuntimeError):
            with db.transaction(conn):
                conn.execute("INSERT INTO settings (key, value, updated_at) VALUES ('inner', 'v', 'now')")
                raise RuntimeError("boom")
    keys = [r[0] for r in conn.execute("SELECT key FROM settings")]
    assert keys == ["outer"]


# ---------- Migrations that change what's already there ----------


def _at(tmp_path, version: int) -> sqlite3.Connection:
    """A database migrated only as far as ``version``, to apply the later ones to."""
    older = tmp_path / "older"
    older.mkdir()
    for path in db.MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"):
        if int(path.name[:4]) <= version:
            _write(older, path.name, path.read_text(encoding="utf-8"))
    conn = db.connect(tmp_path / "t.sqlite3")
    db.migrate(conn, older)
    return conn


def test_washer_fluid_comes_right_after_wiper_blades(conn):
    from amg.repo import services

    codes = [row["code"] for row in services.list_types(conn)]
    assert codes[codes.index("wiper_blades") + 1] == "washer_fluid"
    fluid = next(row for row in services.list_types(conn) if row["code"] == "washer_fluid")
    assert (fluid["name"], fluid["category"], fluid["default_action"], fluid["is_custom"]) == (
        "Washer fluid", "Electrical", "replace", 0)


def test_washer_fluid_forgets_only_wording_learned_with_no_service(tmp_path):
    conn = _at(tmp_path, 9)
    learned = {
        "washer fluid": "[]",
        "top off windshield washer fluid": "[]",
        "wiper blades and fluid": '[{"code": "wiper_blades", "action": "replace"}]',
        "drain plug washer": "[]",
    }
    conn.executemany("INSERT INTO service_aliases (phrase, covers_json, updated_at) VALUES (?, ?, 'now')",
                     learned.items())
    db.migrate(conn)
    kept = {row[0] for row in conn.execute("SELECT phrase FROM service_aliases")}
    assert kept == {"wiper blades and fluid", "drain plug washer"}
    conn.close()


def test_washer_fluid_is_never_added_twice(tmp_path):
    from amg.repo import services

    conn = _at(tmp_path, 9)
    services.add_custom_type(conn, "washer fluid", "Electrical")
    db.migrate(conn)
    named = conn.execute("SELECT code FROM service_types WHERE name = 'Washer fluid' COLLATE NOCASE").fetchall()
    assert [row[0] for row in named] == ["custom_washer_fluid"]
    conn.close()
