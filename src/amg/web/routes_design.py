"""The design reference: tokens, type, controls and the interval chart, on one page.

It exists so the visual language can be reviewed before the pages that use it
are built, and checked against later. The chart here is drawn from sample data
written out by hand, not from the gap engine.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import Response

from .templating import render

router = APIRouter()

PALETTE = [
    ("floor", "Shop floor", "Page background"),
    ("sheet", "Manual page", "Panels and forms"),
    ("ink", "Ink", "Text, primary actions"),
    ("steel", "Steel", "Secondary text, later items"),
    ("done", "Service green", "Done"),
    ("due", "Safety yellow", "Due soon, focus"),
    ("gap", "Signal red", "Gaps and overdue"),
]


def _row(name: str, every: str, marks: list[tuple[int, str]]) -> dict:
    return {"name": name, "every": every, "marks": [{"miles": m, "status": s} for m, s in marks]}


SAMPLE_CHART = {
    "vehicle": "Sample car",
    "here": 64_300,
    "span": 90_000,
    "ticks": [0, 15_000, 30_000, 45_000, 60_000, 75_000, 90_000],
    "groups": [
        {
            "label": "Engine",
            "rows": [
                _row(
                    "Oil and filter",
                    "5,000 mi · 6 mo",
                    [(m, "done") for m in range(5_000, 40_000, 5_000)]
                    + [(40_000, "gap")]
                    + [(m, "done") for m in range(45_000, 65_000, 5_000)]
                    + [(65_000, "due")]
                    + [(m, "later") for m in range(70_000, 95_000, 5_000)],
                ),
                _row("Engine air filter", "30,000 mi", [(30_000, "done"), (60_000, "overdue"), (90_000, "later")]),
                _row("Spark plugs", "60,000 mi", [(60_000, "done")]),
            ],
        },
        {
            "label": "Tires and brakes",
            "rows": [
                _row(
                    "Tire rotation",
                    "7,500 mi",
                    [(7_500, "done"), (15_000, "done"), (22_500, "gap")]
                    + [(m, "done") for m in (30_000, 37_500, 45_000, 52_500)]
                    + [(60_000, "overdue")]
                    + [(m, "later") for m in (67_500, 75_000, 82_500, 90_000)],
                ),
                _row("Brake fluid", "45,000 mi · 3 yr", [(45_000, "done"), (90_000, "later")]),
            ],
        },
        {
            "label": "Cabin",
            "rows": [
                _row(
                    "Cabin air filter",
                    "15,000 mi",
                    [(15_000, "done"), (30_000, "done"), (45_000, "gap"), (60_000, "done"), (75_000, "later"), (90_000, "later")],
                ),
            ],
        },
    ],
}

SAMPLE_NEXT_UP = [
    {"name": "Tire rotation", "status": "overdue", "when": "4,300 mi overdue", "cost": 2_500},
    {"name": "Engine air filter", "status": "overdue", "when": "4,300 mi overdue", "cost": 4_500},
    {"name": "Oil and filter", "status": "due", "when": "in 700 mi · by Nov 12", "cost": 8_999},
    {"name": "Cabin air filter", "status": "later", "when": "in 10,700 mi · ~Jul", "cost": 3_800},
]


@router.get("/design")
def design_reference(request: Request) -> Response:
    return render(
        request,
        "design.html",
        active="design",
        palette=PALETTE,
        chart=SAMPLE_CHART,
        upcoming=SAMPLE_NEXT_UP,
    )
