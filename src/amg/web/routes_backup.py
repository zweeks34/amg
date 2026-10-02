"""Back up: what a backup holds, and the download.

Restoring isn't offered here. It replaces everything, so it is a command run on
the server with the app stopped — the page says how.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from starlette.background import BackgroundTask
from starlette.responses import FileResponse, Response

from .. import backup
from .deps import get_conn
from .templating import render

router = APIRouter()


@router.get("/backup")
def page(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    return render(request, "backup.html", active="backup", summary=backup.summary(conn))


@router.get("/backup/download")
def download(files: int = 1) -> Response:
    include_files = bool(files)
    # Built in the system temp directory, not the data directory, and deleted
    # once sent: a full backup is the size of every scan, and the server
    # shouldn't quietly keep a copy per click.
    handle, name = tempfile.mkstemp(prefix="amg-backup-", suffix=".zip")
    os.close(handle)
    path = Path(name)
    try:
        backup.write(path, include_files=include_files)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return FileResponse(
        path,
        media_type="application/zip",
        filename=backup.filename(include_files),
        background=BackgroundTask(path.unlink, missing_ok=True),
    )
