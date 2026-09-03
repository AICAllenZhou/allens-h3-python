"""Asynchronous client — mirrors :class:`allens_h3.H3Client` exactly.

Shares all policy with the sync client through ``_base``; only the transport
differs, so the two cannot drift apart in behaviour.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union

import httpx

from . import _base
from .exceptions import (
    H3ConnectionError,
    H3JobFailedError,
    H3RateLimitError,
    H3TimeoutError,
)
from .models import GPUStatus, HealthStatus, Job, JobStatus, VideoResult

__all__ = ["AsyncH3Client"]


class AsyncH3Client:
    """Async client for Allen's MiniMax H3 API.

        >>> async with AsyncH3Client() as client:
        ...     video = await client.generate(prompt="A cinematic commercial")
        ...     await video.download("output.mp4")
    """

    def __init__(self, api_key: Optional[str] = None,
                 base_url: Optional[str] = None,
                 timeout: float = _base.DEFAULT_TIMEOUT,
                 poll_interval: float = _base.DEFAULT_POLL_INTERVAL) -> None:
        self._api_key, self.base_url = _base.resolve_config(api_key, base_url)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout,
                                       verify=True, follow_redirects=False,
                                       headers=_base.auth_headers(self._api_key))

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AsyncH3Client":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return f"<AsyncH3Client base_url={self.base_url!r}>"

    async def _request(self, method: str, path: str, *, retry: bool = True,
                       **kw: Any) -> httpx.Response:
        attempt = 0
        while True:
            try:
                resp = await self._http.request(method, path, **kw)
            except httpx.TimeoutException as e:
                if retry and attempt < _base.MAX_RETRIES:
                    await asyncio.sleep(_base.backoff_delay(attempt))
                    attempt += 1
                    continue
                raise H3ConnectionError(f"request timed out: {e}") from e
            except httpx.HTTPError as e:
                if retry and attempt < _base.MAX_RETRIES:
                    await asyncio.sleep(_base.backoff_delay(attempt))
                    attempt += 1
                    continue
                raise H3ConnectionError(f"could not reach the server: {e}") from e

            if (retry and resp.status_code in _base.RETRY_STATUSES
                    and attempt < _base.MAX_RETRIES):
                await asyncio.sleep(_base.backoff_delay(attempt))
                attempt += 1
                continue

            if resp.status_code == 429 and retry and attempt < _base.MAX_RETRIES:
                wait = _base.parse_retry_after(resp.headers.get("Retry-After"))
                if wait is not None and wait <= 30:
                    await asyncio.sleep(wait)
                    attempt += 1
                    continue

            _base.raise_for_response(resp.status_code, resp.text, resp.headers)
            return resp

    async def health(self) -> HealthStatus:
        r = await self._request("GET", "/health")
        return HealthStatus.from_dict(r.json())

    async def gpu(self) -> GPUStatus:
        r = await self._request("GET", "/v1/gpu")
        return GPUStatus.from_dict(r.json())

    async def create_video(self, prompt: str, *, width: int = 608,
                           height: int = 352, duration: float = 5.0,
                           steps: int = 20,
                           seed: Optional[int] = None) -> Job:
        payload = _base.build_payload(prompt, width, height, duration, steps,
                                      seed)
        r = await self._request("POST", "/v1/videos", json=payload, retry=False)
        return Job.from_dict(r.json())

    async def get_job(self, job_id: str) -> Job:
        r = await self._request("GET", f"/v1/jobs/{job_id}")
        return Job.from_dict(r.json())

    async def list_jobs(self, limit: int = 20) -> list[Job]:
        r = await self._request("GET", "/v1/jobs", params={"limit": limit})
        return [Job.from_dict(j) for j in r.json().get("jobs", [])]

    async def cancel(self, job_id: str) -> Job:
        await self._request("POST", f"/v1/jobs/{job_id}/cancel", retry=False)
        return await self.get_job(job_id)

    async def wait(self, job_id: str, *,
                   timeout: float = _base.DEFAULT_JOB_TIMEOUT,
                   poll_interval: Optional[float] = None,
                   on_progress: Optional[Callable[[Job], Any]] = None) -> Job:
        interval = poll_interval or self.poll_interval
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        transient = 0

        while loop.time() < deadline:
            try:
                job = await self.get_job(job_id)
                transient = 0
            except (H3ConnectionError, H3RateLimitError):
                transient += 1
                if transient > 10:
                    raise
                await asyncio.sleep(interval)
                continue

            if on_progress:
                result = on_progress(job)
                if isinstance(result, Awaitable):
                    await result
            if job.is_terminal:
                if job.status != JobStatus.COMPLETED:
                    raise H3JobFailedError(
                        f"job {job.status}: {job.error or 'no detail'}",
                        job_id=job_id, status=job.status)
                return job
            await asyncio.sleep(interval)

        raise H3TimeoutError(
            f"job {job_id} did not finish within {timeout:.0f}s; it may still "
            f"be running — poll get_job({job_id!r}) to keep checking")

    async def generate(self, prompt: str, *, width: int = 608,
                       height: int = 352, duration: float = 5.0,
                       steps: int = 20, seed: Optional[int] = None,
                       timeout: float = _base.DEFAULT_JOB_TIMEOUT,
                       on_progress: Optional[Callable[[Job], Any]] = None
                       ) -> VideoResult:
        job = await self.create_video(prompt=prompt, width=width, height=height,
                                      duration=duration, steps=steps, seed=seed)
        done = await self.wait(job.id, timeout=timeout, on_progress=on_progress)
        return VideoResult(job=done, _client=self)

    async def download(self, job_id: str, path: Union[str, Path]) -> Path:
        dest = Path(path)
        if dest.parent and not dest.parent.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
        async with self._http.stream("GET", f"/v1/jobs/{job_id}/video") as resp:
            if resp.status_code >= 400:
                await resp.aread()
                _base.raise_for_response(resp.status_code, resp.text,
                                         resp.headers)
            with dest.open("wb") as fh:
                async for chunk in resp.aiter_bytes(65536):
                    fh.write(chunk)
        return dest.resolve()

    async def content(self, job_id: str) -> bytes:
        r = await self._request("GET", f"/v1/jobs/{job_id}/video")
        return r.content
