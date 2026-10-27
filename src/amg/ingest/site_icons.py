"""A website's icon, for the logo of a station or shop.

Asked for in this order; the first answer that opens as a picture wins:

1. the icons the site's home page declares, largest first: its
   apple-touch-icon (180px, made for a phone's home screen), then by the
   sizes it gives;
2. ``/apple-touch-icon.png`` and ``/favicon.ico``, where sites keep them by
   habit;
3. DuckDuckGo's public icon service, for the sites that turn a script away
   (Wawa, Marathon and Firestone did, in October 2026). It learns the site's
   name and nothing else.

Every request is HTTPS, to an address on the public internet (never one on
your home network, so a page can't point AMG inside your LAN), with 5 seconds
and 1 MB to answer. Whatever comes back has to open as a picture: some sites
answer a missing icon with a web page and "200". The picture is made a 96px
square PNG on a clear ground, which is what ``site_icons`` keeps.
"""

from __future__ import annotations

import base64
import http.client
import ipaddress
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO

import pymupdf
from PIL import Image

USER_AGENT = "AMG/1.0 (a home car-maintenance app, fetching a site icon for a logo)"
TIMEOUT = 5.0           # seconds, each request
LIMIT = 1_000_000       # bytes, each answer
BUDGET = 15.0           # seconds on the site itself before asking the service
SIZE = 96               # the PNG kept: 24px tiles, sharp up to 4x
SERVICE = "https://icons.duckduckgo.com/ip3/{site}.ico"

# A website as AMG keeps it: a lowercase host name with no "www.", "wawa.com".
SITE = re.compile(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


class Blocked(ValueError):
    """An address AMG won't fetch: not HTTPS, or not on the public internet."""


@dataclass(frozen=True)
class Answer:
    status: int
    type: str           # its media type, "image/png"
    body: bytes
    url: str            # where it came from, after any redirects


@dataclass(frozen=True)
class Found:
    png: bytes | None   # None: no icon anywhere
    source: str         # the address it came from


Get = Callable[[str], Answer]


def site_of(text: str) -> str | None:
    """A website as typed, "https://www.JoesGarage.com/about", as AMG keeps it: "joesgarage.com". None if it isn't one."""
    text = (text or "").strip().lower()
    if not text:
        return None
    host = urllib.parse.urlsplit(text if "//" in text else "//" + text).hostname or ""
    host = host.removeprefix("www.").rstrip(".")
    return host if SITE.fullmatch(host) else None


# ---------- Asking ----------


def _check(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise Blocked(f"Not an HTTPS address: {url}")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as err:
        raise Blocked(f"No such site: {parts.hostname}") from err
    if not all(ipaddress.ip_address(address.split("%")[0]).is_global for address in addresses):
        raise Blocked(f"Not on the public internet: {parts.hostname}")


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to where a first request could have gone."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url: str) -> Answer:
    """One request, as the fetch makes them; a refusal ("403") is an answer, not an error. Tests replace it."""
    _check(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*, text/html, */*;q=0.5"})
    try:
        with urllib.request.build_opener(_Redirects).open(request, timeout=TIMEOUT) as response:
            body = response.read(LIMIT + 1)
            return Answer(response.status, response.headers.get_content_type(), body if len(body) <= LIMIT else b"",
                          response.geturl())
    except urllib.error.HTTPError as err:
        return Answer(err.code, "", b"", url)


def _ask(get: Get, url: str) -> Answer | None:
    try:
        return get(url)
    except (OSError, ValueError, http.client.HTTPException):    # no answer, a timeout, a refused address
        return None


# ---------- The home page's icons ----------


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "link":
            return
        found = {key.lower(): (value or "").strip() for key, value in attrs}
        rel = found.get("rel", "").lower().split()
        if found.get("href") and ("icon" in rel or any(r.startswith("apple-touch-icon") for r in rel)):
            self.found.append(found)


def _size(link: dict[str, str]) -> int:
    """How big an icon says it is: its sizes, 180 for a phone's, 100 for a drawing (above every small one)."""
    sizes = [int(w) for w, _ in re.findall(r"(\d+)x(\d+)", link.get("sizes", "").lower())]
    if sizes:
        return max(sizes)
    if any(r.startswith("apple-touch-icon") for r in link["rel"].lower().split()):
        return 180
    if link.get("type", "").lower() == "image/svg+xml" or link["href"].lower().split("?")[0].endswith(".svg"):
        return 100
    return 16


def declared(page: bytes, base: str) -> list[str]:
    """The icons a home page names, largest first, as full HTTPS (or data:) addresses."""
    parser = _Links()
    try:
        parser.feed(page.decode("utf-8", errors="replace"))
    except AssertionError:                  # HTMLParser on badly broken markup
        pass
    ranked = sorted(parser.found, key=_size, reverse=True)
    urls = []
    for link in ranked:
        url = link["href"] if link["href"].startswith("data:") else urllib.parse.urljoin(base, link["href"])
        if (url.startswith("https://") or url.startswith("data:image/")) and url not in urls:
            urls.append(url)
    return urls


# ---------- Making it a PNG ----------


def _is_svg(data: bytes, kind: str) -> bool:
    head = data[:512].lstrip().lower()
    return kind == "image/svg+xml" or head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head)


def _svg(data: bytes) -> Image.Image:
    with pymupdf.open(stream=data, filetype="svg") as doc:
        page = doc[0]
        zoom = SIZE * 2 / max(page.rect.width, page.rect.height, 1)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
        return Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)


def picture(data: bytes, kind: str = "") -> bytes | None:
    """An icon as a 96px square PNG, centred on a clear ground; None when it isn't a picture, or is a speck."""
    try:
        if _is_svg(data, kind):
            image = _svg(data)
        else:
            image = Image.open(BytesIO(data))
            image.load()                    # an ICO opens at its largest size
    except Exception:                       # not a picture, or one Pillow or MuPDF can't read: no icon from here
        return None
    if min(image.size) < 8:
        return None
    image = image.convert("RGBA")
    scale = SIZE / max(image.size)
    image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.LANCZOS)
    square = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    square.paste(image, ((SIZE - image.width) // 2, (SIZE - image.height) // 2))
    out = BytesIO()
    square.save(out, "PNG", optimize=True)
    return out.getvalue()


def _picture_at(get: Get, url: str) -> bytes | None:
    if url.startswith("data:"):
        head, _, payload = url.partition(",")
        try:
            data = base64.b64decode(payload) if head.endswith(";base64") else urllib.parse.unquote_to_bytes(payload)
        except ValueError:
            return None
        return picture(data, head[5:].split(";")[0])
    answer = _ask(get, url)
    if answer is None or answer.status != 200 or not answer.body:
        return None
    return picture(answer.body, answer.type)


# ---------- The whole fetch ----------


def fetch(site: str, get: Get | None = None, clock: Callable[[], float] = time.monotonic) -> Found:
    """A site's icon, from the site itself or else the icon service; Found(None, "") when neither has one."""
    if not SITE.fullmatch(site):
        raise ValueError(f"Not a website: {site!r}")
    get = get or _get
    deadline = clock() + BUDGET
    page = _ask(get, f"https://{site}/") or _ask(get, f"https://www.{site}/")
    base = page.url if page else f"https://{site}/"
    urls = declared(page.body, base) if page and page.status == 200 and "html" in page.type else []
    urls += [urllib.parse.urljoin(base, "/apple-touch-icon.png"), urllib.parse.urljoin(base, "/favicon.ico")]
    tried: set[str] = set()
    for url in urls:
        if url in tried or clock() > deadline:
            continue
        tried.add(url)
        if png := _picture_at(get, url):
            return Found(png, url if not url.startswith("data:") else base)
    service = SERVICE.format(site=site)
    if png := _picture_at(get, service):
        return Found(png, service)
    return Found(None, "")
