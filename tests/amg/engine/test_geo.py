"""Geography: a town's name as it's looked up, and where a point goes on the map."""

from __future__ import annotations

import pytest

from amg.engine.geo import project, town_key


@pytest.mark.parametrize("typed, key", [
    ("Trenton", "trenton"),
    ("  TRENTON ", "trenton"),
    ("St. Augustine", "saint augustine"),
    ("Saint Augustine", "saint augustine"),
    ("Mt Laurel", "mount laurel"),
    ("Mount Laurel", "mount laurel"),
    ("Ft. Lauderdale", "fort lauderdale"),
    ("Montréal", "montreal"),
    ("St. John's", "saint johns"),
    ("Wilkes-Barre", "wilkes barre"),
    ("Hamilton Twp", "hamilton township"),
    ("", ""),
])
def test_a_town_is_looked_up_however_its_written(typed, key):
    assert town_key(typed) == key


def test_the_map_runs_east_and_south():
    trenton, pittsburgh, miami = project(40.22, -74.76), project(40.44, -80.0), project(25.76, -80.19)
    assert pittsburgh[0] < trenton[0]                       # west is left
    assert miami[1] > trenton[1]                            # south is down the page
    assert project(40.0, -96.0) == pytest.approx((0.0, 0.0), abs=1e-6)   # the middle of the map
    # Trenton to Pittsburgh is about 445 km. An equal-area map keeps areas, not distances: here, between its
    # standard parallels, east-west runs about 6% short, which a town-level dot doesn't notice.
    distance = ((trenton[0] - pittsburgh[0]) ** 2 + (trenton[1] - pittsburgh[1]) ** 2) ** 0.5
    assert distance == pytest.approx(419, rel=0.01)


def test_the_far_aleutians_stay_with_alaska():
    attu, anchorage = project(52.9, 172.9), project(61.2, -149.9)
    assert attu[0] < anchorage[0]                           # west of Anchorage, not across the map
