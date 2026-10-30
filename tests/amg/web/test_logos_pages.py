"""Logos on the pages that name a station or shop, the route that serves each icon, and Stations and shops."""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from PIL import Image

from amg.ingest import site_icons
from amg.repo import fuel, logos, services, vehicles
from amg.repo.services import EventInput, LineInput


def png(colour="red"):
    out = BytesIO()
    Image.new("RGBA", (96, 96), colour).save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def fetched(monkeypatch):
    """Every site has an icon: a different red for each, and a count of each fetch."""
    asked = []

    def fetch(site):
        asked.append(site)
        if site == "bp.com":
            return site_icons.Found(None, "")
        return site_icons.Found(png((200, len(asked), 0)), f"https://{site}/favicon.ico")

    monkeypatch.setattr(site_icons, "fetch", fetch)
    return asked


@pytest.fixture
def car(conn):
    return vehicles.create(conn, vehicles.VehicleFields(name="Outback", powertrain="gas"))


def page(client, url):
    return html.unescape(client.get(url).text)


def _service(conn, car, shop, on="2026-09-01", source="shop", confirmed=True):
    return services.create_event(conn, car, EventInput(performed_on=on, source=source, odometer=30_000, shop=shop,
                                                       lines=[LineInput("Oil change")]), confirmed=confirmed)


def test_a_logo_is_fetched_once_kept_and_served_until_it_changes(signed_in, conn, fetched):
    first = signed_in.get("/logos/wawa.com.png")
    assert first.status_code == 200 and first.headers["content-type"] == "image/png"
    assert first.headers["cache-control"] == "private, no-cache" and first.headers["etag"]
    again = signed_in.get("/logos/wawa.com.png", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and fetched == ["wawa.com"]                   # kept, not fetched again
    assert logos.icon(conn, "wawa.com")["source"] == "https://wawa.com/favicon.ico"


def test_a_site_with_no_icon_is_a_404_and_asked_again_after_30_days(signed_in, conn, fetched):
    assert signed_in.get("/logos/bp.com.png").status_code == 404
    assert signed_in.get("/logos/bp.com.png").status_code == 404 and fetched == ["bp.com"]
    long_ago = (datetime.now(timezone.utc) - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("UPDATE site_icons SET fetched_at = ? WHERE site = 'bp.com'", (long_ago,))
    signed_in.get("/logos/bp.com.png")
    assert fetched == ["bp.com", "bp.com"]


def test_only_a_brands_site_or_one_you_gave_is_fetched(signed_in, conn, fetched):
    assert signed_in.get("/logos/example.com.png").status_code == 404
    assert signed_in.get("/logos/..%2Fsecrets.png").status_code == 404
    assert fetched == []
    logos.set_place(conn, "Joe's Garage", "joesgarage.com")
    assert signed_in.get("/logos/joesgarage.com.png").status_code == 200


def test_the_logo_route_needs_signing_in(client, fetched):
    assert client.get("/logos/wawa.com.png", follow_redirects=False).status_code in (303, 401)
    assert fetched == []


def test_fill_ups_and_services_show_their_logos(signed_in, conn, car):
    fuel.create(conn, car, fuel.FillInput("2026-09-02", 30_100, "gas", 10.0, station="Wawa on Route 9"))
    fuel.create(conn, car, fuel.FillInput("2026-09-09", 30_400, "gas", 10.0, station="Joe's Gas"))
    fuel.create(conn, car, fuel.FillInput("2026-09-16", 30_700, "gas", 10.0))
    jiffy = _service(conn, car, "Jiffy Lube #2231")
    _service(conn, car, "", on="2026-08-05", source="diy")

    log = page(signed_in, f"/vehicles/{car}/fuel")
    wawa = '<span class="logo logo--row" aria-hidden="true">W<img src="/logos/wawa.com.png" alt=""'
    assert wawa in log and '<span class="vh">Wawa on Route 9</span>' in log
    assert '<span class="logo logo--row" aria-hidden="true">J</span>' in log            # not recognised: its letter
    assert log.count('<span class="fuellog__logo"></span>') == 1                        # no station, no logo

    car_page = page(signed_in, f"/vehicles/{car}")
    assert ('<span class="ledger__who"><span class="withlogo"><span class="logo logo--row" aria-hidden="true">J'
            '<img src="/logos/jiffylube.com.png"') in car_page
    assert '<span class="withlogo__text">Your own work</span>' in car_page               # no shop, no logo
    garage = page(signed_in, "/")
    assert '<img src="/logos/jiffylube.com.png"' in garage                               # Last service
    assert '<img src="/logos/wawa.com.png"' in page(signed_in, f"/vehicles/{car}/fuel/new")   # the chips
    service = page(signed_in, f"/services/{jiffy}")
    assert '<span class="logo logo--page" aria-hidden="true">J<img src="/logos/jiffylube.com.png"' in service
    assert '<img src="/logos/jiffylube.com.png"' in page(signed_in, "/reports")


def test_stations_and_shops_lists_each_once_and_says_where_its_logo_comes_from(signed_in, conn, car, fetched):
    for day, station in (("2026-09-02", "Wawa"), ("2026-09-09", "WAWA"), ("2026-09-16", "BP #4"),
                         ("2026-09-20", "Joe's Gas")):
        fuel.create(conn, car, fuel.FillInput(day, 30_000 + int(day[-2:]) * 10, "gas", 10.0, station=station))
    _service(conn, car, "Jiffy Lube #2231")
    _service(conn, car, "Not yet confirmed Motors", confirmed=False)
    signed_in.get("/logos/wawa.com.png")
    signed_in.get("/logos/bp.com.png")

    text = page(signed_in, "/places")
    assert 'href="/places" aria-current="page">Stations and shops</a>' in text
    assert text.count('<li class="place"') == 4 and "Not yet confirmed" not in text
    assert "WAWA" in text and "2 fill-ups, the last" in text and "1 service, the last" in text
    assert "Recognised as Wawa. Logo from wawa.com." in text
    assert "Recognised as BP. No icon found for bp.com on " in text and "tried again after 30 days" in text
    assert "Recognised as Jiffy Lube. Its logo comes from jiffylube.com, fetched the first time it's shown." in text
    assert "Not recognised. Give it a logo or its website." in text
    assert 'placeholder="wawa.com"' in text


def test_giving_a_shop_its_website_fetches_its_icon(signed_in, conn, car, fetched):
    fuel.create(conn, car, fuel.FillInput("2026-09-20", 30_200, "gas", 10.0, station="Joe's Gas"))
    response = signed_in.post("/places", data={"name": "Joe's Gas", "website": "https://www.JoesGas.com/hours"},
                              follow_redirects=False)
    assert response.status_code == 303 and fetched == ["joesgas.com"]
    assert logos.places(conn)["joe's gas"]["website"] == "joesgas.com"
    text = page(signed_in, response.headers["location"])
    assert "Saved Joe's Gas." in text and "Logo from joesgas.com." in text and 'value="joesgas.com"' in text
    assert '<img src="/logos/joesgas.com.png"' in page(signed_in, f"/vehicles/{car}/fuel")

    bad = signed_in.post("/places", data={"name": "Joe's Gas", "website": "Joe's place"})
    assert bad.status_code == 422
    assert "Type its website as you'd find it, like joesgarage.com." in html.unescape(bad.text)
    assert logos.places(conn)["joe's gas"]["website"] == "joesgas.com"                  # unchanged


def test_its_letter_instead_and_back_to_the_brand(signed_in, conn, car, fetched):
    fuel.create(conn, car, fuel.FillInput("2026-09-20", 30_200, "gas", 10.0, station="Shell"))
    signed_in.post("/places", data={"name": "shell", "website": "", "letter_only": "1"})
    assert '<img src="/logos/shell.com.png"' not in page(signed_in, f"/vehicles/{car}/fuel")
    assert "Shows its letter, as you asked." in page(signed_in, "/places")
    signed_in.post("/places", data={"name": "Shell", "website": ""})
    assert logos.places(conn) == {}
    assert '<img src="/logos/shell.com.png"' in page(signed_in, f"/vehicles/{car}/fuel")
    assert fetched == []                                                                 # nothing shown yet


def test_fetch_again(signed_in, conn, car, fetched):
    fuel.create(conn, car, fuel.FillInput("2026-09-20", 30_200, "gas", 10.0, station="Shell"))
    signed_in.get("/logos/shell.com.png")
    response = signed_in.post("/places/fetch", data={"site": "shell.com"}, follow_redirects=False)
    assert fetched == ["shell.com", "shell.com"]
    assert "Fetched shell.com's icon again." in page(signed_in, response.headers["location"])
    signed_in.post("/places/fetch", data={"site": "example.com"})                        # not one AMG fetches
    assert fetched == ["shell.com", "shell.com"]


def test_what_you_said_and_what_was_fetched_are_kept(conn, car):
    fuel.create(conn, car, fuel.FillInput("2026-09-02", 30_100, "gas", 10.0, station="Costco"))
    fuel.create(conn, car, fuel.FillInput("2026-09-09", 30_400, "gas", 10.0, station="costco"))
    _service(conn, car, "Costco Tire Center")
    stations, shops = logos.visited(conn)
    assert [(s["name"], s["visits"], s["last"]) for s in stations] == [("costco", 2, "2026-09-09")]
    assert [s["name"] for s in shops] == ["Costco Tire Center"]
    logos.keep(conn, "costco.com", None)
    assert logos.due(logos.icon(conn, "costco.com")) is False                              # nothing, just now
    assert logos.due(logos.icon(conn, "costco.com"), datetime.now(timezone.utc) + timedelta(days=31)) is True
    logos.keep(conn, "costco.com", png(), "https://www.costco.com/apple-touch-icon.png")
    assert logos.due(logos.icon(conn, "costco.com"), datetime.now(timezone.utc) + timedelta(days=400)) is False
    logos.forget(conn, "costco.com")
    assert logos.due(logos.icon(conn, "costco.com")) is True


# ---------- Logos you upload ----------


def _upload(client, name, colour="green", filename="logo.png", **data):
    return client.post("/places", data={"name": name, "website": "", **data},
                       files=[("logo_file", (filename, png(colour), "image/png"))], follow_redirects=False)


def _shown(conn, document_id):
    from amg.repo import documents

    sha = documents.get(conn, document_id)["sha256"]
    return f'<img src="/documents/{document_id}/pages/1?v={sha[:12]}&size=thumb"'


def test_a_logo_uploaded_for_a_brand_covers_every_station_of_it(signed_in, conn, car, fetched):
    fuel.create(conn, car, fuel.FillInput("2026-09-02", 30_100, "gas", 10.0, station="BP #4"))
    fuel.create(conn, car, fuel.FillInput("2026-09-09", 30_400, "gas", 10.0, station="BP Route 9"))
    assert "For every BP station or shop. PNG, JPG or GIF." in page(signed_in, "/places")
    response = _upload(signed_in, "BP #4")
    assert response.status_code == 303 and "Saved BP #4." in page(signed_in, response.headers["location"])
    mine = logos.brand_logos(conn)["BP"]["document_id"]
    fuel_page = page(signed_in, f"/vehicles/{car}/fuel")
    log = fuel_page.split('id="log-heading"', 1)[1]
    assert log.count(_shown(conn, mine)) == 2 and "/logos/bp.com.png" not in fuel_page  # both, and nothing fetched
    text = page(signed_in, "/places")
    assert text.count("Recognised as BP. Your logo, for every BP.") == 2
    assert "Remove your logo for every BP" in text and fetched == []
    assert logos.places(conn) == {}                                                   # nothing about "BP #4" itself


def test_a_logo_for_a_name_amg_doesnt_know_is_for_that_name(signed_in, conn, car, fetched):
    fuel.create(conn, car, fuel.FillInput("2026-09-02", 30_100, "gas", 10.0, station="Joe's Gas"))
    fuel.create(conn, car, fuel.FillInput("2026-09-09", 30_400, "gas", 10.0, station="Joe's Garage"))
    assert "For Joe's Gas. PNG, JPG or GIF." in page(signed_in, "/places")
    _upload(signed_in, "Joe's Gas")
    mine = logos.places(conn)["joe's gas"]["logo_document_id"]
    log = page(signed_in, f"/vehicles/{car}/fuel").split('id="log-heading"', 1)[1]
    assert log.count(_shown(conn, mine)) == 1 and "Your logo." in page(signed_in, "/places")
    assert '<span class="logo logo--row" aria-hidden="true">J</span>' in log            # Joe's Garage: its letter


def test_which_logo_wins(signed_in, conn, car, fetched):
    from amg.repo import documents

    for n, station in enumerate(("Shell", "Shell Route 9", "Shell on Main")):
        fuel.create(conn, car, fuel.FillInput(f"2026-09-0{n + 1}", 30_000 + n * 300, "gas", 10.0, station=station))
    _upload(signed_in, "Shell", "green")                                              # every Shell
    brand = logos.brand_logos(conn)["Shell"]["document_id"]
    own, _ = documents.store(conn, png("blue"), "corner.png")
    logos.set_logo(conn, "Shell Route 9", own["id"])                                  # this one's own
    signed_in.post("/places", data={"name": "Shell on Main", "website": "", "letter_only": "1"})
    log = page(signed_in, f"/vehicles/{car}/fuel").split('id="log-heading"', 1)[1]      # the log, a row a fill
    assert log.count(_shown(conn, brand)) == 1 and log.count(_shown(conn, own["id"])) == 1
    assert '<span class="logo logo--row" aria-hidden="true">S</span>' in log           # its letter, as asked
    assert "/logos/shell.com.png" not in log                                          # your logo beats the fetched one

    # A name you gave its own website is a place of its own: a logo picked there is for it alone.
    signed_in.post("/places", data={"name": "Shell on Main", "website": "shellonmain.com"})
    _upload(signed_in, "Shell on Main", "red", website="shellonmain.com")
    assert logos.places(conn)["shell on main"]["logo_document_id"] is not None
    assert logos.brand_logos(conn)["Shell"]["document_id"] == brand

    # Picking a logo while "Show the letter instead" is ticked: the logo is what you meant.
    _upload(signed_in, "Shell Route 9", "yellow", letter_only="1")
    assert logos.places(conn)["shell route 9"]["letter_only"] == 0


def test_removing_your_logo_goes_back_to_the_fetched_icon(signed_in, conn, car, fetched):
    fuel.create(conn, car, fuel.FillInput("2026-09-02", 30_100, "gas", 10.0, station="BP #4"))
    _upload(signed_in, "BP #4")
    signed_in.post("/places", data={"name": "BP #4", "website": "", "remove_logo": "1"})
    assert logos.brand_logos(conn) == {}
    assert '<img src="/logos/bp.com.png"' in page(signed_in, f"/vehicles/{car}/fuel")


def test_only_a_picture_is_taken(signed_in, conn, car, fetched):
    fuel.create(conn, car, fuel.FillInput("2026-09-02", 30_100, "gas", 10.0, station="Joe's Gas"))
    response = signed_in.post("/places", data={"name": "Joe's Gas", "website": ""},
                              files=[("logo_file", ("brochure.pdf", b"%PDF-1.4", "application/pdf"))])
    assert response.status_code == 422
    text = html.unescape(response.text)
    assert "brochure.pdf: add the logo as PNG, JPG or GIF." in text and 'aria-expanded="true"' in text
    assert logos.places(conn) == {} and logos.uploads(conn) == []


def test_add_a_station_or_shop_before_your_first_visit(signed_in, conn, car, fetched):
    assert "Add a station or shop" in page(signed_in, "/places")
    nothing = signed_in.post("/places/add", data={"name": "Joe's Garage", "website": ""})
    assert nothing.status_code == 422 and "Give it a logo, or its website." in html.unescape(nothing.text)
    unnamed = signed_in.post("/places/add", data={"name": " ", "website": "joesgarage.com"})
    assert "Name the station or shop" in html.unescape(unnamed.text)

    response = signed_in.post("/places/add", data={"name": "Joe's Garage", "website": ""},
                              files=[("logo_file", ("joes.png", png("navy"), "image/png"))], follow_redirects=False)
    assert response.status_code == 303
    text = page(signed_in, response.headers["location"])
    assert "Added Joe's Garage." in text and "Not visited yet" in text and "Your logo." in text
    signed_in.post("/places/add", data={"name": "Pep Boys", "website": ""},
                   files=[("logo_file", ("pep.png", png("red"), "image/png"))])
    assert "Pep Boys" in logos.brand_logos(conn)                                      # a brand: every Pep Boys
    assert page(signed_in, "/places").count('<li class="place" id="new-') == 2

    _service(conn, car, "Joe's Garage")                                               # the first visit
    text = page(signed_in, "/places")
    assert text.count('<li class="place" id="new-') == 1 and '<li class="place" id="shop-1"' in text
    mine = logos.places(conn)["joe's garage"]["logo_document_id"]
    assert _shown(conn, mine) in page(signed_in, f"/vehicles/{car}")                  # in its service history
