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
