"""Shared fixtures. Every test gets its own data directory — none touches data/."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from amg import auth, db
from amg.ingest import recalls

PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    path = tmp_path / "data"
    monkeypatch.setenv("AMG_DATA_DIR", str(path))
    monkeypatch.setattr(auth, "FAILED_LOGIN_DELAY", 0)
    # Whatever .env says about alerts, no test sends a real push or email: a test that wants a channel sets it.
    for name in ("AMG_BASE_URL", "AMG_NTFY_TOPIC", "AMG_NTFY_URL", "AMG_NTFY_TOKEN", "AMG_SMTP_HOST", "AMG_SMTP_PORT",
                 "AMG_SMTP_USER", "AMG_SMTP_PASSWORD", "AMG_EMAIL_TO"):
        monkeypatch.delenv(name, raising=False)
    # Nor does any reach NHTSA: a test that wants recalls fakes the answer.
    monkeypatch.setattr(recalls, "_get", _offline)
    return path


def _offline(url):
    raise recalls.RecallLookupError("Tests don't reach NHTSA.")


@pytest.fixture
def password():
    return PASSWORD


@pytest.fixture
def conn(data_dir):
    connection = db.connect()
    db.migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def client(data_dir):
    from amg.app import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def signed_in(client, conn):
    auth.set_password(conn, PASSWORD)
    response = client.post("/login", data={"password": PASSWORD}, follow_redirects=False)
    assert response.status_code == 303
    return client
