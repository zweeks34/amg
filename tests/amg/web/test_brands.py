"""Recognising a brand in a station's or shop's name, however it was written down."""

from __future__ import annotations

import pytest

from amg.ingest.site_icons import SITE
from amg.web import brands


@pytest.mark.parametrize(("name", "brand"), [
    ("Wawa on Route 9", "Wawa"),
    ("EXXONMOBIL 4471", "Exxon"),
    ("Exxon Mobil", "Exxon"),
    ("Mobil 1 Lube Express", "Mobil"),
    ("SHEETZ #312", "Sheetz"),
    ("Jiffy Lube #2231", "Jiffy Lube"),
    ("Love's Travel Stop", "Love's"),
    ("Sam's Club Fuel", "Sam's Club"),
    ("7-Eleven", "7-Eleven"),
    ("O'Reilly Auto Parts", "O'Reilly"),
    ("Hyundai of Wesley Chapel", "Hyundai"),            # a dealer: its make
    ("Firestone Complete Auto Care, Toyota Plaza", "Firestone"),   # a chain beats a make
    ("Gulf #12", "Gulf"),
    ("Automobile Repair", None),                        # Mobil, but not a whole word
    ("Gulf Coast Auto Repair", None),                   # Gulf only as the whole name
    ("Irving Auto Body", None),
    ("Joe's Garage", None),
    ("", None),
])
def test_a_name_says_its_brand(name, brand):
    found = brands.recognise(name)
    assert (found.name if found else None) == brand


def test_every_brand_has_a_website_and_words():
    assert all(SITE.fullmatch(brand.site) and brand.words for brand in brands.BRANDS)
    assert len({brand.name for brand in brands.BRANDS}) == len(brands.BRANDS)
    assert {"wawa.com", "sheetz.com", "jiffylube.com", "hyundaiusa.com"} <= brands.SITES
