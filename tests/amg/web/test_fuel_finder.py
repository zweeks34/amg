"""Narrowing and sorting a car's fuel log, on rows shaped as the log makes them."""

from __future__ import annotations

import pytest

from amg.web.fuel_finder import Finder, choices, find, sorts


def _row(n, day="2026-06-01", station="", city="", state="", note="", cost=3_300, partial=False, place=None,
         unusual=False, unit_cents=None, economy=None):
    return {"id": n, "day": day, "station": station, "city": city, "state": state, "note": note, "cost_cents": cost,
            "partial": partial, "place": place, "unusual": unusual, "unit_cents": unit_cents, "economy_value": economy}


def _ids(rows, **params):
    return [row["id"] for row in find(rows, Finder.read(params).within(choices(rows)))]


ROWS = [    # newest first, as the log has them
    _row(6, "2026-06-20", "Shell", "Trenton", "NJ", note="Road trip to the coast"),
    _row(5, "2026-05-20", "shell", "newark", "NJ", partial=True),
    _row(4, "2026-04-20", "Wawa", "Newark", "DE", note="ROAD work on Route 9"),
    _row(3, "2026-03-20", "Costco", "", "PA", cost=None),
    _row(2, "2026-02-20", "", "Halifax", "NS"),
    _row(1, "2026-01-20", unusual=True),
]


def test_nothing_narrows_the_log_until_asked():
    assert _ids(ROWS) == [6, 5, 4, 3, 2, 1]
    finder = Finder.read({})
    assert (finder.on, finder.active, finder.changed, finder.query()) == (0, False, False, "")


def test_dates_include_both_ends_and_either_works_alone():
    assert _ids(ROWS, **{"from": "2026-03-20", "to": "2026-05-20"}) == [5, 4, 3]
    assert _ids(ROWS, **{"from": "2026-05-20"}) == [6, 5]
    assert _ids(ROWS, to="2026-02-20") == [2, 1]


def test_from_after_to_is_taken_the_right_way_round():
    assert _ids(ROWS, **{"from": "2026-05-20", "to": "2026-03-20"}) == [5, 4, 3]


def test_state_city_and_station_go_by_what_the_log_holds_whatever_the_capitals():
    assert _ids(ROWS, state="NJ") == [6, 5]
    assert _ids(ROWS, city="HALIFAX") == [2]
    assert _ids(ROWS, station="SHELL") == [6, 5]


def test_two_newarks_are_one_city_until_a_state_says_which():
    assert _ids(ROWS, city="Newark") == [5, 4]
    assert _ids(ROWS, city="newark", state="DE") == [4]
    assert _ids(ROWS, city="Newark", state="NJ") == [5]


def test_a_city_not_in_the_chosen_state_is_dropped():
    finder = Finder.read({"state": "NJ", "city": "Halifax"}).within(choices(ROWS))
    assert (finder.state, finder.city) == ("NJ", "")


def test_filters_all_have_to_match():
    assert _ids(ROWS, state="NJ", station="Shell", fill="partial") == [5]
    assert _ids(ROWS, state="DE", station="Shell") == []


@pytest.mark.parametrize("look, expected", [
    ("location", [1]),                 # neither a city nor a state: one of them is enough
    ("station", [2, 1]),
    ("cost", [3]),
    ("unusual", [1]),
    ("any", [3, 2, 1]),
])
def test_needs_a_look(look, expected):
    assert _ids(ROWS, look=look) == expected


def test_a_charge_at_home_is_missing_no_place_but_can_miss_a_cost():
    rows = [_row(2, place="Home", cost=None), _row(1, place="Public")]
    assert _ids(rows, look="location") == [1]
    assert _ids(rows, look="station") == [1]
    assert _ids(rows, look="cost") == [2]


def test_full_or_partial():
    assert _ids(ROWS, fill="partial") == [5]
    assert _ids(ROWS, fill="full") == [6, 4, 3, 2, 1]


def test_every_word_of_a_note_search_has_to_be_in_the_note():
    assert _ids(ROWS, note="road") == [6, 4]
    assert _ids(ROWS, note="  ROAD   coast ") == [6]
    assert _ids(ROWS, note="road nowhere") == []


SORTED = [
    _row(4, "2026-04-01", cost=4_000, unit_cents=340.0, economy=30.0),
    _row(3, "2026-03-01", cost=None, unit_cents=None, economy=None),
    _row(2, "2026-02-01", cost=2_000, unit_cents=320.0, economy=32.0),
    _row(1, "2026-01-01", cost=3_000, unit_cents=340.0, economy=28.0),
]


@pytest.mark.parametrize("sort, expected", [
    ("newest", [4, 3, 2, 1]),
    ("oldest", [1, 2, 3, 4]),
    ("price_low", [2, 4, 1, 3]),        # 4 and 1 tie: newest first; no figure goes last
    ("price_high", [4, 1, 2, 3]),
    ("cost", [4, 1, 2, 3]),
    ("economy_high", [2, 4, 1, 3]),
    ("economy_low", [1, 4, 2, 3]),
])
def test_sorts_put_what_has_no_figure_last(sort, expected):
    assert _ids(SORTED, sort=sort) == expected


def test_each_sort_on_offer_can_be_read_back():
    offered = sorts("MPG")
    assert offered["economy_high"] == "Best MPG" and sorts("mi/kWh")["economy_low"] == "Lowest mi/kWh"
    assert [Finder.read({"sort": key}).sort for key in offered] == list(offered)


def test_what_doesnt_fit_the_log_is_dropped():
    params = {"from": "someday", "to": "2026-13-45", "state": "ZZ", "city": "Atlantis", "station": "Nowhere",
              "look": "everything", "fill": "half", "sort": "//evil.example"}
    finder = Finder.read(params).within(choices(ROWS))
    assert finder == Finder()
    assert finder.url(7) == "/vehicles/7/fuel"


def test_sorting_alone_isnt_a_filter():
    finder = Finder.read({"sort": "oldest"})
    assert (finder.on, finder.active, finder.changed) == (0, False, True)


def test_links_carry_the_filters_and_land_on_the_log():
    finder = Finder.read({"state": "NJ", "note": "road trip", "sort": "cost"})
    assert finder.on == 2
    assert finder.query() == "?state=NJ&note=road+trip&sort=cost"
    assert finder.url(7, saved=12) == "/vehicles/7/fuel?state=NJ&note=road+trip&sort=cost&saved=12#log-heading"
    assert finder.csv_url(7) == "/vehicles/7/fuel.csv?state=NJ&note=road+trip&sort=cost"
    assert finder.cleared(7) == "/vehicles/7/fuel?sort=cost#log-heading"       # the same order, nothing narrowing
    assert Finder().url(7, saved=12) == "/vehicles/7/fuel?saved=12"            # the log as it was: the top of the page
    assert Finder().cleared(7) == "/vehicles/7/fuel#log-heading"


def test_the_choices_are_what_the_log_holds_each_once_as_last_written():
    assert choices(ROWS) == {
        "states": ["DE", "NJ", "NS", "PA"],
        "cities": [{"name": "Halifax", "state": "NS"}, {"name": "newark", "state": "DE"},
                   {"name": "newark", "state": "NJ"}, {"name": "Trenton", "state": "NJ"}],
        "stations": ["Costco", "Shell", "Wawa"],
    }
    assert choices([]) == {"states": [], "cities": [], "stations": []}
