from __future__ import annotations

import pytest

from amg.web.templating import axis, dollars, miles, money


def test_empty_garage_shows_the_three_steps(signed_in):
    response = signed_in.get("/")
    assert response.status_code == 200
    assert "No cars yet" in response.text
    for step in ("Add a car", "Load its maintenance schedule", "Add service receipts"):
        assert step in response.text


def test_design_reference_renders_the_sample_chart(signed_in):
    response = signed_in.get("/design")
    assert response.status_code == 200
    assert 'class="ichart"' in response.text
    assert "Oil and filter at 40,000 mi: missed" in response.text
    assert "64,300 mi" in response.text


def test_static_assets_are_versioned(signed_in):
    html = signed_in.get("/").text
    assert "/static/app.css?v=" in html
    assert "/static/vendor/htmx.min.js?v=" in html


def test_healthz(client):
    assert client.get("/healthz").text == "ok"


@pytest.mark.parametrize(
    ("value", "span", "expected"),
    [(45_000, 90_000, "50.000"), (-5, 90_000, "0.000"), (100_000, 90_000, "100.000"), (1, 0, "0")],
)
def test_axis_is_clamped(value, span, expected):
    assert axis(value, span) == expected


def test_number_formats():
    assert miles(64300) == "64,300 mi"
    assert miles(None) == "—"
    assert dollars(118_049) == "$1,180"
    assert money(14_648) == "$146.48"
