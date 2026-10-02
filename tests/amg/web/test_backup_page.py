from __future__ import annotations

import io
import tempfile
import zipfile

import pymupdf

from amg.repo import documents, vehicles


def _store_a_receipt(conn):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), "OIL CHANGE")
        return documents.store(conn, doc.tobytes(), "oil.pdf")[0]


def test_the_backup_page_needs_a_login(client):
    response = client.get("/backup/download", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_the_page_says_what_a_backup_holds(signed_in, conn):
    vehicles.create(conn, vehicles.VehicleFields(name="Outback"))
    _store_a_receipt(conn)
    page = signed_in.get("/backup")
    assert page.status_code == 200
    assert "Download a backup" in page.text
    assert "amg restore" in page.text
    assert 'href="/backup"' in page.text  # linked from the footer


def test_download_is_a_zip_and_leaves_nothing_behind(signed_in, conn, tmp_path, monkeypatch):
    document = _store_a_receipt(conn)
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    full = signed_in.get("/backup/download")
    assert full.status_code == 200
    assert full.headers["content-type"] == "application/zip"
    assert 'filename="amg-backup-' in full.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(full.content)) as zf:
        assert {"amg.sqlite3", document["stored_as"]} <= set(zf.namelist())

    small = signed_in.get("/backup/download?files=0")
    assert "database-only.zip" in small.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(small.content)) as zf:
        assert document["stored_as"] not in zf.namelist()

    assert list(scratch.iterdir()) == []
