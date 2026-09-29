"""The login guard: every page but the login page needs a valid session.

A browser that isn't signed in is sent to /login with the page it wanted in
``next``. An htmx request can't follow a redirect into a full page, so it gets
a 401 with an ``HX-Redirect`` header and htmx navigates the whole window.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse, Response

from .. import auth, config, db

PUBLIC_PATHS = {"/login", "/healthz", "/favicon.ico"}
PUBLIC_PREFIXES = ("/static/",)


def is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def safe_next(target: str | None) -> str:
    """Where to go after signing in — only ever a path on this site."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=auth.SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=config.cookie_secure(),
    )


def _check(token: str | None) -> tuple[int | None, str | None]:
    """(session age, refreshed token or None) — run in a thread, it touches the database."""
    conn = db.connect()
    try:
        age = auth.session_age(conn, token)
        if age is not None and auth.needs_refresh(age):
            return age, auth.issue_session(conn)
        return age, None
    finally:
        conn.close()


async def require_login(request: Request, call_next) -> Response:
    if is_public(request.url.path):
        return await call_next(request)

    age, refreshed = await run_in_threadpool(_check, request.cookies.get(auth.SESSION_COOKIE))
    if age is None:
        if request.headers.get("HX-Request"):
            return Response(status_code=401, headers={"HX-Redirect": "/login"})
        wanted = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(wanted, safe='/')}", status_code=303)

    response = await call_next(request)
    if refreshed:
        set_session_cookie(response, refreshed)
    return response
