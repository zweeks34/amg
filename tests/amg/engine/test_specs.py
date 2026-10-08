"""The specs catalogue, what receipt lines suggest for a box, and what was last fitted."""

from __future__ import annotations

from datetime import date

from amg.engine import specs
from amg.engine.specs import FIELDS


def line(code, description, part_number="", kind="part", event_id=1, day="2026-08-01", shop="Valley Honda",
         quantity=None):
    return {"code": code, "description": description, "part_number": part_number, "kind": kind, "event_id": event_id,
            "performed_on": day, "shop": shop, "quantity": quantity}


def test_the_catalogue_hangs_together():
    assert len(FIELDS) == len({f.label for f in FIELDS.values()})
    assert {f.group for f in FIELDS.values()} == set(specs.GROUPS)
    assert all(f.pick in ("part", "grade", "tire", "length") for f in FIELDS.values() if f.codes)
    assert all(not f.pick for f in FIELDS.values() if not f.codes)


def test_an_electric_car_has_no_oil_or_fuel_unless_a_value_says_otherwise():
    groups = dict(specs.for_car("ev"))
    assert "Engine oil" not in groups and "Fuel and ignition" not in groups
    assert [f.key for f in groups["Filters"]] == ["cabin_air_filter"]
    assert "Engine oil" in dict(specs.for_car("ev", ["oil_grade"]))
    assert [g for g, _ in specs.for_car("gas")] == list(specs.GROUPS)


def test_an_oil_grade_from_how_a_shop_writes_it():
    lines = [line("engine_oil", "0W20 FULL SYN OIL", quantity=5), line("engine_oil", "Oil change SAE 5W-30", kind="labor"),
             line("engine_oil", "15W-40 diesel oil")]
    assert specs.candidates(FIELDS["oil_grade"], lines) == ["0W-20", "5W-30", "15W-40"]


def test_a_tire_size():
    lines = [line("tires", "P225/65R17 102H Geolandar"), line("tires", "Mount and balance", kind="labor")]
    assert specs.candidates(FIELDS["tire_size"], lines) == ["225/65R17"]


def test_a_part_number_over_a_description_and_never_twice():
    lines = [line("oil_filter", "Oil filter", "15208AA15A"), line("oil_filter", "OIL FILTER", "15208aa15a", event_id=2),
             line("oil_filter", "Oil and filter change", kind="labor"),
             line("wiper_blades", "Wiper blade 26 in"), line("wiper_blades", "Wiper blades"),
             line("oil_filter", "Filter, oil", "15208AA170", event_id=3)]
    assert specs.candidates(FIELDS["oil_filter"], lines) == ["15208AA15A", "15208AA170"]
    # A description says which part only when it has a number in it.
    battery = [line("battery_12v", "Battery H6 AGM"), line("battery_12v", "Battery")]
    assert specs.candidates(FIELDS["battery"], battery) == ["Battery H6 AGM"]


def test_a_wiper_blades_length_over_its_part_number():
    lines = [line("wiper_blades", "Wiper blade 26 in", "76620-TBA-A02"), line("wiper_blades", 'Wiper 16"'),
             line("wiper_blades", "Rear wiper", "WR-14"), line("wiper_blades", "Wiper blades, 650mm")]
    assert specs.candidates(FIELDS["wiper_driver"], lines) == ["26 in", "16 in", "WR-14"]


def test_last_fitted_is_the_newest_visit_per_part():
    lines = [   # newest first, as repo.specs.fitted_lines gives them
        line("cabin_air_filter", "Cabin filter", "72880FL00A", event_id=9, day="2026-08-01"),
        line("oil_filter", "Oil filter", "15208AA15A", event_id=9, day="2026-08-01"),
        line("engine_oil", "0W-20 full synthetic", quantity=5, event_id=9, day="2026-08-01"),
        line("engine_oil", "Oil and filter change", kind="labor", event_id=9, day="2026-08-01"),
        line("engine_air_filter", "Engine air filter", "16546AA12A", event_id=4, day="2025-03-02", shop="Midas"),
        line("oil_filter", "Oil filter", "OLD-1", event_id=4, day="2025-03-02", shop="Midas"),
    ]
    oil = specs.last_fitted(lines, ["engine_oil", "oil_filter"])
    assert oil == [specs.Fitted(date(2026, 8, 1), "Valley Honda", 9,
                                ("Oil filter 15208AA15A", "0W-20 full synthetic × 5"))]
    filters = specs.last_fitted(lines, ["engine_air_filter", "cabin_air_filter"])
    assert [(f.event_id, f.lines) for f in filters] == [(9, ("Cabin filter 72880FL00A",)),
                                                         (4, ("Engine air filter 16546AA12A",))]
    done = [line("brake_fluid", "Brake fluid: done, no receipt", kind="other", shop="")]
    assert specs.last_fitted(done, ["brake_fluid"])[0].lines == ("Brake fluid: done, no receipt",)
    assert specs.last_fitted(lines, ["spark_plugs"]) == []
