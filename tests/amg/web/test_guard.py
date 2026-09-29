from __future__ import annotations

import time

import pytest

from amg import auth
from amg.web.guard import safe_next


def test_pages_redirect_to_login_when_signed_out(client):
    response = client.get("/design?x=1", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/design%3Fx%3D1"


def test_htmx_requests_get_401_with_hx_redirect(client):
    response = client.get("/", headers={"HX-Request": "true"}, follow_redirects=False)
    assert response.status_code == 401
    assert response.headers["HX-Redirect"] == "/login"


@pytest.mark.parametrize("path", ["/login", "/healthz", "/static/app.css"])
def test_public_paths_need_no_session(client, path):
    assert client.get(path, follow_redirects=False).status_code == 200


def test_login_page_explains_setup_when_no_password(client):
    response = client.get("/login")
    assert "Set a password first" in response.text
    assert "python -m amg.cli set-password" in response.text


def test_wrong_password_is_refused(client, conn, password):
    auth.set_password(conn, password)
    response = client.post("/login", data={"password": "not it at all"}, follow_redirects=False)
    assert response.status_code == 401
    assert "Wrong password." in response.text
    assert auth.SESSION_COOKIE not in response.cookies


def test_sign_in_goes_to_next_and_sets_an_httponly_cookie(client, conn, password):
    auth.set_password(conn, password)
    response = client.post("/login", data={"password": password, "next": "/design"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/design"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert client.get("/design", follow_redirects=False).status_code == 200


def test_signed_in_user_visiting_login_is_sent_on(signed_in):
    response = signed_in.get("/login?next=/design", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/design"


def test_sign_out_ends_the_session(signed_in):
    response = signed_in.post("/logout", follow_redirects=False)
    assert response.headers["location"] == "/login"
    assert signed_in.get("/", follow_redirects=False).status_code == 303


def test_stale_session_is_refreshed(signed_in, conn):
    stale = auth.issue_session(conn, now=time.time() - auth.REFRESH_AFTER_SECONDS - 60)
    signed_in.cookies.set(auth.SESSION_COOKIE, stale)
    response = signed_in.get("/", follow_redirects=False)
    assert response.status_code == 200
    assert auth.SESSION_COOKIE in response.cookies
    assert response.cookies[auth.SESSION_COOKIE] != stale


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("/design", "/design"),
        ("/a?b=c", "/a?b=c"),
        (None, "/"),
        ("", "/"),
        ("https://evil.example", "/"),
        ("//evil.example", "/"),
        ("/\\evil.example", "/"),
    ],
)
def test_next_is_always_a_local_path(target, expected):
    assert safe_next(target) == expected
