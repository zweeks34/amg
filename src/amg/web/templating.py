"""The Jinja2 environment and a render helper every route uses."""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from ..backup import size_label
from ..repo.documents import fingerprint

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
    """Whole dollars, for estimates and budgets: 118000 → $1,180; a credit, -$20."""
    return "—" if cents is None else f"{'-' if cents < 0 else ''}${round(abs(cents) / 100):,}"


def money(cents: int | None) -> str:
    """Dollars and cents, for what was actually paid: 14648 → $146.48; a credit, -$20.00."""
    return "—" if cents is None else f"{'-' if cents < 0 else ''}${abs(cents) / 100:,.2f}"


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

# What a schedule job does, by the manual's own letters: the schedule page's
# stamps and their key, and next up.
ACTION_WORDS = {"replace": "Replace", "inspect": "Inspect", "perform": "Perform"}


def who(event) -> str:
    """Who did a service, as its title: the shop, you, or nobody on paper."""
    if event["shop"]:
        return event["shop"]
    return "Done, no receipt" if event["source"] == "attested" else "Your own work"


def page_url(document_id: int, sha256: str, page: int, full: bool = False, thumb: bool = False) -> str:
    """A scan page's URL. It names the file's content, so the browser may keep the image for good."""
    size = "&size=full" if full else "&size=thumb" if thumb else ""
    return f"/documents/{document_id}/pages/{page}?v={fingerprint(sha256)}{size}"


def file_url(document_id: int, sha256: str) -> str:
    return f"/documents/{document_id}/file?v={fingerprint(sha256)}"


# The thumbnail is 480px on its long edge; the largest avatar is 90px, 180 device pixels on a sharp screen. Zoomed
# in further than this, the avatar uses the larger rendering so the photo stays sharp.
AVATAR_THUMB_ZOOM = 2.5


def avatar_url(car) -> str | None:
    """A car's photo, for its avatar: the thumbnail, or the larger rendering once it's zoomed past
    AVATAR_THUMB_ZOOM. None when it has none (or the row didn't bring its hash)."""
    keys = car.keys()
    if "photo_sha256" not in keys or not car["photo_document_id"] or not car["photo_sha256"]:
        return None
    sharp = "photo_zoom" in keys and car["photo_zoom"] > AVATAR_THUMB_ZOOM
    return page_url(car["photo_document_id"], car["photo_sha256"], 1, thumb=not sharp)


def frame_style(car) -> str:
    """How a car's photo sits in its avatar, as the CSS its image carries: '--z: 1.5; --dx: -10%; --dy: 5%'."""
    keys = car.keys()

    def value(key: str, default: float) -> float:
        return default if key not in keys or car[key] is None else float(car[key])

    return (f"--z: {round(value('photo_zoom', 1), 2):g}; --dx: {round(value('photo_x', 0), 1):g}%;"
            f" --dy: {round(value('photo_y', 0), 1):g}%")


def initial(name: str) -> str:
    """The first letter or digit of a car's name, for its avatar when it has no photo."""
    return next((char.upper() for char in name or "" if char.isalnum()), "")


# Where a car's schedule came from, as a sentence finishes it: "28 items, from …".
SCHEDULE_ORIGINS = {
    "manual": "your owner's manual",
    "claude": "Claude's draft",
    "template": "AMG's generic template",
    "copy": "another car's schedule",
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


def fill_word() -> str:
    """The masthead's way to the fill-up form: Charge when every car in the garage is electric."""
    from .. import db
    from ..repo import vehicles

    conn = db.connect()
    try:
        return "Charge" if vehicles.powertrains(conn) == {"ev"} else "Fill-up"
    finally:
        conn.close()


templates.env.globals["asset"] = asset
templates.env.globals["receipts_to_check"] = receipts_to_check
templates.env.globals["fill_word"] = fill_word
templates.env.globals["axis"] = axis
templates.env.globals["status_words"] = STATUS_WORDS
templates.env.globals["action_words"] = ACTION_WORDS
templates.env.globals["origin_words"] = SCHEDULE_ORIGINS
templates.env.globals["page_url"] = page_url
templates.env.globals["who"] = who
templates.env.globals["file_url"] = file_url
templates.env.globals["avatar_url"] = avatar_url
templates.env.globals["frame_style"] = frame_style
templates.env.globals["initial"] = initial
templates.env.filters["miles"] = miles
templates.env.filters["dollars"] = dollars
templates.env.filters["money"] = money
templates.env.filters["filesize"] = size_label


def render(request: Request, name: str, status_code: int = 200, **context) -> Response:
    return templates.TemplateResponse(request, name, context, status_code=status_code)
