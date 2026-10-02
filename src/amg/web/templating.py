"""The Jinja2 environment and a render helper every route uses."""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from ..backup import size_label

HERE = Path(__file__).parent
STATIC_DIR = HERE / "static"

templates = Jinja2Templates(directory=HERE / "templates")


def asset(path: str) -> str:
    """URL for a static file, versioned by its modification time.

    After a deploy the browser fetches the new app.css instead of trusting a
    cached copy; between deploys the URL is stable and stays cached.
    """
    try:
        version = int((STATIC_DIR / path).stat().st_mtime)
    except OSError:
        return f"/static/{path}"
    return f"/static/{path}?v={version}"


def miles(value: int | None) -> str:
    return "—" if value is None else f"{value:,} mi"


def dollars(cents: int | None) -> str:
    """Whole dollars, for estimates and budgets: 118000 → $1,180."""
    return "—" if cents is None else f"${round(cents / 100):,}"


def money(cents: int | None) -> str:
    """Dollars and cents, for what was actually paid: 14648 → $146.48."""
    return "—" if cents is None else f"${cents / 100:,.2f}"


def axis(value: float, span: float) -> str:
    """A position along a mileage axis as a unitless 0–100, clamped.

    Unitless so CSS can use it both as a position, ``calc(var(--p) * 1%)``, and
    as a delay, ``calc(var(--p) * 9ms)`` — marks appear as the line reaches them.
    """
    if span <= 0:
        return "0"
    return f"{max(0.0, min(100.0, value / span * 100)):.3f}"


# What each status is called wherever a person reads it — chart labels, the
# legend, the next-up list — so the words cannot drift apart between pages.
STATUS_WORDS = {
    "done": "Done",
    "gap": "Missed",
    "overdue": "Overdue",
    "due": "Due soon",
    "later": "Later",
}

def receipts_to_check() -> int:
    """For the nav badge: receipts read and waiting for you."""
    from .. import db
    from ..repo import receipts

    conn = db.connect()
    try:
        return receipts.count_to_check(conn)
    finally:
        conn.close()


templates.env.globals["asset"] = asset
templates.env.globals["receipts_to_check"] = receipts_to_check
templates.env.globals["axis"] = axis
templates.env.globals["status_words"] = STATUS_WORDS
templates.env.filters["miles"] = miles
templates.env.filters["dollars"] = dollars
templates.env.filters["money"] = money
templates.env.filters["filesize"] = size_label


def render(request: Request, name: str, status_code: int = 200, **context) -> Response:
    return templates.TemplateResponse(request, name, context, status_code=status_code)
