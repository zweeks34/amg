"""The single-password login.

AMG has one user, so there are no accounts: one password, stored as a scrypt
hash in ``settings``, and a signed session cookie. The cookie carries no data
worth stealing — just when it was issued and which *session generation* it
belongs to, signed with a secret generated on first use and kept in the
database. Setting a new password bumps the generation, which signs every
existing cookie out at once.

Sessions last SESSION_DAYS and are re-issued on use (see ``needs_refresh``), so
a phone that opens AMG every few weeks never sees the login page again.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
import time

from .db import transaction
from .repo import settings

SESSION_COOKIE = "amg_session"
SESSION_DAYS = 90
REFRESH_AFTER_SECONDS = 24 * 3600
MIN_PASSWORD_LENGTH = 8

# How long a wrong password makes the login page wait. Tests set it to zero.
FAILED_LOGIN_DELAY = 1.0

# scrypt cost: 2**15 with r=8 needs 32 MiB, so maxmem is raised past Python's
# 32 MiB default. About a tenth of a second per check.
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = _scrypt(password, _unb64(salt), int(n), int(r), int(p))
        return hmac.compare_digest(candidate, _unb64(digest))
    except (ValueError, TypeError):
        return False


def password_is_set(conn: sqlite3.Connection) -> bool:
    return settings.get(conn, "password_hash") is not None


def set_password(conn: sqlite3.Connection, password: str) -> None:
    """Store a new password and sign every existing session out."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    with transaction(conn):
        settings.put(conn, "password_hash", hash_password(password))
        generation = int(settings.get(conn, "session_generation", "0")) + 1
        settings.put(conn, "session_generation", str(generation))


def check_password(conn: sqlite3.Connection, password: str) -> bool:
    stored = settings.get(conn, "password_hash")
    return stored is not None and verify_password(password, stored)


def issue_session(conn: sqlite3.Connection, now: float | None = None) -> str:
    issued = int(time.time() if now is None else now)
    payload = f"{issued}.{_generation(conn)}"
    return f"{payload}.{_sign(conn, payload)}"


def session_age(conn: sqlite3.Connection, token: str | None, now: float | None = None) -> int | None:
    """Seconds since a valid token was issued, or None if the token is not valid.

    Invalid means: malformed, signed with another secret, from an older session
    generation, issued in the future, or older than SESSION_DAYS.
    """
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3 or not parts[0].isdigit():
        return None
    issued, generation, signature = parts
    if not hmac.compare_digest(signature, _sign(conn, f"{issued}.{generation}")):
        return None
    if generation != _generation(conn):
        return None
    age = int(time.time() if now is None else now) - int(issued)
    if age < 0 or age > SESSION_DAYS * 86400:
        return None
    return age


def needs_refresh(age: int) -> bool:
    return age > REFRESH_AFTER_SECONDS


def _generation(conn: sqlite3.Connection) -> str:
    return settings.get(conn, "session_generation", "0")  # type: ignore[return-value]


def _sign(conn: sqlite3.Connection, payload: str) -> str:
    secret = settings.get_or_create(conn, "session_secret", lambda: secrets.token_hex(32))
    return hmac.new(bytes.fromhex(secret), payload.encode(), hashlib.sha256).hexdigest()


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=_SCRYPT_MAXMEM, dklen=32)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
