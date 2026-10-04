"""Where AMG keeps things, and the settings that come from the environment.

Everything here is a function read at call time rather than a module constant:
a test points AMG_DATA_DIR at a temporary directory and every later call sees
it. A path bound at import time — or as a default argument — is how a test ends
up writing into the real data/ directory.

The repo's .env is loaded once, without overriding anything already set, so a
variable exported in the shell or by systemd wins over the file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def data_dir() -> Path:
    """The runtime data directory — database and stored files. Created on demand."""
    path = Path(os.environ.get("AMG_DATA_DIR") or ROOT / "data")
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "amg.sqlite3"


def cookie_secure() -> bool:
    """Whether the session cookie is HTTPS-only.

    Off by default: inside the VPN the home lab serves plain HTTP, and a Secure
    cookie would never be sent back. Set AMG_COOKIE_SECURE=1 behind TLS.
    """
    return os.environ.get("AMG_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes"}


def base_url() -> str:
    """Where links in alerts point: the app as you reach it at home or on the VPN."""
    return (os.environ.get("AMG_BASE_URL") or "http://amg.home.arpa").strip().rstrip("/")


@dataclass(frozen=True)
class Ntfy:
    url: str        # the server, e.g. https://ntfy.sh
    topic: str
    token: str      # for a protected topic; empty for none


def ntfy() -> Ntfy | None:
    """Push settings, or None when no topic is set — no topic, no pushes."""
    topic = os.environ.get("AMG_NTFY_TOPIC", "").strip()
    if not topic:
        return None
    url = (os.environ.get("AMG_NTFY_URL") or "https://ntfy.sh").strip().rstrip("/")
    return Ntfy(url, topic, os.environ.get("AMG_NTFY_TOKEN", "").strip())


@dataclass(frozen=True)
class Smtp:
    host: str
    port: int
    user: str
    password: str
    to: str


def smtp() -> Smtp | None:
    """Email settings, or None unless both the user and the password are set.

    Gmail shows an app password in groups of four; the spaces aren't part of it.
    """
    user = os.environ.get("AMG_SMTP_USER", "").strip()
    password = os.environ.get("AMG_SMTP_PASSWORD", "").replace(" ", "").strip()
    if not (user and password):
        return None
    port = os.environ.get("AMG_SMTP_PORT", "").strip()
    return Smtp(
        host=(os.environ.get("AMG_SMTP_HOST") or "smtp.gmail.com").strip(),
        port=int(port) if port.isdigit() else 587,
        user=user,
        password=password,
        to=os.environ.get("AMG_EMAIL_TO", "").strip() or user,
    )
