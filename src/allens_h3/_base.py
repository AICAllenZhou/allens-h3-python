"""Shared plumbing for the sync and async clients.

Holds everything that has no I/O opinion: configuration resolution, URL
validation, retry policy, and response-to-exception mapping. ``client.py``
and ``jobs.py`` build the two transports on top of this.
"""

from __future__ import annotations

import os
import random
from typing import Any, Optional
from urllib.parse import urlparse

from .exceptions import H3Error, H3ValidationError, from_status
from .version import __version__

ENV_API_KEY = "ALLENS_H3_API_KEY"
ENV_BASE_URL = "ALLENS_H3_BASE_URL"

DEFAULT_TIMEOUT = 30.0
DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_JOB_TIMEOUT = 1800.0

# Only idempotent reads are retried. A generation POST is never retried
# automatically: a duplicate would occupy the single GPU a second time.
RETRY_STATUSES = frozenset({502, 503, 504})
MAX_RETRIES = 3
BACKOFF_BASE = 1.5

USER_AGENT = f"allens-h3-python/{__version__}"


def resolve_config(api_key: Optional[str], base_url: Optional[str]
                   ) -> tuple[str, str]:
    """Explicit argument wins, then environment. Neither is ever persisted."""
    key = api_key or os.environ.get(ENV_API_KEY, "")
    url = base_url or os.environ.get(ENV_BASE_URL, "")

    if not key:
        raise H3ValidationError(
            "No API key. Pass api_key=... or set the "
            f"{ENV_API_KEY} environment variable.")
    if not url:
        raise H3ValidationError(
            "No base URL. Pass base_url=... or set the "
            f"{ENV_BASE_URL} environment variable. The endpoint is never "
            "hard-coded in this SDK because tunnel hostnames can change.")
    return key.strip(), validate_base_url(url)


def validate_base_url(url: str) -> str:
    """Reject malformed URLs and any URL carrying embedded credentials."""
    url = url.strip().rstrip("/")
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise H3ValidationError(
            f"base_url must be http or https, got {parsed.scheme!r}")
    if not parsed.netloc:
        raise H3ValidationError("base_url has no host")
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise H3ValidationError(
            "base_url must not contain credentials; pass api_key separately")
    if parsed.query or parsed.fragment:
        raise H3ValidationError("base_url must not contain a query or fragment")
    if parsed.scheme == "http" and parsed.hostname not in (
            "localhost", "127.0.0.1", "::1"):
        raise H3ValidationError(
            "Refusing plain http to a remote host — the credential would be "
            "sent in clear text. Use https.")
    return url


def auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json"}


def backoff_delay(attempt: int) -> float:
    """Exponential backoff with jitter, so parallel clients do not sync up."""
    return (BACKOFF_BASE ** attempt) + random.uniform(0, 0.4)


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def raise_for_response(status: int, body: str, headers: Any) -> None:
    """Map a non-2xx response onto a typed exception.

    The server already sanitises its error text; we additionally never echo
    request headers back into the message.
    """
    if 200 <= status < 300:
        return

    request_id = None
    message = ""
    try:
        import json
        data = json.loads(body) if body else {}
        if isinstance(data, dict):
            request_id = data.get("request_id")
            message = data.get("error") or data.get("detail") or ""
            if isinstance(message, list):           # pydantic error list
                parts = []
                for item in message:
                    if isinstance(item, dict):
                        loc = ".".join(str(x) for x in item.get("loc", [])
                                       if x not in ("body",))
                        parts.append(f"{loc}: {item.get('msg', '')}".strip(": "))
                message = "; ".join(p for p in parts if p)
    except Exception:                                          # noqa: BLE001
        pass

    if not message:
        message = {
            401: "Authentication failed — check the API key, and whether it "
                 "has been revoked or has expired.",
            403: "The credential lacks the required scope.",
            404: "Not found.",
            413: "Request body too large.",
            422: "Invalid parameters.",
            429: "Rate limit or generation quota exceeded.",
            503: "The GPU or rendering backend is unavailable.",
        }.get(status, f"Request failed with status {status}")

    retry_after = None
    try:
        retry_after = parse_retry_after(headers.get("Retry-After"))
    except Exception:                                          # noqa: BLE001
        pass

    raise from_status(status, message, request_id=request_id,
                      retry_after=retry_after)


def build_payload(prompt: str, width: int, height: int, duration: float,
                  steps: int, seed: Optional[int]) -> dict[str, Any]:
    """Client-side validation mirrors the server's allowlist, so obvious
    mistakes fail instantly instead of costing a round trip."""
    if not prompt or not prompt.strip():
        raise H3ValidationError("prompt must not be empty")
    if len(prompt) > 2000:
        raise H3ValidationError("prompt exceeds 2000 characters")
    for name, value in (("width", width), ("height", height)):
        if value % 32:
            raise H3ValidationError(f"{name} must be a multiple of 32")
    if not 1 <= duration <= 10:
        raise H3ValidationError("duration must be between 1 and 10 seconds")
    if not 4 <= steps <= 40:
        raise H3ValidationError("steps must be between 4 and 40")

    payload: dict[str, Any] = {"prompt": prompt, "width": width,
                               "height": height, "duration": duration,
                               "steps": steps}
    if seed is not None:
        if not 0 <= seed < 2 ** 63:
            raise H3ValidationError("seed out of range")
        payload["seed"] = seed
    return payload
