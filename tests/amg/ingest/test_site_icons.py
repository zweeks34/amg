"""Fetching a website's icon: what the home page declares, the usual places, then the icon service; only pictures."""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from amg.ingest import site_icons
from amg.ingest.site_icons import Answer, Blocked


def picture(size=(32, 32), kind="PNG", colour="red"):
    out = BytesIO()
    Image.new("RGB", size, colour).save(out, kind, **({"sizes": [(16, 16), (48, 48)]} if kind == "ICO" else {}))
    return out.getvalue()


class Sites:
    """A pretend internet: each address's answer, and every address asked."""

    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    def __call__(self, url):
        self.asked.append(url)
        answer = self.answers.get(url)
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            return Answer(404, "text/html", b"<h1>Not found</h1>", url)
        status, kind, body = answer
        return Answer(status, kind, body, url)


HOME = b"""<!doctype html><html><head>
<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">
<link rel="mask-icon" href="/safari-pinned-tab.svg" color="#c00">
<link rel="shortcut icon" href="/favicon.ico">
<link rel="icon" type="image/svg+xml" href="/icon.svg">
<link rel="apple-touch-icon" href="https://cdn.example.com/touch.png">
<link rel="icon" sizes="192x192" href="//cdn.example.com/icon-192.png">
<link rel="icon" href="http://insecure.example.com/old.png">
</head></html>"""


def test_the_home_pages_icons_largest_first_and_only_https():
    assert site_icons.declared(HOME, "https://www.wawa.com/") == [
        "https://cdn.example.com/icon-192.png",       # sizes 192x192
        "https://cdn.example.com/touch.png",          # a phone's: 180
        "https://www.wawa.com/icon.svg",              # a drawing: above every small one
        "https://www.wawa.com/favicon-16x16.png",
        "https://www.wawa.com/favicon.ico",
    ]                                                   # no mask icon, nothing over plain HTTP


def test_the_first_answer_that_is_a_picture_wins():
    sites = Sites({
        "https://wawa.com/": (200, "text/html", HOME),
        "https://cdn.example.com/icon-192.png": (200, "text/html", b"<html>moved</html>"),   # "200", but a page
        "https://cdn.example.com/touch.png": (200, "image/png", picture((180, 180))),
    })
    found = site_icons.fetch("wawa.com", get=sites)
    assert found.source == "https://cdn.example.com/touch.png"
    image = Image.open(BytesIO(found.png))
    assert (image.format, image.size, image.mode) == ("PNG", (96, 96), "RGBA")
    assert "https://icons.duckduckgo.com/ip3/wawa.com.ico" not in sites.asked


def test_a_site_that_turns_amg_away_is_asked_of_the_icon_service():
    sites = Sites({
        "https://marathonbrand.com/": (403, "text/html", b"Access denied"),
        "https://marathonbrand.com/apple-touch-icon.png": (403, "", b""),
        "https://marathonbrand.com/favicon.ico": (403, "", b""),
        "https://icons.duckduckgo.com/ip3/marathonbrand.com.ico": (200, "image/x-icon", picture(kind="ICO")),
    })
    found = site_icons.fetch("marathonbrand.com", get=sites)
    assert found.source == "https://icons.duckduckgo.com/ip3/marathonbrand.com.ico"
    assert Image.open(BytesIO(found.png)).size == (96, 96)
    assert sites.asked == ["https://marathonbrand.com/", "https://marathonbrand.com/apple-touch-icon.png",
                           "https://marathonbrand.com/favicon.ico",
                           "https://icons.duckduckgo.com/ip3/marathonbrand.com.ico"]


def test_no_icon_anywhere_is_none_and_a_dead_site_is_tried_with_www():
    sites = Sites({"https://bp.com/": OSError("connection refused"), "https://www.bp.com/": (403, "", b"")})
    assert site_icons.fetch("bp.com", get=sites) == site_icons.Found(None, "")
    assert sites.asked[:2] == ["https://bp.com/", "https://www.bp.com/"]
    assert sites.asked[-1] == "https://icons.duckduckgo.com/ip3/bp.com.ico"


def test_a_slow_site_gets_its_time_and_then_the_service():
    ticks = iter(range(0, 1000, 10))                   # every look at the clock, 10 seconds on
    sites = Sites({"https://slow.com/": (200, "text/html", HOME)})
    site_icons.fetch("slow.com", get=sites, clock=lambda: next(ticks))
    assert len(sites.asked) == 3                       # the page, one icon, then out of time: the service
    assert sites.asked[-1] == "https://icons.duckduckgo.com/ip3/slow.com.ico"


def test_an_icon_written_into_the_page_is_read_from_it():
    import base64

    inline = b'<link rel="icon" href="data:image/png;base64,' + base64.b64encode(picture()) + b'">'
    found = site_icons.fetch("inline.com", get=Sites({"https://inline.com/": (200, "text/html", inline)}))
    assert found.png and found.source == "https://inline.com/"


def test_pictures_are_made_96px_squares_and_specks_and_pages_refused():
    wide = Image.open(BytesIO(site_icons.picture(picture((64, 32)))))
    assert wide.size == (96, 96)
    assert wide.getpixel((48, 10))[3] == 0 and wide.getpixel((48, 48))[3] == 255      # centred on a clear ground
    ico = Image.open(BytesIO(site_icons.picture(picture(kind="ICO"), "image/x-icon")))
    assert ico.size == (96, 96)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="5" fill="#c00"/></svg>'
    drawn = Image.open(BytesIO(site_icons.picture(svg, "image/svg+xml")))
    assert drawn.size == (96, 96) and drawn.getpixel((48, 48))[:3] == (204, 0, 0)
    assert site_icons.picture(picture((1, 1))) is None                                  # a tracking pixel
    assert site_icons.picture(b"<!doctype html><title>Home</title>") is None


@pytest.mark.parametrize(("typed", "kept"), [
    ("https://www.JoesGarage.com/about", "joesgarage.com"),
    ("joesgarage.com", "joesgarage.com"),
    ("  www.bobs-auto.net  ", "bobs-auto.net"),
    ("shop.example.co.uk:8443/x", "shop.example.co.uk"),
    ("Joe's Garage", None),
    ("localhost", None),
    ("http://192.168.1.10", None),
    ("", None),
])
def test_a_website_as_typed_and_as_kept(typed, kept):
    assert site_icons.site_of(typed) == kept


@pytest.mark.parametrize("url", ["http://wawa.com/", "https://localhost/", "https://127.0.0.1/", "https://10.0.0.5/",
                                 "https://192.168.1.10/favicon.ico", "https://[::1]/"])
def test_nothing_on_your_home_network_or_over_plain_http(url):
    with pytest.raises(Blocked):
        site_icons._check(url)


def test_only_a_website_is_fetched():
    with pytest.raises(ValueError):
        site_icons.fetch("not a site", get=Sites({}))
