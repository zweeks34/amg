"""The one way AMG calls Claude: structured output, refusal fallbacks on, usage kept.

Every call returns a validated Pydantic object or raises ClaudeError with a
message fit for the page — never a half-parsed response. The model is one
setting, AMG_CLAUDE_MODEL, so trading accuracy for cost is a one-line change.

Server-side refusal fallbacks (``fallbacks: "default"``) are on: if the model
declines on a policy classifier, the API re-runs the request on Anthropic's
recommended fallback model inside the same call. For reading receipts that
should never happen, and costs nothing when it doesn't.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import TypeVar

import anthropic
import httpx2  # the SDK's HTTP library; a streamed answer's read timeout surfaces as its exception
from pydantic import BaseModel

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# $ per million tokens: (input, output, cache read). Cache writes cost 1.25× input.
# For cost estimates only; the bill is the authority. Prices as of 2026-09.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
}

T = TypeVar("T", bound=BaseModel)


class ClaudeError(Exception):
    """Claude could not produce a usable answer; the message says why."""


@dataclass
class Usage:
    model: str
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    seconds: float
    request_id: str | None

    @property
    def cost_usd(self) -> float | None:
        price = PRICES.get(self.model)
        if price is None:
            return None
        per_in, per_out, per_cache_read = price
        return (
            self.input_tokens * per_in
            + self.cache_write_tokens * per_in * 1.25
            + self.cache_read_tokens * per_cache_read
            + self.output_tokens * per_out
        ) / 1_000_000


def model() -> str:
    return os.environ.get("AMG_CLAUDE_MODEL") or DEFAULT_MODEL


def configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


@lru_cache(maxsize=1)
def client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def parse(
    schema: type[T],
    system: str,
    content: list[dict],
    effort: str = "medium",
    max_tokens: int = 16_000,
    timeout: float = 180.0,
    stream: bool = False,
) -> tuple[T, Usage]:
    """Ask Claude for ``schema`` given ``content``; the system prompt is cached.

    ``timeout`` is per attempt (the SDK retries twice), so a stuck call can't
    hold a background job for the SDK's default ten minutes.

    ``stream`` is for long answers — a manual's whole schedule at high effort.
    The answer arrives as it's written, so ``timeout`` bounds a silence rather
    than the whole call, and a long read isn't mistaken for a stuck one.
    """
    if not configured():
        # The SDK would raise a bare TypeError here; say what to do about it instead.
        raise ClaudeError("No Anthropic API key is set, so AMG can't read documents. Add ANTHROPIC_API_KEY "
                          "to the .env file, restart the app, then read this again.")
    started = time.monotonic()
    request = dict(
        model=model(),
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": content}],
        output_format=schema,
        output_config={"effort": effort},
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    messages = client().with_options(timeout=timeout).beta.messages
    try:
        if stream:
            with messages.stream(**request) as live:
                response = live.get_final_message()
                request_id = live.request_id
        else:
            response = messages.parse(**request)
            request_id = getattr(response, "_request_id", None)
    except (anthropic.APITimeoutError, httpx2.TimeoutException) as err:
        raise ClaudeError("Claude took too long to answer. Try reading it again.") from err
    except anthropic.AuthenticationError as err:
        raise ClaudeError("Claude rejected the API key. Check ANTHROPIC_API_KEY in .env.") from err
    except anthropic.RateLimitError as err:
        raise ClaudeError("Claude is rate-limiting requests. Try again in a minute.") from err
    except (anthropic.APIConnectionError, httpx2.TransportError) as err:
        raise ClaudeError("Couldn't reach Claude. Check the server's internet connection.") from err
    except anthropic.APIStatusError as err:
        raise ClaudeError(f"Claude returned an error ({err.status_code}): {err.message}") from err

    usage = response.usage
    used = Usage(
        model=response.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_write_tokens=usage.cache_creation_input_tokens or 0,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        seconds=round(time.monotonic() - started, 1),
        request_id=request_id,
    )
    if response.stop_reason == "refusal":
        raise ClaudeError("Claude declined to read this document.")
    if response.stop_reason == "max_tokens":
        raise ClaudeError("Claude's answer was cut off before it finished.")
    if response.parsed_output is None:
        raise ClaudeError("Claude's answer didn't match the expected format.")
    return response.parsed_output, used
