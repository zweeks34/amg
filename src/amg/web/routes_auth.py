"""Sign in and sign out."""

from __future__ import annotations

import sqlite3
import time

from fastapi import APIRouter, Depends, Form, Request
from starlette.responses import RedirectResponse, Response

from .. import auth
from .deps import get_conn
from .guard import safe_next, set_session_cookie
from .templating import render

router = APIRouter()


@router.get("/login")
def login_page(request: Request, next: str = "/", conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    if auth.session_age(conn, request.cookies.get(auth.SESSION_COOKIE)) is not None:
        return RedirectResponse(safe_next(next), status_code=303)
    return render(request, "login.html", next=safe_next(next), password_set=auth.password_is_set(conn))


@router.post("/login")
def login(
    request: Request,
    password: str = Form(""),
    next: str = Form("/"),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Response:
    if not auth.check_password(conn, password):
        time.sleep(auth.FAILED_LOGIN_DELAY)
        return render(
            request,
            "login.html",
            status_code=401,
            next=safe_next(next),
            password_set=auth.password_is_set(conn),
            error="Wrong password.",
        )
    response = RedirectResponse(safe_next(next), status_code=303)
    set_session_cookie(response, auth.issue_session(conn))
    return response


@router.post("/logout")
def logout() -> Response:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.SESSION_COOKIE)
    return response
