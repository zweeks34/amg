"""Local OCR with Tesseract — free, offline, and only as good as the scan.

pytesseract is a wrapper; the engine is a separate system binary (apt on the
server, the UB-Mannheim installer on Windows). On this Windows machine it is
installed but not on PATH, so the usual install locations are tried too. If
it is missing, ``available()`` says so and the receipt reader skips local OCR
rather than failing.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

_WINDOWS_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)

_configured = False


@dataclass
class OcrResult:
    text: str
    confidence: float  # mean word confidence, 0–100; 0 when nothing was read
    words: int


def _configure() -> None:
    global _configured
    if _configured:
        return
    _configured = True
    import pytesseract

    if shutil.which("tesseract"):
        return
    for candidate in _WINDOWS_PATHS:
        if Path(candidate).exists():
            pytesseract.pytesseract.tesseract_cmd = candidate
            return


def available() -> bool:
    try:
        import pytesseract
    except ImportError:
        return False
    _configure()
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return False
    return True


def read(image: bytes) -> OcrResult:
    """OCR an image, keeping Tesseract's line breaks and its confidence."""
    import pytesseract
    from PIL import Image

    _configure()
    data = pytesseract.image_to_data(Image.open(BytesIO(image)), output_type=pytesseract.Output.DICT)
    lines: dict[tuple[int, int, int], list[str]] = {}
    confidences: list[float] = []
    for i, word in enumerate(data["text"]):
        word = word.strip()
        conf = float(data["conf"][i])
        if not word or conf < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(word)
        confidences.append(conf)
    text = "\n".join(" ".join(words) for _, words in sorted(lines.items()))
    mean = sum(confidences) / len(confidences) if confidences else 0.0
    return OcrResult(text=text, confidence=round(mean, 1), words=len(confidences))
