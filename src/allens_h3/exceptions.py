"""Exception hierarchy for the Allen's MiniMax H3 SDK.

Callers should never have to inspect a raw HTTP status code. Every server
response maps onto one of these types.

No exception message ever contains the Authorization header or the API key —
:func:`_scrub` is applied to any server-supplied text before it is stored.
"""

from __future__ import annotations

import re

__all__ = [
    "H3Error",
    "H3AuthenticationError",
    "H3PermissionError",
    "H3ValidationError",
    "H3NotFoundError",
    "H3ConflictError",
    "H3RateLimitError",
    "H3GPUUnavailableError",
    "H3JobFailedError",
    "H3TimeoutError",
    "H3ConnectionError",
    "from_status",
]

_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*)\S+"),
    re.compile(r"(?i)(bearer\s+)\S+"),
    re.compile(r"h3s_[A-Za-z0-9._\-]+"),
    re.compile(r"h3c_[A-Za-z0-9._\-]{8,}"),
]


def _scrub(text: str) -> str:
    """Strip anything credential-shaped out of a message."""
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub(lambda m: (m.group(1) if m.lastindex else "") + "<redacted>",
                      out)
    return out


class H3Error(Exception):
    """Base class for every error raised by this SDK."""

    def __init__(self, message: str, *, status: int | None = None,
                 request_id: str | None = None) -> None:
        super().__init__(_scrub(message))
        self.status = status
        self.request_id = request_id

    def __str__(self) -> str:
        base = super().__str__()
        if self.request_id:
            return f"{base} (request_id={self.request_id})"
        return base


class H3AuthenticationError(H3Error):
    """401 — missing, malformed, revoked or expired credential."""


class H3PermissionError(H3Error):
    """403 — the credential is valid but lacks the required scope."""


class H3ValidationError(H3Error):
    """422 / 400 / 413 — the request parameters were rejected."""


class H3NotFoundError(H3Error):
    """404 — unknown job, or a job belonging to another client."""


class H3ConflictError(H3Error):
    """409 — the job is not in a state that allows this operation."""


class H3RateLimitError(H3Error):
    """429 — request rate or generation quota exceeded."""

    def __init__(self, message: str, *, retry_after: float | None = None,
                 **kw) -> None:
        super().__init__(message, **kw)
        self.retry_after = retry_after


class H3GPUUnavailableError(H3Error):
    """503 — the GPU or the rendering backend is not currently usable."""


class H3JobFailedError(H3Error):
    """The job reached a terminal state other than ``completed``."""

    def __init__(self, message: str, *, job_id: str | None = None,
                 status: str | None = None) -> None:
        super().__init__(message)
        self.job_id = job_id
        self.job_status = status


class H3TimeoutError(H3Error):
    """The client stopped waiting before the job finished."""


class H3ConnectionError(H3Error):
    """The server could not be reached."""


_STATUS_MAP: dict[int, type[H3Error]] = {
    400: H3ValidationError,
    401: H3AuthenticationError,
    403: H3PermissionError,
    404: H3NotFoundError,
    409: H3ConflictError,
    413: H3ValidationError,
    422: H3ValidationError,
    429: H3RateLimitError,
    500: H3Error,
    502: H3GPUUnavailableError,
    503: H3GPUUnavailableError,
    504: H3GPUUnavailableError,
}


def from_status(status: int, message: str, *, request_id: str | None = None,
                retry_after: float | None = None) -> H3Error:
    """Build the right exception for an HTTP status code."""
    cls = _STATUS_MAP.get(status, H3Error)
    if cls is H3RateLimitError:
        return H3RateLimitError(message, status=status, request_id=request_id,
                                retry_after=retry_after)
    return cls(message, status=status, request_id=request_id)
