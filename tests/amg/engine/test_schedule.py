"""The gap engine, on cars driven at a steady pace so every date can be worked out by hand."""

from __future__ import annotations

from datetime import date, timedelta

from amg.engine.odometer import Odometer
from amg.engine.schedule import Car, Item, Service, assess, meets, walk

NEW = date(2020, 1, 1)


def day(n: int) -> date:
    return NEW + timedelta(days=n)


def steady(per_day: int = 30, to: int = 1500) -> Odometer:
    """A car driven ``per_day`` miles every day from new, with a reading every 50 days."""
    return Odometer([(day(n), n * per_day) for n in range(0, to + 1, 50)], in_service=NEW)


def item(codes=("engine_oil",), action="replace", miles=None, months=None, first_miles=None, first_months=None,
         applies="always", id=1) -> Item:
    return Item(id, "Item", frozenset(codes), action, miles, months, first_miles, first_months, applies)


_ids = iter(range(1, 10_000))


def service(n: int, *codes: str, action="replace", per_day=30) -> Service:
    """A service on day n, at the steady car's mileage, covering ``codes`` with ``action``."""
    return Service(next(_ids), day(n), n * per_day, {code: frozenset({action}) for code in codes or ("engine_oil",)})


def statuses(result) -> list[tuple[str, date, int | None]]:
    return [(o.status, o.due_day, o.due_miles) for o in result.occurrences]


CAR = Car(in_service=NEW)


# ---------- Whichever comes first ----------


def test_months_come_first_on_a_car_that_isnt_driven_much():
    odo = steady(per_day=10)     # 3,650 mi a year
    result = walk(item(miles=6000, months=6), [], odo, CAR, today=day(150), until=day(400))
    assert statuses(result)[0] == ("due", date(2020, 7, 1), 1820)      # six months, at ~1,820 mi


def test_miles_come_first_on_a_car_driven_hard():
    odo = steady(per_day=100)    # 36,500 mi a year
    result = walk(item(miles=6000, months=6), [], odo, CAR, today=day(10), until=day(100))
    assert statuses(result)[0] == ("later", day(60), 6000)


def test_first_due_then_every():
    odo = steady()
    timing = item(miles=15_000, first_miles=7_500)
    result = walk(timing, [service(250), service(750)], odo, CAR, today=day(1000), until=day(1300))
    assert statuses(result) == [
        ("done", day(250), 7_500),       # first at 7,500
        ("done", day(750), 22_500),      # then every 15,000 from when it was done
        ("later", day(1250), 37_500),
    ]


def test_first_due_by_years_counts_from_new():
    odo = steady(per_day=10)
    coolant = item(("engine_coolant",), miles=75_000, months=72, first_miles=137_500, first_months=132)
    result = walk(coolant, [], odo, CAR, today=day(400), until=day(500))
    assert statuses(result)[0][:2] == ("later", date(2031, 1, 1))     # 11 years, long before 137,500 mi


# ---------- Done, missed, late ----------


def test_a_late_service_counts_and_a_whole_interval_with_nothing_is_missed():
    """Oil every 6,000 mi: done 13,500 → due 19,500; nothing until 27,000 → 19,500 missed,
    25,500 done late at 27,000, next due 33,000."""
    odo = steady()
    result = walk(item(miles=6000), [service(200), service(450), service(900)], odo, CAR,
                  today=day(1000), until=day(1100))
    assert [(o.status, o.due_miles, o.late) for o in result.occurrences] == [
        ("done", 6_000, False),
        ("done", 12_000, True),      # done at 13,500: a quarter of an interval late
        ("gap", 19_500, False),      # 25,500 fell due too with nothing done
        ("done", 25_500, True),      # done at 27,000, before 31,500 fell due
        ("later", 33_000, False),
    ]
    assert result.occurrences[3].service.miles == 27_000
    assert [o.due_miles for o in result.missed] == [19_500]
    assert result.current.due_miles == 33_000


def test_done_early_restarts_the_count():
    odo = steady()
    result = walk(item(months=6), [service(60)], odo, CAR, today=day(100), until=day(400))
    assert statuses(result)[:2] == [("done", date(2020, 7, 1), 5_460), ("later", date(2020, 9, 1), 7_320)]


def test_the_tolerance_edge():
    """Every 12 months from 2021-01-01: the next falls 365 days later, so a tenth is 36.5 days."""
    odo = steady(to=1200)
    yearly = item(months=12)
    car = Car(in_service=date(2020, 1, 1))
    on_time = walk(yearly, [service(366 + 36)], odo, car, today=day(500), until=day(800))
    late = walk(yearly, [service(366 + 37)], odo, car, today=day(500), until=day(800))
    assert on_time.occurrences[0].due_day == date(2021, 1, 1)
    assert (on_time.occurrences[0].late, late.occurrences[0].late) == (False, True)


def test_overdue_until_the_next_falls_due_then_missed():
    odo = steady()
    oil = item(months=6)
    assert statuses(walk(oil, [], odo, CAR, today=day(200), until=day(400)))[0][0] == "overdue"
    assert statuses(walk(oil, [], odo, CAR, today=day(400), until=day(500)))[:2] == [
        ("gap", date(2020, 7, 1), 5_460), ("overdue", date(2021, 1, 1), 10_980)]


def test_due_soon_by_days_or_by_miles():
    odo = steady()
    oil = item(miles=6000)                             # due on day 200
    assert walk(oil, [], odo, CAR, today=day(170), until=day(300)).current.status == "due"     # 30 days, 900 mi
    assert walk(oil, [], odo, CAR, today=day(160), until=day(300)).current.status == "later"   # 40 days, 1,200 mi
    slow = steady(per_day=10)
    by_miles = walk(item(miles=2000), [], slow, CAR, today=day(105), until=day(300))          # 95 days but 950 mi
    assert by_miles.current.status == "due"


def test_a_one_off_item_is_due_once():
    odo = steady()
    break_in = item(first_miles=1_000)
    assert statuses(walk(break_in, [service(40)], odo, CAR, today=day(500), until=day(900))) == [
        ("done", day(34), 1_000)]
    assert statuses(walk(break_in, [], odo, CAR, today=day(500), until=day(900))) == [("overdue", day(34), 1_000)]


# ---------- Before you had it ----------


def test_nothing_is_missed_before_you_had_the_car():
    odo = steady()
    car = Car(in_service=NEW, acquired_on=day(500), acquired_miles=15_000)
    result = walk(item(months=6), [], odo, car, today=day(800), until=day(900))
    before = [o for o in result.occurrences if o.status == "before"]
    assert before and all(o.due_day < day(500) for o in before)
    assert all(o.due_day >= day(500) for o in result.missed)


def test_a_used_car_with_no_in_service_date_counts_from_when_you_got_it():
    odo = Odometer([(day(500), 15_000), (day(800), 24_000)])
    car = Car(acquired_on=day(500), acquired_miles=15_000)
    result = walk(item(miles=6000), [], odo, car, today=day(600), until=day(900))
    assert statuses(result)[0] == ("later", day(700), 21_000)


# ---------- Counted from a date ----------

# Washer fluid every 3 months on a car you've had since 2019, never once recorded.
SINCE_2019 = Car(in_service=date(2019, 5, 1))
YEARS = Odometer([(date(2019, 5, 1), 0), (date(2026, 9, 1), 80_000)], in_service=date(2019, 5, 1))
FLUID = Item(1, "Washer fluid", frozenset({"washer_fluid"}), "replace", interval_months=3)
COUNTED = Item(1, "Washer fluid", frozenset({"washer_fluid"}), "replace", interval_months=3,
               counts_from=date(2026, 10, 6))
OCT_6 = date(2026, 10, 6)


def topped_up(on: date) -> Service:
    return Service(next(_ids), on, None, {"washer_fluid": frozenset({"replace"})})


def test_a_job_never_recorded_is_missed_all_along_without_a_date():
    result = walk(FLUID, [], YEARS, SINCE_2019, today=OCT_6, until=date(2027, 6, 1))
    assert len(result.missed) > 20 and result.current.status == "overdue"


def test_counted_from_a_date_nothing_before_it_is_judged():
    result = walk(COUNTED, [], YEARS, SINCE_2019, today=OCT_6, until=date(2027, 6, 1))
    assert [(o.status, o.due_day) for o in result.occurrences] == [
        ("later", date(2027, 1, 6)), ("later", date(2027, 4, 6))]


def test_counted_from_a_date_a_later_service_counts():
    result = walk(COUNTED, [topped_up(date(2026, 12, 1))], YEARS, SINCE_2019, today=date(2027, 1, 10),
                  until=date(2027, 4, 1))
    assert [(o.status, o.due_day) for o in result.occurrences] == [
        ("done", date(2027, 1, 6)), ("later", date(2027, 3, 1))]


def test_counted_from_a_date_an_earlier_service_does_not():
    result = walk(COUNTED, [topped_up(date(2026, 9, 1))], YEARS, SINCE_2019, today=OCT_6, until=date(2027, 2, 1))
    assert [(o.status, o.due_day) for o in result.occurrences] == [("later", date(2027, 1, 6))]


def test_counted_from_a_date_first_at_no_longer_applies():
    coolant = Item(1, "Coolant", frozenset({"engine_coolant"}), "replace", interval_months=60, first_months=120,
                   counts_from=OCT_6)
    result = walk(coolant, [], YEARS, SINCE_2019, today=OCT_6, until=date(2032, 1, 1))
    assert result.current.due_day == date(2031, 10, 6)                    # not 2029-05-01, ten years from new


def test_a_one_off_item_still_counts_from_new():
    once = Item(1, "Timing belt", frozenset({"timing_belt"}), "replace", first_months=120, counts_from=OCT_6)
    result = walk(once, [], YEARS, SINCE_2019, today=OCT_6, until=date(2030, 1, 1))
    assert [(o.status, o.due_day) for o in result.occurrences] == [("later", date(2029, 5, 1))]


# ---------- No readings ----------


def test_with_no_readings_months_still_count():
    result = walk(item(miles=6000, months=6), [], Odometer([]), CAR, today=day(200), until=day(400))
    assert statuses(result)[0] == ("overdue", date(2020, 7, 1), None)


def test_with_no_readings_a_mileage_only_item_needs_one():
    result = walk(item(miles=6000), [], Odometer([]), CAR, today=day(200), until=day(400))
    assert result.needs_reading and result.occurrences == []


# ---------- What meets what ----------


def test_an_inspection_doesnt_meet_a_replacement():
    pads = item(("brake_pads",), action="replace")
    assert not meets(service(10, "brake_pads", action="inspect"), pads)
    assert meets(service(10, "brake_pads", action="replace"), pads)


def test_a_replacement_meets_an_inspection():
    assert meets(service(10, "brake_pads", action="replace"), item(("brake_pads",), action="inspect"))


def test_any_shared_service_type_will_do():
    brakes = item(("brake_pads", "brake_rotors", "axle_boots"), action="inspect")
    assert meets(service(10, "axle_boots", action="inspect"), brakes)
    assert not meets(service(10, "engine_oil"), brakes)


def test_a_multipoint_or_state_inspection_meets_inspections_only():
    multipoint = service(10, "multipoint_inspection", action="inspect")
    state = service(10, "state_inspection", action="perform")
    for visit in (multipoint, state):
        assert meets(visit, item(("steering_suspension",), action="inspect"))
        assert not meets(visit, item(("brake_fluid",), action="replace"))
        assert not meets(visit, item(("tire_rotation",), action="perform"))


def test_a_procedure_needs_doing():
    rotation = item(("tire_rotation",), action="perform")
    assert meets(service(10, "tire_rotation", action="perform"), rotation)
    assert not meets(service(10, "tire_rotation", action="inspect"), rotation)


# ---------- Normal and severe ----------


def test_only_items_for_how_the_car_is_driven_are_judged():
    items = [item(applies="always", id=1), item(applies="normal", id=2), item(applies="severe", id=3)]
    normal = assess(items, [], steady(), Car(in_service=NEW), today=day(100))
    severe = assess(items, [], steady(), Car(in_service=NEW, severe=True), today=day(100))
    assert [s.item.id for s in normal] == [1, 2]
    assert [s.item.id for s in severe] == [1, 3]
