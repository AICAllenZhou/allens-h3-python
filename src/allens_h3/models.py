"""Typed response models.

Plain dataclasses — no Pydantic dependency, so the SDK stays light and works
on any Python 3.9+. Every model is built with :meth:`from_dict` so unknown
fields added by a future server version never break an older client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

__all__ = ["JobStatus", "Job", "GPUStatus", "HealthStatus", "VideoResult"]


class JobStatus:
    """Job lifecycle states (string constants, not an enum, so an unknown
    state from a newer server is still readable)."""

    QUEUED = "queued"
    LOADING = "loading"
    GENERATING = "generating"
    DECODING = "decoding"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED})
    ACTIVE = frozenset({QUEUED, LOADING, GENERATING, DECODING})


def _dt(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class Job:
    """A generation job."""

    id: str
    status: str
    progress: float = 0.0
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    queue_position: Optional[int] = None
    length_frames: Optional[int] = None
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        return cls(
            id=d.get("job_id", ""),
            status=d.get("status", "unknown"),
            progress=float(d.get("progress", 0.0) or 0.0),
            created_at=_dt(d.get("created_at")),
            completed_at=_dt(d.get("finished_at") or d.get("completed_at")),
            error=d.get("error"),
            queue_position=d.get("queue_position"),
            length_frames=d.get("length_frames"),
            raw=d,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in JobStatus.TERMINAL

    @property
    def is_complete(self) -> bool:
        return self.status == JobStatus.COMPLETED

    @property
    def percent(self) -> float:
        return round(self.progress * 100, 1)


@dataclass
class GPUStatus:
    """Live GPU telemetry."""

    name: str = ""
    temperature_c: Optional[float] = None
    hotspot_c: Optional[float] = None
    vram_max_c: Optional[float] = None
    vram_used_mb: Optional[float] = None
    vram_total_mb: Optional[float] = None
    power_w: Optional[float] = None
    power_limit_w: Optional[float] = None
    utilization_pct: Optional[float] = None
    worker: str = "unknown"
    queue_depth: int = 0
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: dict) -> "GPUStatus":
        def num(key: str) -> Optional[float]:
            v = d.get(key)
            return float(v) if isinstance(v, (int, float)) else None

        return cls(
            name=d.get("name", ""),
            temperature_c=num("temperature_c"),
            hotspot_c=num("hotspot_c"),
            vram_max_c=num("vram_max_c"),
            vram_used_mb=num("vram_used_mb"),
            vram_total_mb=num("vram_total_mb"),
            power_w=num("power_w"),
            power_limit_w=num("power_limit_w"),
            utilization_pct=num("utilization_pct"),
            worker=d.get("worker", "unknown"),
            queue_depth=int(d.get("queue_depth", 0) or 0),
            raw=d,
        )

    @property
    def is_busy(self) -> bool:
        return self.worker == "busy"


@dataclass
class HealthStatus:
    """Server liveness."""

    status: str = "unknown"
    comfyui: str = "unknown"
    gpu: str = "unknown"
    worker: str = "unknown"
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: dict) -> "HealthStatus":
        return cls(status=d.get("status", "unknown"),
                   comfyui=d.get("comfyui", "unknown"),
                   gpu=d.get("gpu", "unknown"),
                   worker=d.get("worker", "unknown"), raw=d)

    @property
    def is_ok(self) -> bool:
        return self.status == "ok"


@dataclass
class VideoResult:
    """A finished video, bound to the client that produced it.

    ``download()`` and ``content()`` re-authenticate on every call — the video
    is never reachable through an unauthenticated URL.
    """

    job: Job
    _client: Any = field(default=None, repr=False)

    @property
    def job_id(self) -> str:
        return self.job.id

    def download(self, path):
        """Save the MP4 to ``path``.

        Returns a ``Path`` for a sync client, or an awaitable yielding a
        ``Path`` when the result came from :class:`AsyncH3Client`.
        """
        if self._client is None:
            raise RuntimeError("VideoResult is not bound to a client")
        return self._client.download(self.job.id, path)

    def content(self):
        """Return the MP4 bytes (awaitable for an async client)."""
        if self._client is None:
            raise RuntimeError("VideoResult is not bound to a client")
        return self._client.content(self.job.id)
