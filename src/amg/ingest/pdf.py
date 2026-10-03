"""An uploaded file as pages: PDF, PNG, JPG or GIF.

PyMuPDF opens an image as a one-page document, so every format goes through
the same two calls — the page's own text layer, and the page rendered as an
image — and nothing downstream needs to know which kind of file it was.

Rendering is to a target long edge in pixels, not a DPI, because the two
consumers want different sizes regardless of how the file was scanned:

* VISION_LONG_EDGE — what Claude is sent. Opus 5.5 reads up to 2576px on the
  long edge and 3.75 megapixels; a letter page at 2200px tall is 1700×2200,
  just under that, so nothing is lost to the API's own downscaling.
* OCR_LONG_EDGE — what Tesseract reads: 300 DPI for a letter page, where its
  accuracy on small print levels off.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".gif"}
VISION_LONG_EDGE = 2200
OCR_LONG_EDGE = 3300
JPEG_QUALITY = 85


@dataclass
class Page:
    number: int   # 1-based
    text: str     # the file's own text layer; "" for photos and image-only scans


def is_supported(path: Path | str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED


def page_count(path: Path | str) -> int:
    with pymupdf.open(path) as doc:
        return doc.page_count


def pages(path: Path | str) -> list[Page]:
    with pymupdf.open(path) as doc:
        return [Page(page.number + 1, page.get_text().strip()) for page in doc]


def render(path: Path | str, number: int, long_edge: int, fmt: str = "jpeg") -> bytes:
    """One page (1-based) as JPEG or PNG bytes, scaled so its long edge is ``long_edge`` px."""
    with pymupdf.open(path) as doc:
        page = doc[number - 1]
        zoom = long_edge / max(page.rect.width, page.rect.height)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csRGB, alpha=False)
        if fmt == "png":
            return pix.tobytes("png")
        return pix.tobytes("jpeg", jpg_quality=JPEG_QUALITY)
