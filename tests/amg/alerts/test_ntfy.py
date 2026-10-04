from __future__ import annotations

import json
import urllib.error

import pytest

from amg import config
from amg.alerts import ntfy

PUSH = ntfy.Push("Outback: Oil and filter overdue", "1,200 mi overdue · ~$85", 4, ("warning",),
                 "http://amg.home.arpa/vehicles/1")


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b"{}"


@pytest.fixture
def sent(monkeypatch):
    requests = []

    def urlopen(request, timeout):
        requests.append((request, timeout))
        return _Response()

    monkeypatch.setattr(ntfy.urllib.request, "urlopen", urlopen)
    return requests


def test_a_push_is_published_as_json(sent):
    ntfy.send(PUSH, config.Ntfy("https://ntfy.sh", "amg-topic", ""))
    ((request, timeout),) = sent
    assert request.full_url == "https://ntfy.sh" and request.get_method() == "POST" and timeout == 15
    assert json.loads(request.data) == {
        "topic": "amg-topic", "title": "Outback: Oil and filter overdue", "message": "1,200 mi overdue · ~$85",
        "priority": 4, "tags": ["warning"], "click": "http://amg.home.arpa/vehicles/1"}
    assert request.get_header("Authorization") is None


def test_a_token_goes_as_a_bearer(sent):
    ntfy.send(PUSH, config.Ntfy("https://push.example", "amg", "tk_secret"))
    assert sent[0][0].get_header("Authorization") == "Bearer tk_secret"


@pytest.mark.parametrize("error, words", [
    (urllib.error.HTTPError("https://ntfy.sh", 403, "Forbidden", {}, None), "the topic needs a token"),
    (urllib.error.HTTPError("https://ntfy.sh", 429, "Too Many Requests", {}, None), "(429 Too Many Requests)"),
    (urllib.error.URLError("Name or service not known"), "Couldn't reach ntfy.sh (Name or service not known)"),
])
def test_a_push_that_doesnt_go_says_why(monkeypatch, error, words):
    def urlopen(request, timeout):
        raise error

    monkeypatch.setattr(ntfy.urllib.request, "urlopen", urlopen)
    with pytest.raises(ntfy.SendError, match=words.replace("(", r"\(").replace(")", r"\)")):
        ntfy.send(PUSH, config.Ntfy("https://ntfy.sh", "amg", ""))


def test_settings_come_from_the_environment(monkeypatch):
    assert config.ntfy() is None
    monkeypatch.setenv("AMG_NTFY_TOPIC", " amg-x ")
    monkeypatch.setenv("AMG_NTFY_URL", "https://push.example/")
    assert config.ntfy() == config.Ntfy("https://push.example", "amg-x", "")
