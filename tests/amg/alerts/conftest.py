from __future__ import annotations

import alert_fixtures as af  # tests/ is on pytest's path
import pytest

from amg.alerts import ntfy


@pytest.fixture
def car(conn):
    return af.make_car(conn)


@pytest.fixture
def pushes(monkeypatch):
    """Pushes are set up, and every one sent is kept here instead of leaving the machine."""
    monkeypatch.setenv("AMG_NTFY_TOPIC", "amg-test")
    sent: list[ntfy.Push] = []
    monkeypatch.setattr(ntfy, "send", lambda push, settings: sent.append(push))
    return sent
