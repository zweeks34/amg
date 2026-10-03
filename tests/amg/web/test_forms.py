from __future__ import annotations

from datetime import date, timedelta

import pytest

from amg.web import forms


@pytest.mark.parametrize(("raw", "expected"), [("32,610", 32610), ("32610 mi", 32610), ("32 610", 32610), ("", None)])
def test_miles(raw, expected):
    assert forms.miles(raw) == expected


@pytest.mark.parametrize("raw", ["32.5", "abc", "9999999"])
def test_bad_miles(raw):
    with pytest.raises(ValueError):
        forms.miles(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("$1,234.56", 123456), ("89", 8900), ("89.9", 8990), (".5", 50), ("-10.00", -1000), ("(5.00)", -500), ("", None)],
)
def test_money(raw, expected):
    assert forms.money(raw) == expected


@pytest.mark.parametrize("raw", ["12.345", "ten", "1.2.3"])
def test_bad_money(raw):
    with pytest.raises(ValueError):
        forms.money(raw)


@pytest.mark.parametrize(("raw", "expected"), [("2", 2.0), ("1.5", 1.5), ("-1", -1.0), ("", None), (None, None)])
def test_quantity(raw, expected):
    assert forms.quantity(raw) == expected


def test_bad_quantity():
    with pytest.raises(ValueError):
        forms.quantity("two")


@pytest.mark.parametrize(("raw", "expected"), [("2016-08-15", "2016-08-15"), ("08/15/2016", "2016-08-15"), ("8/15/16", "2016-08-15")])
def test_day(raw, expected):
    assert forms.day(raw) == expected


def test_future_days_are_refused():
    with pytest.raises(ValueError, match="future"):
        forms.day((date.today() + timedelta(days=2)).isoformat())


def test_year():
    assert forms.year("2016") == 2016
    with pytest.raises(ValueError):
        forms.year("16")


@pytest.mark.parametrize(("raw", "expected"), [("6", 6), ("24 months", 24), ("1 mo", 1), ("", None)])
def test_months(raw, expected):
    assert forms.months(raw) == expected


@pytest.mark.parametrize("raw", ["0", "six", "1.5", "601"])
def test_bad_months(raw):
    with pytest.raises(ValueError):
        forms.months(raw)
