"""Uploaded files: stored once by content, rendered on demand for review.

A file is identified by the SHA-256 of its bytes as uploaded, so uploading
the same scan twice finds the first copy. Files live under
``data/files/<first two hex>/<sha256>.<ext>``; the uploaded name is kept for
display and never touches a path.

Phone photos carry their rotation as an EXIF tag that PDF renderers ignore, so
a JPEG is turned upright before it's stored — otherwise both the review page
and Claude would see it sideways.
"""

from __future__ import annotations

import hashlib
import sqlite3
from io import BytesIO
from pathlib import Path

import pymupdf

from .. import config
from ..db import now_iso
from ..ingest import pdf

MAX_BYTES = 50 * 1024 * 1024
MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
}
PREVIEW_LONG_EDGE = 1600   # the review page
FULL_LONG_EDGE = 2600      # "open full size"
THUMB_LONG_EDGE = 480      # an issue's photos in a row


class UploadError(ValueError):
    """A file AMG can't take; the message names the file and says why."""


def store(conn: sqlite3.Connection, data: bytes, filename: str) -> tuple[sqlite3.Row, bool]:
    """Store an upload; returns (document, True) or (the existing document, False)."""
    name = Path(filename).name or "upload"
    ext = Path(name).suffix.lower()
    if ext not in MEDIA_TYPES:
        raise UploadError(f"{name}: AMG reads PDF, PNG, JPG and GIF files.")
    if not data:
        raise UploadError(f"{name} is empty.")
    if len(data) > MAX_BYTES:
        raise UploadError(f"{name} is over 50 MB.")

    sha = hashlib.sha256(data).hexdigest()
    if existing := by_sha(conn, sha):
        return existing, False

    body = _upright(data, ext)
    pages = _page_count(body, ext, name)
    relative = Path("files") / sha[:2] / f"{sha}{'.jpg' if ext == '.jpeg' else ext}"
    target = config.data_dir() / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    try:
        cursor = conn.execute(
            "INSERT INTO documents (sha256, filename, media_type, size_bytes, page_count, stored_as, uploaded_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sha, name, MEDIA_TYPES[ext], len(data), pages, relative.as_posix(), now_iso()),
        )
    except sqlite3.IntegrityError:  # the same file, uploaded in the same moment by another request
        return by_sha(conn, sha), False  # type: ignore[return-value]
    return get(conn, cursor.lastrowid), True  # type: ignore[arg-type,return-value]


def combine(parts: list[tuple[bytes, str]]) -> tuple[bytes, str]:
    """Several files — photos of an invoice's pages, say — as one PDF, in order."""
    out = pymupdf.open()
    for data, filename in parts:
        ext = Path(filename).suffix.lower()
        if ext not in MEDIA_TYPES:
            raise UploadError(f"{Path(filename).name}: AMG reads PDF, PNG, JPG and GIF files.")
        try:
            with pymupdf.open(stream=_upright(data, ext), filetype=ext.lstrip(".")) as source:
                if source.is_pdf:
                    out.insert_pdf(source)
                else:
                    with pymupdf.open("pdf", source.convert_to_pdf()) as converted:
                        out.insert_pdf(converted)
        except UploadError:
            raise
        except Exception as err:
            raise UploadError(f"{Path(filename).name} couldn't be opened.") from err
    data = out.tobytes(garbage=3, deflate=True)
    out.close()
    return data, f"{Path(parts[0][1]).stem}-combined.pdf"


def fingerprint(sha256: str) -> str:
    """A file's short name in URLs: enough of its hash that a different file never shares it."""
    return sha256[:12]


def get(conn: sqlite3.Connection, document_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()


def by_sha(conn: sqlite3.Connection, sha: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM documents WHERE sha256 = ?", (sha,)).fetchone()


def path(document: sqlite3.Row) -> Path:
    return config.data_dir() / document["stored_as"]


def page_image(document: sqlite3.Row, page: int, long_edge: int) -> Path:
    """A page as JPEG, rendered once and kept under data/previews/."""
    if not 1 <= page <= document["page_count"]:
        raise ValueError(f"page {page} out of range")
    cached = config.data_dir() / "previews" / f"{document['sha256']}-{page}-{long_edge}.jpg"
    if not cached.exists():
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(pdf.render(path(document), page, long_edge))
    return cached


def _upright(data: bytes, ext: str) -> bytes:
    if ext not in (".jpg", ".jpeg"):
        return data
    from PIL import Image, ImageOps

    try:
        image = Image.open(BytesIO(data))
        orientation = image.getexif().get(0x0112, 1)
    except Exception:
        return data
    if orientation in (None, 1):
        return data
    upright = ImageOps.exif_transpose(image)
    out = BytesIO()
    upright.convert("RGB").save(out, "JPEG", quality=92)
    return out.getvalue()


def _page_count(data: bytes, ext: str, name: str) -> int:
    try:
        with pymupdf.open(stream=data, filetype=ext.lstrip(".")) as doc:
            count = doc.page_count
    except Exception as err:
        raise UploadError(f"{name} couldn't be opened. Is it damaged?") from err
    if count < 1:
        raise UploadError(f"{name} has no pages.")
    return count
