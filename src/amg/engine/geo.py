"""Geography for the fill-up map: a town's name as it's looked up, and where a point goes on the map.

Pure: no database, no files. scripts/build_places.py uses the same two
functions to build the town list and the outlines, so a name typed on the
form and a name in the list come out the same, and the outlines and the
dots are drawn in the same coordinates.

The map is an equal-area conic for North America (the ESRI "North America
Albers" parameters): kilometres east and south of the middle of the
continent, south down the page as SVG has it.
"""

from __future__ import annotations

import math
import re
import unicodedata

# Words a town's name is written with more than one way: the long form is the one looked up.
_SAME = {"st": "saint", "ste": "sainte", "mt": "mount", "ft": "fort", "pt": "point", "e": "east", "w": "west",
         "n": "north", "s": "south", "twp": "township"}


def town_key(name: str) -> str:
    """A town's name as it's looked up: "St. John's" → "saint johns", "Montréal" → "montreal",
    "Mt Laurel" → "mount laurel". Capitals, accents, punctuation and spacing don't count."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"['’`]", "", text)
    words = re.sub(r"[^a-z0-9]+", " ", text).split()
    return " ".join(_SAME.get(word, word) for word in words)


# North America Albers Equal Area Conic, on a sphere of the Earth's mean radius.
_R = 6371.0
_LAT1, _LAT2, _LAT0, _LON0 = (math.radians(d) for d in (20.0, 60.0, 40.0, -96.0))
_N = (math.sin(_LAT1) + math.sin(_LAT2)) / 2
_C = math.cos(_LAT1) ** 2 + 2 * _N * math.sin(_LAT1)
_RHO0 = _R * math.sqrt(_C - 2 * _N * math.sin(_LAT0)) / _N


def project(lat: float, lon: float) -> tuple[float, float]:
    """A point's place on the map, in kilometres: x east, y south of the middle. A longitude past 180° east (the
    far Aleutians) is taken as west of it, so Alaska stays in one piece."""
    if lon > 0:
        lon -= 360
    rho = _R * math.sqrt(_C - 2 * _N * math.sin(math.radians(lat))) / _N
    theta = _N * (math.radians(lon) - _LON0)
    return rho * math.sin(theta), -(_RHO0 - rho * math.cos(theta))
