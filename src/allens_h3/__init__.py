"""Allen's MiniMax H3 Python SDK.

Generate video with audio from a text prompt, on a private RTX 3090.

    from allens_h3 import H3Client

    client = H3Client()                       # reads ALLENS_H3_* env vars
    video = client.generate(prompt="A cinematic AI commercial", duration=5)
    video.download("output.mp4")

Async:

    from allens_h3 import AsyncH3Client

    async with AsyncH3Client() as client:
        video = await client.generate(prompt="...")
        await video.download("output.mp4")
"""

from .client import H3Client
from .exceptions import (
    H3AuthenticationError,
    H3ConflictError,
    H3ConnectionError,
    H3Error,
    H3GPUUnavailableError,
    H3JobFailedError,
    H3NotFoundError,
    H3PermissionError,
    H3RateLimitError,
    H3TimeoutError,
    H3ValidationError,
)
from .jobs import AsyncH3Client
from .models import GPUStatus, HealthStatus, Job, JobStatus, VideoResult
from .version import __api_version__, __title__, __version__

__all__ = [
    # clients
    "H3Client",
    "AsyncH3Client",
    # models
    "Job",
    "JobStatus",
    "VideoResult",
    "GPUStatus",
    "HealthStatus",
    # exceptions
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
    # metadata
    "__version__",
    "__api_version__",
    "__title__",
]
