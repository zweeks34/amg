from __future__ import annotations

import io
import json
import urllib.error

import pytest

from amg.ingest import vin

# The worked example from the VIN check-digit literature: its check digit is X.
GOOD = "1M8GDM9AXKP042788"


def test_check_digit():
    assert vin.check_digit(GOOD) == "X"
    assert vin.problem(GOOD) is None


def test_normalize_strips_spaces_and_dashes():
    assert vin.normalize(" 1m8gdm9a-xkp 042788 ") == GOOD


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (GOOD[:-1], "17 characters"),
        (GOOD[:4] + "O" + GOOD[5:], "I, O or Q"),
        (GOOD[:4] + "*" + GOOD[5:], "letters and digits"),
        (GOOD[:-1] + "9", "check digit"),
    ],
)
def test_problems(value, expected):
    assert expected in vin.problem(value)


def _payload(**fields):
    return {"Results": [{"Make": "", "Model": "", "ModelYear": "", **fields}]}


def test_parse_gasoline_car():
    decoded = vin.parse(_payload(
        Make="SUBARU", Model="Outback", ModelYear="2016", Trim="Premium",
        DisplacementL="2.5", EngineCylinders="4", FuelTypePrimary="Gasoline",
    ))
    assert decoded == vin.Decoded(2016, "Subaru", "Outback", "Premium", "2.5L 4-cyl", "gas")


@pytest.mark.parametrize(
    ("fields", "powertrain"),
    [
        ({"ElectrificationLevel": "BEV (Battery Electric Vehicle)"}, "ev"),
        ({"FuelTypePrimary": "Electric"}, "ev"),
        ({"ElectrificationLevel": "Strong HEV (Hybrid Electric Vehicle)"}, "hybrid"),
        ({"ElectrificationLevel": "PHEV (Plug-in Hybrid Electric Vehicle)"}, "hybrid"),
        ({"FuelTypePrimary": "Diesel"}, "gas"),
    ],
)
def test_parse_powertrains(fields, powertrain):
    assert vin.parse(_payload(Make="X", **fields)).powertrain == powertrain


def test_uppercase_makes_stay_uppercase():
    assert vin.parse(_payload(Make="BMW")).make == "BMW"
    assert vin.parse(_payload(Make="MERCEDES-BENZ")).make == "Mercedes-Benz"


def test_unknown_vin_is_an_error():
    with pytest.raises(vin.VinLookupError, match="doesn't recognise"):
        vin.parse(_payload())


def test_decode_reads_vpic(monkeypatch):
    body = json.dumps(_payload(Make="TOYOTA", Model="Prius", ModelYear="2020",
                               ElectrificationLevel="Strong HEV")).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: io.BytesIO(body))
    assert vin.decode(GOOD).powertrain == "hybrid"


def test_decode_network_failure_is_a_friendly_error(monkeypatch):
    def fail(request, timeout):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(vin.VinLookupError, match="Couldn't reach"):
        vin.decode(GOOD)
