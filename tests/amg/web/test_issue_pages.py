"""Issues on the car's page, the service's page and the garage: noting one with photos, the question a
later visit asks, and closing, dropping and reopening. Then the sheet for the shop."""

from __future__ import annotations

import hashlib
import html
from datetime import date, timedelta
from io import BytesIO

import pytest
import report_fixtures as rf  # tests/ is on pytest's path
from PIL import Image
from schedule_fixtures import steady_car

from amg.repo import documents, issues, odometer, vehicles
from amg.repo.issues import IssueInput
from amg.web import status
from amg.web.recalls import day_words


@pytest.fixture
def car(conn):
    return rf.car(conn, "Civic", year=2019, make="Honda", model="Civic")


def png(colour="red"):
    out = BytesIO()
    Image.new("RGB", (60, 40), colour).save(out, "PNG")
    return out.getvalue()


def stored(conn, colour):
    return documents.store(conn, png(colour), f"{colour}.png")[0]["id"]


def page(signed_in, url):
    return html.unescape(signed_in.get(url).text)


def _note(signed_in, car, files=(), **fields):
    data = {"title": "Rattle at 40 mph", "details": "", "noticed_on": "2025-09-02", **fields}
    return signed_in.post(f"/vehicles/{car}/issues", data=data, files=list(files), follow_redirects=False)


# ---------- Noting one ----------


def test_the_empty_section_and_the_form(signed_in, car):
    text = page(signed_in, f"/vehicles/{car}")
    assert 'id="issues"' in text and "No open issues." in text and f'href="/vehicles/{car}/issues/new"' in text
    form = page(signed_in, f"/vehicles/{car}/issues/new")
    assert "Note an issue" in form and "What's wrong" in form and "Take a photo" in form and "Save issue" in form
    assert f'value="{date.today().isoformat()}"' in form


def test_noting_one_with_photos(signed_in, conn, car):
    odometer.add(conn, car, "2025-08-01", 91_000)
    odometer.add(conn, car, "2025-10-01", 93_000)
    jpeg = BytesIO()
    Image.new("RGB", (60, 40), "blue").save(jpeg, "JPEG")
    response = _note(signed_in, car, details="From the front.\nWarm or cold.",
                     files=[("photos", ("leak.jpg", jpeg.getvalue(), "image/jpeg")),
                            ("photos", ("IMG_0001.png", png(), "image/png"))])
    assert response.status_code == 303 and response.headers["location"] == f"/vehicles/{car}#issues"
    [issue] = issues.for_car(conn, car)
    assert [p["filename"] for p in issue["photos"]] == ["leak.jpg", "IMG_0001.png"]
    text = page(signed_in, f"/vehicles/{car}")
    assert "Rattle at 40 mph" in text and "Noticed Sep 2, 2025, at about 92,000 mi" in text
    assert "From the front.\nWarm or cold." in text
    assert text.count("size=thumb") == 2 and "Photo 2 of Rattle at 40 mph" in text
    assert "1 issue</li>" in page(signed_in, "/")


def test_what_the_form_refuses(signed_in, conn, car):
    cases = [
        ({"title": ""}, [], "Say what's wrong, such as Rattle at 40 mph."),
        ({"title": "x" * 121}, [], "Keep it under 120 characters. The details can say more."),
        ({"details": "x" * 2001}, [], "Keep the details under 2,000 characters."),
        ({"noticed_on": (date.today() + timedelta(days=1)).isoformat()}, [], "That date is in the future."),
        ({}, [("photos", ("invoice.pdf", rf.pdf_bytes("NOT A PHOTO"), "application/pdf"))],
         "invoice.pdf: add photos as PNG, JPG or GIF."),
        ({}, [("photos", (f"{n}.png", png(f"#{n:02x}0000"), "image/png")) for n in range(11)],
         "An issue holds up to 10 photos. Remove 1."),
    ]
    for fields, files, message in cases:
        response = _note(signed_in, car, files=files, **fields)
        assert response.status_code == 422 and message in html.unescape(response.text), message
    assert issues.for_car(conn, car) == []


def test_photos_stay_when_the_form_comes_back(signed_in, conn, car):
    response = _note(signed_in, car, title="", files=[("photos", ("leak.png", png(), "image/png"))])
    kept = documents.by_sha(conn, hashlib.sha256(png()).hexdigest())["id"]
    assert response.status_code == 422 and f'name="photo" value="{kept}"' in response.text
    _note(signed_in, car, photo=str(kept))
    assert [p["id"] for p in issues.for_car(conn, car)[0]["photos"]] == [kept]


def test_edit_removes_a_photo_and_delete(signed_in, conn, car):
    red, green = stored(conn, "red"), stored(conn, "green")
    issue = issues.create(conn, car, IssueInput("Rattle", "", "2025-09-02"), [red, green])
    form = page(signed_in, f"/issues/{issue}/edit")
    assert "Edit issue" in form and f'name="photo" value="{red}"' in form and f'name="photo" value="{green}"' in form
    response = signed_in.post(f"/issues/{issue}/edit", data={"title": "Rattle at 45 mph", "details": "",
                                                             "noticed_on": "2025-09-03", "photo": str(green)},
                              follow_redirects=False)
    assert response.headers["location"] == f"/vehicles/{car}#issues"
    row = issues.get(conn, issue)
    assert (row["title"], row["noticed_on"], [p["id"] for p in row["photos"]]) == ("Rattle at 45 mph", "2025-09-03",
                                                                                 [green])
    response = signed_in.post(f"/issues/{issue}/delete", follow_redirects=False)
    assert response.headers["location"] == f"/vehicles/{car}#issues" and issues.get(conn, issue) is None


# ---------- What became of it ----------


def test_a_later_visit_asks_and_still_there_is_kept(signed_in, conn, car):
    _note(signed_in, car)
    [issue] = issues.for_car(conn, car)
    rf.visit(conn, car, "2025-08-20", shop="Midas", lines=[rf.line("Oil", 5_000)])       # before: never asked
    assert "fix it" not in page(signed_in, f"/vehicles/{car}")
    looked = rf.visit(conn, car, "2025-09-20", shop="Valley Honda", lines=[rf.line("Looked for rattle", 0)])
    text = page(signed_in, f"/vehicles/{car}")
    assert "Did Valley Honda fix it on Sep 20, 2025?" in text and "Yes, fixed then" in text
    assert f'<option value="{looked}">2025-09-20 · Valley Honda</option>' in text
    signed_in.post(f"/issues/{issue['id']}/still-there", data={"service_event_id": str(looked)})
    text = page(signed_in, f"/vehicles/{car}")
    assert "Still there after Valley Honda on Sep 20, 2025." in text and "fix it on" not in text

    mine = rf.visit(conn, car, "2025-10-01", source="diy", lines=[rf.line("Heat shield clamp", 500, kind="part")])
    assert "Did your work on Oct 1, 2025 fix it?" in page(signed_in, f"/vehicles/{car}")
    response = signed_in.post(f"/issues/{issue['id']}/fixed", data={"service_event_id": str(mine)},
                              follow_redirects=False)
    assert response.headers["location"] == f"/vehicles/{car}#issues"
    text = page(signed_in, f"/vehicles/{car}")
    assert "1 fixed or dropped" in text and f'<a href="/services/{mine}">Fixed Oct 1, 2025 by you</a>' in text
    assert "No open issues." in text


def test_still_there_takes_only_the_cars_visits(signed_in, conn, car):
    _note(signed_in, car)
    [issue] = issues.for_car(conn, car)
    elsewhere = rf.visit(conn, rf.car(conn, "Outback"), "2025-09-20", shop="Midas", lines=[rf.line("Oil", 5_000)])
    signed_in.post(f"/issues/{issue['id']}/still-there", data={"service_event_id": str(elsewhere)})
    assert issues.get(conn, issue["id"])["checks"] == []


def test_its_fixed_on_a_date_and_not_before_it_was_noticed(signed_in, conn, car):
    _note(signed_in, car)
    [issue] = issues.for_car(conn, car)
    response = signed_in.post(f"/issues/{issue['id']}/fixed", data={"service_event_id": "", "fixed_on": "2025-08-01"})
    assert response.status_code == 422
    text = html.unescape(response.text)
    assert "That's before you noticed it, on Sep 2, 2025." in text and 'aria-invalid="true"' in text
    assert issues.get(conn, issue["id"])["status"] == "open"
    signed_in.post(f"/issues/{issue['id']}/fixed", data={"service_event_id": "", "fixed_on": "2025-09-10"})
    assert "Fixed Sep 10, 2025" in page(signed_in, f"/vehicles/{car}")


def test_drop_and_undo(signed_in, conn, car):
    _note(signed_in, car)
    [issue] = issues.for_car(conn, car)
    signed_in.post(f"/issues/{issue['id']}/drop")
    assert f"Dropped {day_words(date.today().isoformat())}" in page(signed_in, f"/vehicles/{car}")
    assert "issue</li>" not in page(signed_in, "/")
    signed_in.post(f"/issues/{issue['id']}/reopen")
    assert issues.get(conn, issue["id"])["status"] == "open" and "fixed or dropped" not in page(signed_in,
                                                                                              f"/vehicles/{car}")


def test_the_service_page_asks_about_itself(signed_in, conn, car):
    _note(signed_in, car)
    _note(signed_in, car, title="Squeak over bumps", noticed_on="2025-09-25")
    rattle, squeak = sorted(issues.for_car(conn, car), key=lambda r: r["id"])
    visit = rf.visit(conn, car, "2025-09-20", shop="Valley Honda", lines=[rf.line("Clamp", 4_000)])
    text = page(signed_in, f"/services/{visit}")
    assert "Your issues" in text and "Did this visit fix it?" in text
    assert "Rattle at 40 mph" in text and "Squeak over bumps" not in text      # noticed after this visit
    assert '<input type="hidden" name="back" value="service">' in text
    response = signed_in.post(f"/issues/{rattle['id']}/fixed",
                              data={"service_event_id": str(visit), "back": "service"}, follow_redirects=False)
    assert response.headers["location"] == f"/services/{visit}#issues"
    text = page(signed_in, f"/services/{visit}")
    assert "Fixed on this visit" in text and "Did this visit fix it?" not in text
    assert issues.get(conn, squeak["id"])["status"] == "open"


def test_a_service_with_nothing_to_ask_says_nothing(signed_in, conn, car):
    visit = rf.visit(conn, car, "2025-09-20", shop="Valley Honda", lines=[rf.line("Oil", 5_000)])
    assert "Your issues" not in page(signed_in, f"/services/{visit}")


def test_the_garage_counts_open_ones(signed_in, conn, car):
    for title in ("Rattle", "Squeak"):
        issues.create(conn, car, IssueInput(title, "", "2025-09-02"))
    assert "2 issues</li>" in page(signed_in, "/")


def test_an_unknown_issue_is_a_404(signed_in):
    assert signed_in.get("/issues/999/edit").status_code == 404
    assert signed_in.post("/issues/999/drop").status_code == 404


# ---------- The sheet for the shop ----------


def sheet(signed_in, car):
    """The sheet itself, without the page around it."""
    return page(signed_in, f"/vehicles/{car}/for-the-shop").split('<article class="sheet shopsheet">')[1]         .split("</article>")[0]


def test_the_sheet_has_the_car_and_your_open_issues_numbered(signed_in, conn):
    car = rf.car(conn, "Civic", year=2019, make="Honda", model="Civic", trim="EX", engine="2.0L 4-cyl",
                 vin="2HGFC2F59KH000001", plate="ABC 123")
    odometer.add(conn, car, date.today().isoformat(), 95_000)
    looked = rf.visit(conn, car, "2025-09-20", shop="Valley Honda", lines=[rf.line("Looked for rattle", 0)])
    rattle = issues.create(conn, car, IssueInput("Rattle at 40 mph", "From the front", "2025-09-02"),
                           [stored(conn, "red")])
    issues.still_there(conn, rattle, looked)
    issues.create(conn, car, IssueInput("Squeak over bumps", "", "2025-10-01"))
    issues.drop(conn, issues.create(conn, car, IssueInput("Smell of fuel", "", "2025-08-01")), "2025-08-10")

    assert f'href="/vehicles/{car}/for-the-shop"' in page(signed_in, f"/vehicles/{car}")
    text = sheet(signed_in, car)
    assert "2019 Honda Civic EX" in text and "2.0L 4-cyl" in text and "2HGFC2F59KH000001" in text
    assert "ABC 123" in text and "95,000 mi today" in text
    assert "Please look at" in text and text.index("Squeak over bumps") < text.index("Rattle at 40 mph")
    assert "From the front" in text and "Still there after Valley Honda on Sep 20, 2025." in text
    assert "size=thumb" in text and "Smell of fuel" not in text
    assert f"From AMG, {day_words(date.today().isoformat())}." in text
    assert "Print" in page(signed_in, f"/vehicles/{car}/for-the-shop")


def test_the_sheets_odometer(signed_in, conn):
    car = rf.car(conn, "Civic")
    odometer.add(conn, car, "2025-08-01", 91_000)
    assert "91,000 mi on Aug 1, 2025" in sheet(signed_in, car)            # one reading: no pace to estimate by
    odometer.add(conn, car, (date.today() - timedelta(days=30)).isoformat(), 95_000)
    assert "about " in sheet(signed_in, car) and " mi today" in sheet(signed_in, car)


def test_the_sheet_lists_only_whats_due_now_and_no_prices(signed_in, conn):
    car, _, _ = steady_car(conn, date.today() - timedelta(days=1000))
    every = status.next_up(status.load(conn, vehicles.get(conn, car)))
    urgent = [row["name"] for row in every if row["status"] in ("overdue", "due")]
    later = [row["name"] for row in every if row["status"] == "later"]
    assert urgent and later
    text = sheet(signed_in, car)
    assert "Due now" in text and all(name in text for name in urgent)
    assert not any(name in text for name in later) and "mi overdue" in text
    assert "$" not in text
    for name in ("Cabin air filter", "Engine oil and filter"):          # what to do to each, before its name
        assert f'<span class="actword shopsheet__action">Replace</span> {name}</span>' in text


def test_the_sheet_lists_recent_open_recommendations(signed_in, conn):
    car = rf.car(conn, "Civic")
    recent = (date.today() - timedelta(days=30)).isoformat()
    rf.receipt(conn, car, rf.pdf_bytes("RECENT"), "recent.pdf", date=recent, shop_name="Valley Honda", odometer=None)
    rf.receipt(conn, car, rf.pdf_bytes("OLD"), "old.pdf", date="2022-03-01", shop_name="Midas", odometer=None)
    text = sheet(signed_in, car)
    assert "Recommended before" in text and "Brake fluid flush" in text
    assert f"Valley Honda, {day_words(recent)}" in text and "Midas" not in text
    assert "$" not in text and "129.95" not in text


def test_a_sheet_with_nothing_to_ask_for_says_so(signed_in, conn):
    car = rf.car(conn, "Civic")
    text = sheet(signed_in, car)
    assert "Nothing to ask for: no open issues, nothing due, and no open shop recommendations." in text
    assert "Please look at" not in text and "Due now" not in text and "Recommended before" not in text
