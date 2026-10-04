"""A push to your phone through ntfy (https://ntfy.sh, or a server of your own).

Published as JSON to the server's root, so the title and message can carry any
character — "·", "—", a car called "Mum's" — which HTTP headers can't.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from ..config import Ntfy

TIMEOUT = 15   # seconds


class SendError(Exception):
    """A push didn't go; the message says why, in words for the Alerts page."""


@dataclass(frozen=True)
class Push:
    title: str
    message: str
    priority: int = 3                  # ntfy's 1–5: 3 is normal, 4 is high
    tags: tuple[str, ...] = field(default=())
    click: str = ""                    # what tapping it opens


def send(push: Push, settings: Ntfy) -> None:
    payload = {"topic": settings.topic, "title": push.title, "message": push.message, "priority": push.priority}
    if push.tags:
        payload["tags"] = list(push.tags)
    if push.click:
        payload["click"] = push.click
    headers = {"Content-Type": "application/json"}
    if settings.token:
        headers["Authorization"] = f"Bearer {settings.token}"
    request = urllib.request.Request(settings.url, data=json.dumps(payload).encode("utf-8"), headers=headers,
                                     method="POST")
    host = urlsplit(settings.url).netloc or settings.url
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            response.read()
    except urllib.error.HTTPError as err:
        if err.code in (401, 403):
            raise SendError(f"{host} turned the push down ({err.code}): the topic needs a token, "
                            "or AMG_NTFY_TOKEN is wrong.") from err
        raise SendError(f"{host} turned the push down ({err.code} {err.reason}).") from err
    except (urllib.error.URLError, OSError) as err:
        reason = getattr(err, "reason", err)
        raise SendError(f"Couldn't reach {host} ({reason}). Check AMG_NTFY_URL and the server's internet.") from err
