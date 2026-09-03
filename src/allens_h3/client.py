"""Synchronous client for Allen's MiniMax H3 API."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Optional, Union

import httpx

from . import _base
from .exceptions import (
    H3ConnectionError,
    H3JobFailedError,
    H3RateLimitError,
    H3TimeoutError,
)
from .models import GPUStatus, HealthStatus, Job, JobStatus, VideoResult

__all__ = ["H3Client"]


class H3Client:
    """Client for Allen's MiniMax H3 video generation API.

    Credentials come from the constructor or, failing that, the environment
    (``ALLENS_H3_API_KEY`` / ``ALLENS_H3_BASE_URL``). The endpoint is never
    hard-coded, because tunnel hostnames change.

        >>> client = H3Client()
        >>> video = client.generate(prompt="A cinematic AI commercial")
        >>> video.download("output.mp4")

    TLS verification is always on and cannot be disabled.
    """

    def __init__(self, api_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 timeout: float = _base.DEFAULT_TIMEOUT,
                 poll_interval: float = _base.DEFAULT_POLL_INTERVAL) -> None:
        self._api_key, self.base_url = _base.resolve_config(api_key, base_url)
        self.timeout = timeout
        self.poll_interval = poll_interval
        # verify=True is hard-coded: there is deliberately no opt-out, since
        # disabling it would expose the credential to a man in the middle.
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout,
                                  verify=True, follow_redirects=False,
                                  headers=_base.auth_headers(self._api_key))

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "H3Client":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __repr__(self) -> str:            # never shows the key
        return f"<H3Client base_url={self.base_url!r}>"

    # -- transport ---------------------------------------------------------
    def _request(self, method: str, path: str, *, retry: bool = True,
                 **kw: Any) -> httpx.Response:
        attempt = 0
        while True:
            try:
                resp = self._http.request(method, path, **kw)
            except httpx.TimeoutException as e:
                if retry and attempt < _base.MAX_RETRIES:
                    time.sleep(_base.backoff_delay(attempt))
                    attempt += 1
                    continue
                raise H3ConnectionError(f"request timed out: {e}") from e
            except httpx.HTTPError as e:
                if retry and attempt < _base.MAX_RETRIES:
                    time.sleep(_base.backoff_delay(attempt))
                    attempt += 1
                    continue
                raise H3ConnectionError(f"could not reach the server: {e}") from e

            if (retry and resp.status_code in _base.RETRY_STATUSES
                    and attempt < _base.MAX_RETRIES):
                time.sleep(_base.backoff_delay(attempt))
                attempt += 1
                continue

            if resp.status_code == 429 and retry and attempt < _base.MAX_RETRIES:
                wait = _base.parse_retry_after(resp.headers.get("Retry-After"))
                if wait is not None and wait <= 30:
                    time.sleep(wait)
                    attempt += 1
                    continue

            _base.raise_for_response(resp.status_code, resp.text, resp.headers)
            return resp

    # -- endpoints ---------------------------------------------------------
    def health(self) -> HealthStatus:
        """Server liveness. Does not require a valid key on most deployments."""
        return HealthStatus.from_dict(self._request("GET", "/health").json())

    def gpu(self) -> GPUStatus:
        """Live GPU telemetry."""
        return GPUStatus.from_dict(self._request("GET", "/v1/gpu").json())

    def create_video(self, prompt: str, *, width: int = 608, height: int = 352,
                     duration: float = 5.0, steps: int = 20,
                     seed: Optional[int] = None) -> Job:
        """Submit a job and return immediately, without waiting.

        This POST is never retried automatically — a duplicate would occupy
        the single GPU twice.
        """
        payload = _base.build_payload(prompt, width, height, duration, steps,
                                      seed)
        resp = self._request("POST", "/v1/videos", json=payload, retry=False)
        return Job.from_dict(resp.json())

    def get_job(self, job_id: str) -> Job:
        """Current state of one job."""
        return Job.from_dict(
            self._request("GET", f"/v1/jobs/{job_id}").json())

    def list_jobs(self, limit: int = 20) -> list[Job]:
        """Recent jobs belonging to this credential."""
        data = self._request("GET", "/v1/jobs",
                             params={"limit": limit}).json()
        return [Job.from_dict(j) for j in data.get("jobs", [])]

    def cancel(self, job_id: str) -> Job:
        """Gracefully cancel a queued or running job."""
        self._request("POST", f"/v1/jobs/{job_id}/cancel", retry=False)
        return self.get_job(job_id)

    def wait(self, job_id: str, *, timeout: float = _base.DEFAULT_JOB_TIMEOUT,
             poll_interval: Optional[float] = None,
             on_progress: Optional[Callable[[Job], None]] = None) -> Job:
        """Block until the job reaches a terminal state.

        Raises :class:`H3JobFailedError` if it fails or is cancelled, and
        :class:`H3TimeoutError` if the deadline passes first.
        """
        interval = poll_interval or self.poll_interval
        deadline = time.time() + timeout
        transient = 0

        while time.time() < deadline:
            try:
                job = self.get_job(job_id)
                transient = 0
            except (H3ConnectionError, H3RateLimitError):
                # A long poll can outlive an idle keep-alive socket; that is
                # not a job failure.
                transient += 1
                if transient > 10:
                    raise
                time.sleep(interval)
                continue

            if on_progress:
                on_progress(job)
            if job.is_terminal:
                if job.status != JobStatus.COMPLETED:
                    raise H3JobFailedError(
                        f"job {job.status}: {job.error or 'no detail'}",
                        job_id=job_id, status=job.status)
                return job
            time.sleep(interval)

        raise H3TimeoutError(
            f"job {job_id} did not finish within {timeout:.0f}s; it may still "
            f"be running — poll get_job({job_id!r}) to keep checking")

    def generate(self, prompt: str, *, width: int = 608, height: int = 352,
                 duration: float = 5.0, steps: int = 20,
                 seed: Optional[int] = None,
                 timeout: float = _base.DEFAULT_JOB_TIMEOUT,
                 on_progress: Optional[Callable[[Job], None]] = None
                 ) -> VideoResult:
        """Submit, wait, and return the finished video in one call."""
        job = self.create_video(prompt=prompt, width=width, height=height,
                                duration=duration, steps=steps, seed=seed)
        done = self.wait(job.id, timeout=timeout, on_progress=on_progress)
        return VideoResult(job=done, _client=self)

    # -- downloads ---------------------------------------------------------
    def download(self, job_id: str, path: Union[str, Path]) -> Path:
        """Stream the MP4 to disk. Authenticated on every call."""
        dest = Path(path)
        if dest.parent and not dest.parent.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
        with self._http.stream("GET", f"/v1/jobs/{job_id}/video") as resp:
            if resp.status_code >= 400:
                resp.read()
                _base.raise_for_response(resp.status_code, resp.text,
                                         resp.headers)
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes(65536):
                    fh.write(chunk)
        return dest.resolve()

    def content(self, job_id: str) -> bytes:
        """Return the MP4 as bytes."""
        return self._request("GET", f"/v1/jobs/{job_id}/video").content
