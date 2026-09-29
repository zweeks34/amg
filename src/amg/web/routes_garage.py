"""The garage: every car at a glance. The front page."""

from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import Response

from .templating import render

router = APIRouter()


@router.get("/")
def garage(request: Request) -> Response:
    return render(request, "garage.html", active="garage", vehicles=[])
