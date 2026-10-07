from __future__ import annotations

import json

import pymupdf
import pytest
import receipt_fixtures as fx  # tests/ is on pytest's path
import schedule_fixtures as sfx

from amg.ingest import background, manuals
from amg.repo import schedules, vehicles


def _pdf(pages=2):
    with pymupdf.open() as doc:
        for n in range(pages):
            doc.new_page(width=612, height=792).insert_text((72, 72), f"MAINTENANCE SCHEDULE page {n + 1}")
        return doc.tobytes()


@pytest.fixture
def reads(monkeypatch):
    """Read schedules inline, answering each read with the next queued extraction."""
    queue: list = []
    calls: list = []

    def read_manual(path, car, types, pages=""):
        calls.append(pages)
        return manuals.ScheduleRead([1, 2], queue.pop(0) if queue else sfx.sample(), fx.USAGE)

    def draft_schedule(car, types):
        return manuals.ScheduleRead([], queue.pop(0) if queue else sfx.sample(), fx.USAGE)

    monkeypatch.setattr(manuals, "read_manual", read_manual)
    monkeypatch.setattr(manuals, "draft_schedule", draft_schedule)
    monkeypatch.setattr(background, "spawn", background.run)
    return calls


@pytest.fixture
def outback(conn):
    return vehicles.create(conn, vehicles.VehicleFields(name="Outback", year=2016, make="Subaru", model="Outback"))


def _upload(client, car, data=None, pages=""):
    files = [("files", ("plan.pdf", data or _pdf(), "application/pdf"))]
    return client.post(f"/vehicles/{car}/schedule/manual", files=files, data={"pages": pages}, follow_redirects=False)


def _editor(page: str) -> dict:
    start = page.index("scheduleEditor(") + len("scheduleEditor(")
    return json.loads(page[start:page.index(")'", start)])


def _post(client, url, rows, action="use", **fields):
    return client.post(url, data={"items_json": json.dumps(rows), "action": action, "severe_conditions": "Towing",
                                  **fields}, follow_redirects=False)


def _draft_url(response) -> str:
    assert response.status_code == 303, response.text
    return response.headers["location"]


# ---------- Starting a schedule ----------


def test_a_car_with_no_schedule_is_offered_ways_to_start(signed_in, outback):
    assert "Set up the schedule" in signed_in.get(f"/vehicles/{outback}").text
    page = signed_in.get(f"/vehicles/{outback}/schedule").text
    for words in ("Read the owner's manual", "Ask Claude to draft it", "Start from a generic schedule"):
        assert words in page
    assert "Copy another car's schedule" not in page     # no other car has one


def test_read_a_manual_check_it_and_use_it(signed_in, conn, outback, reads):
    url = _draft_url(_upload(signed_in, outback))
    page = signed_in.get(url).text
    assert "Check this schedule" in page and "Pages read · 1, 2" in page
    document_id, sha = conn.execute("SELECT id, sha256 FROM documents").fetchone()
    assert f'src="/documents/{document_id}/pages/2?v={sha[:12]}"' in page
    editor = _editor(page)
    assert editor["fingerprints"] == {str(document_id): sha[:12]}
    names = [(row["name"], row["included"], row["from_read"]) for row in editor["items"]]
    assert ("Spark plug", True, True) in names and ("Timing Belt (WRX/WRX STI)", False, True) in names
    assert editor["reading"] is True
    assert schedules.items(conn, outback) == []          # nothing counts before it's used

    response = _post(signed_in, url, editor["items"])
    assert response.headers["location"] == f"/vehicles/{outback}/schedule?used=1"
    items = schedules.items(conn, outback)
    assert [item["name"] for item in items] == ["Engine oil", "Spark plug", "Engine coolant", "Engine oil"]
    assert {item["source"] for item in items} == {"manual"} and items[0]["document_id"] is not None
    assert items[0]["applies"] == "normal" and items[3]["applies"] == "severe"

    schedule = signed_in.get(f"/vehicles/{outback}/schedule").text
    assert "every 60,000 mi or 5 years" in schedule
    assert "first at 137,500 mi or 11 years, then every 75,000 mi or 6 years" in schedule
    assert "Owner&#39;s manual, p. 1" in schedule and "Severe service only" in schedule
    assert f'href="/documents/{document_id}/pages/1?v={sha[:12]}&amp;size=full"' in schedule
    assert "4 items" in signed_in.get(f"/vehicles/{outback}").text


def test_left_out_rows_are_saved_only_when_included(signed_in, conn, outback, reads):
    url = _draft_url(_upload(signed_in, outback))
    rows = _editor(signed_in.get(url).text)["items"]
    for row in rows:
        row["included"] = True
    _post(signed_in, url, rows)
    assert "Timing Belt (WRX/WRX STI)" in [item["name"] for item in schedules.items(conn, outback)]


def test_typed_pages_are_checked_and_passed_on(signed_in, outback, reads):
    response = _upload(signed_in, outback, pages="9-10")
    assert response.status_code == 422 and "This file has 2 pages." in response.text
    _draft_url(_upload(signed_in, outback, pages="2"))
    assert reads == ["2"]


def test_no_file_is_explained(signed_in, outback):
    response = signed_in.post(f"/vehicles/{outback}/schedule/manual", data={"pages": ""})
    assert response.status_code == 422 and "Choose the manual" in response.text


def test_claude_drafts_one_from_the_car(signed_in, conn, outback, reads):
    url = _draft_url(signed_in.post(f"/vehicles/{outback}/schedule/claude", follow_redirects=False))
    page = signed_in.get(url).text
    assert "not from your manual" in page and "2016 Subaru Outback" in page
    _post(signed_in, url, _editor(page)["items"])
    assert {item["source"] for item in schedules.items(conn, outback)} == {"claude"}


def test_claude_needs_to_know_the_car(signed_in, conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Mystery"))
    response = signed_in.post(f"/vehicles/{car}/schedule/claude")
    assert response.status_code == 422 and "year, make and model" in response.text


def test_start_from_the_template(signed_in, conn, outback):
    url = _draft_url(signed_in.post(f"/vehicles/{outback}/schedule/template", data={"powertrain": "gas"},
                                    follow_redirects=False))
    page = signed_in.get(url).text
    assert "generic gasoline schedule" in page
    editor = _editor(page)
    assert editor["reading"] is False                     # nothing for Claude to have read
    _post(signed_in, url, editor["items"])
    items = schedules.items(conn, outback)
    assert items and {item["source"] for item in items} == {"template"}
    assert "Timing belt" not in [item["name"] for item in items]    # left out unless the engine has one


def test_copy_another_cars_schedule(signed_in, conn, outback):
    forester = vehicles.create(conn, vehicles.VehicleFields(name="Forester", year=2016, make="Subaru", model="Forester"))
    url = _draft_url(signed_in.post(f"/vehicles/{outback}/schedule/template", data={"powertrain": "gas"},
                                    follow_redirects=False))
    _post(signed_in, url, _editor(signed_in.get(url).text)["items"])

    assert "Copy another car's schedule" in signed_in.get(f"/vehicles/{forester}/schedule").text
    url = _draft_url(signed_in.post(f"/vehicles/{forester}/schedule/copy", data={"from_vehicle_id": str(outback)},
                                    follow_redirects=False))
    assert "Copied from Outback&#39;s schedule" in signed_in.get(url).text
    _post(signed_in, url, _editor(signed_in.get(url).text)["items"])
    assert len(schedules.items(conn, forester)) == len(schedules.items(conn, outback))


# ---------- Checking a draft ----------


def test_a_bad_row_keeps_every_row(signed_in, conn, outback, reads):
    url = _draft_url(_upload(signed_in, outback))
    rows = _editor(signed_in.get(url).text)["items"]
    rows[1]["interval_miles"] = "lots"
    rows[2]["covers"] = []
    response = _post(signed_in, url, rows)
    assert response.status_code == 422
    editor = _editor(response.text)
    assert editor["errors"][1] == "Enter whole miles, like 32,610."
    assert editor["errors"][2].startswith("Add the service it's for")
    assert [row["name"] for row in editor["items"]] == [row["name"] for row in rows]
    assert schedules.items(conn, outback) == []


def test_a_draft_with_nothing_included_cant_be_used(signed_in, outback, reads):
    url = _draft_url(_upload(signed_in, outback))
    rows = _editor(signed_in.get(url).text)["items"]
    for row in rows:
        row["included"] = False
    response = _post(signed_in, url, rows)
    assert response.status_code == 422 and "Include at least one item" in response.text


def test_save_the_draft_and_come_back(signed_in, conn, outback, reads):
    url = _draft_url(_upload(signed_in, outback))
    rows = _editor(signed_in.get(url).text)["items"]
    rows[0]["interval_miles"] = "5,000"
    rows[0]["source"] = "you"
    rows[0]["from_read"] = False
    assert _post(signed_in, url, rows, action="save").headers["location"] == f"{url}?saved=1"
    again = _editor(signed_in.get(url).text)["items"][0]
    assert (again["interval_miles"], again["source"], again["from_read"]) == ("5,000", "you", False)
    assert schedules.items(conn, outback) == []


def test_read_again_with_other_pages(signed_in, conn, outback, reads):
    url = _draft_url(_upload(signed_in, outback))
    draft_id = int(url.rsplit("/", 1)[1])
    signed_in.post(f"{url}/read-again", data={"pages": "2"})
    assert reads == ["", "2"]
    assert schedules.get_draft(conn, draft_id)["requested_pages"] == "2"


def test_a_failed_read_says_why(signed_in, conn, outback, monkeypatch):
    def fail(path, car, types, pages=""):
        raise manuals.ManualError("AMG couldn't find a maintenance schedule in this document.")

    monkeypatch.setattr(manuals, "read_manual", fail)
    monkeypatch.setattr(background, "spawn", background.run)
    page = signed_in.get(_draft_url(_upload(signed_in, outback))).text
    assert "couldn&#39;t find a maintenance schedule" in page and "Pages to read" in page


def test_discard_a_draft(signed_in, conn, outback, reads):
    url = _draft_url(_upload(signed_in, outback))
    response = signed_in.post(f"{url}/discard", follow_redirects=False)
    assert response.headers["location"] == f"/vehicles/{outback}/schedule"
    assert schedules.open_drafts(conn, outback) == []


def test_using_a_draft_replaces_the_schedule_and_says_so(signed_in, conn, outback, reads):
    first = _draft_url(_upload(signed_in, outback))
    _post(signed_in, first, _editor(signed_in.get(first).text)["items"])
    second = _draft_url(signed_in.post(f"/vehicles/{outback}/schedule/template", data={"powertrain": "gas"},
                                       follow_redirects=False))
    page = signed_in.get(second).text
    assert "Using this replaces Outback's current schedule of 4 items." in page


# ---------- After ----------


def test_edit_the_schedule_in_place(signed_in, conn, outback, reads):
    url = _draft_url(_upload(signed_in, outback))
    _post(signed_in, url, _editor(signed_in.get(url).text)["items"])
    before = schedules.items(conn, outback)

    rows = _editor(signed_in.get(f"/vehicles/{outback}/schedule/edit").text)["items"]
    rows[0].update(interval_miles="5,000", source="you")
    del rows[1]
    response = signed_in.post(f"/vehicles/{outback}/schedule/edit", data={"items_json": json.dumps(rows)},
                              follow_redirects=False)
    assert response.headers["location"] == f"/vehicles/{outback}/schedule?saved=1"
    after = schedules.items(conn, outback)
    assert after[0]["id"] == before[0]["id"]
    assert (after[0]["interval_miles"], after[0]["interval_months"], after[0]["source"]) == (5000, 6, "you")
    assert len(after) == len(before) - 1


def test_severe_service_switch(signed_in, conn, outback, reads):
    url = _draft_url(_upload(signed_in, outback))
    _post(signed_in, url, _editor(signed_in.get(url).text)["items"])
    assert "so 3 of them apply" in signed_in.get(f"/vehicles/{outback}/schedule").text
    signed_in.post(f"/vehicles/{outback}/schedule/severe", data={"severe": "1"})
    page = signed_in.get(f"/vehicles/{outback}/schedule").text
    assert "follows severe service, so 3 of them apply" in page and "Towing" in page


def test_a_job_never_recorded_counts_from_a_date(signed_in, conn):
    from datetime import date, timedelta

    from schedule_fixtures import steady_car

    from amg.web import schedule_editor

    car, _, _ = steady_car(conn, date.today() - timedelta(days=1000))     # one missed tire rotation
    edit = f"/vehicles/{car}/schedule/edit"
    rows = _editor(signed_in.get(edit).text)["items"]
    fluid = {**schedule_editor.blank_row(), "name": "Washer fluid", "covers": ["washer_fluid"], "interval_months": "3"}
    assert "Add a start date" in signed_in.get(edit).text

    signed_in.post(edit, data={"items_json": json.dumps(rows + [fluid])})
    assert "1 missed in the past" not in signed_in.get(f"/vehicles/{car}").text     # every top-up since new

    rows = _editor(signed_in.get(edit).text)["items"]
    rows[-1].update(counts_from=date.today().isoformat(), show_start=True)
    signed_in.post(edit, data={"items_json": json.dumps(rows)})
    assert "1 missed in the past" in signed_in.get(f"/vehicles/{car}").text
    today = date.today()
    assert f"every 3 months, counting from {today:%b} {today.day}, {today.year}" in signed_in.get(
        f"/vehicles/{car}/schedule").text
