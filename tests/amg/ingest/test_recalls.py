"""Asking NHTSA for recalls: reading its answers, matching model names, and failing in words."""

from __future__ import annotations

import io
import urllib.error

import pytest
import recall_fixtures as nf  # tests/ is on pytest's path

from amg.ingest import recalls
from amg.ingest.recalls import _get as real_get   # before the autouse fixture swaps it out


def test_parse_reads_nhtsas_answer():
    air_bag, steering = recalls.parse(nf.RECALLS)
    assert air_bag == recalls.Recall(
        campaign="19V910000", reported_on="2019-12-19", component="AIR BAGS: AIR BAG/RESTRAINT CONTROL MODULE",
        summary="A replacement air bag control module may not match the passenger air bag.",
        consequence="The passenger air bag may not deploy as it should in a crash.",
        remedy="Dealers will replace the module free of charge.", park_it=False, park_outside=False)
    assert (steering.reported_on, steering.park_it) == ("2016-05-11", True)    # day first: 11 May


def test_each_campaign_once_and_an_unreadable_date_is_none():
    twice = {"results": [nf.AIR_BAG, {**nf.AIR_BAG, "ReportReceivedDate": "soon"}]}
    assert [r.campaign for r in recalls.parse(twice)] == ["19V910000"]
    assert recalls.parse({"results": [{**nf.AIR_BAG, "ReportReceivedDate": "soon"}]})[0].reported_on is None
    assert recalls.parse({}) == []


@pytest.mark.parametrize(("model", "matched"), [
    ("Outback", "OUTBACK"), ("outback  limited", "OUTBACK"), ("Legacy 3.6R", "LEGACY"), ("Outbacker", ""),
    ("Forester", ""),
])
def test_matching_the_cars_model_to_nhtsas(model, matched):
    assert recalls.match(model, ("LEGACY", "OUTBACK", "OUTBACK WILDERNESS")) == matched


def test_the_longest_name_wins():
    assert recalls.match("Outback Wilderness XT", ("OUTBACK", "OUTBACK WILDERNESS")) == "OUTBACK WILDERNESS"


def test_lookup_asks_with_nhtsas_name_and_never_the_vin(monkeypatch):
    asked = nf.nhtsa(monkeypatch)
    found = recalls.lookup(2016, "Subaru", "Outback Limited")
    assert (found.model, found.listed, len(found.recalls)) == ("OUTBACK", ("LEGACY", "OUTBACK"), 2)
    assert asked == [
        "https://api.nhtsa.gov/products/vehicle/models?modelYear=2016&make=Subaru&issueType=r",
        "https://api.nhtsa.gov/recalls/recallsByVehicle?make=Subaru&model=OUTBACK&modelYear=2016",
    ]


def test_no_match_asks_no_further(monkeypatch):
    asked = nf.nhtsa(monkeypatch)
    assert recalls.lookup(2016, "Subaru", "Forester") == recalls.Lookup("", ("LEGACY", "OUTBACK"), ())
    assert len(asked) == 1


def test_campaign_words():
    assert recalls.campaign_words("19V910000") == "19V-910"
    assert recalls.campaign_words("19E012001") == "19E012001"


def _answer(monkeypatch, outcome):
    def urlopen(request, timeout):
        if isinstance(outcome, Exception):
            raise outcome
        return io.BytesIO(outcome)

    monkeypatch.setattr(recalls.urllib.request, "urlopen", urlopen)


def test_a_400_means_nothing_listed(monkeypatch):
    _answer(monkeypatch, urllib.error.HTTPError("https://api.nhtsa.gov", 400, "Bad Request", {}, None))
    assert real_get("https://api.nhtsa.gov/x") == {}


def test_failing_to_reach_nhtsa_is_said(monkeypatch):
    _answer(monkeypatch, urllib.error.URLError("no route to host"))
    with pytest.raises(recalls.RecallLookupError, match="Couldn't reach NHTSA's recall service."):
        real_get("https://api.nhtsa.gov/x")
    _answer(monkeypatch, urllib.error.HTTPError("https://api.nhtsa.gov", 503, "Unavailable", {}, None))
    with pytest.raises(recalls.RecallLookupError, match="It answered 503."):
        real_get("https://api.nhtsa.gov/x")


def test_an_answer_is_read_as_json(monkeypatch):
    _answer(monkeypatch, b'{"Count": 0, "results": []}')
    assert real_get("https://api.nhtsa.gov/x") == {"Count": 0, "results": []}
