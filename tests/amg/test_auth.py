from __future__ import annotations

import time

import pytest

from amg import auth
from amg.repo import settings


def test_password_hash_round_trip():
    stored = auth.hash_password("s3cret-enough")
    assert stored.startswith("scrypt$")
    assert auth.verify_password("s3cret-enough", stored)
    assert not auth.verify_password("s3cret-enougH", stored)


def test_hashes_are_salted():
    assert auth.hash_password("same password") != auth.hash_password("same password")


@pytest.mark.parametrize("stored", ["", "plain", "scrypt$1$2$3", "bcrypt$16384$8$1$AAAA$BBBB", "scrypt$x$8$1$AAAA$BBBB"])
def test_malformed_hashes_never_verify(stored):
    assert not auth.verify_password("anything", stored)


def test_short_passwords_are_refused(conn):
    with pytest.raises(ValueError):
        auth.set_password(conn, "short")
    assert not auth.password_is_set(conn)


def test_check_password(conn):
    assert not auth.check_password(conn, "anything at all")
    auth.set_password(conn, "correct horse battery")
    assert auth.check_password(conn, "correct horse battery")
    assert not auth.check_password(conn, "wrong horse battery")


def test_session_round_trip(conn):
    token = auth.issue_session(conn, now=1_000_000)
    assert auth.session_age(conn, token, now=1_000_060) == 60


@pytest.mark.parametrize("token", [None, "", "abc", "1.0", "x.0.sig", "1.0.deadbeef"])
def test_malformed_sessions_are_rejected(conn, token):
    assert auth.session_age(conn, token) is None


def test_tampered_session_is_rejected(conn):
    token = auth.issue_session(conn, now=1_000_000)
    issued, generation, signature = token.split(".")
    forged = f"{int(issued) + 86400}.{generation}.{signature}"
    assert auth.session_age(conn, forged, now=1_100_000) is None


def test_session_signed_with_another_secret_is_rejected(conn):
    token = auth.issue_session(conn)
    settings.put(conn, "session_secret", "00" * 32)
    assert auth.session_age(conn, token) is None


def test_expired_and_future_sessions_are_rejected(conn):
    now = time.time()
    old = auth.issue_session(conn, now=now - auth.SESSION_DAYS * 86400 - 1)
    future = auth.issue_session(conn, now=now + 3600)
    assert auth.session_age(conn, old, now=now) is None
    assert auth.session_age(conn, future, now=now) is None


def test_new_password_signs_out_existing_sessions(conn):
    auth.set_password(conn, "first password")
    token = auth.issue_session(conn)
    assert auth.session_age(conn, token) is not None
    auth.set_password(conn, "second password")
    assert auth.session_age(conn, token) is None


def test_refresh_only_after_a_day():
    assert not auth.needs_refresh(3600)
    assert auth.needs_refresh(auth.REFRESH_AFTER_SECONDS + 1)
