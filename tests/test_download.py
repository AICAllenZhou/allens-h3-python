"""Authenticated download paths."""

from __future__ import annotations

import httpx
import pytest
import respx

from allens_h3 import Job, VideoResult
from allens_h3.exceptions import H3ConflictError, H3NotFoundError

from .conftest import API_KEY, BASE_URL

FAKE_MP4 = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 512


class TestDownload:
    @respx.mock
    def test_writes_file(self, client, tmp_path):
        respx.get(f"{BASE_URL}/v1/jobs/h3_test123/video").mock(
            return_value=httpx.Response(200, content=FAKE_MP4))
        dest = tmp_path / "out.mp4"
        path = client.download("h3_test123", dest)
        assert path.exists()
        assert path.read_bytes() == FAKE_MP4

    @respx.mock
    def test_creates_parent_directories(self, client, tmp_path):
        respx.get(f"{BASE_URL}/v1/jobs/h3_test123/video").mock(
            return_value=httpx.Response(200, content=FAKE_MP4))
        dest = tmp_path / "a" / "b" / "out.mp4"
        assert client.download("h3_test123", dest).exists()

    @respx.mock
    def test_download_is_authenticated(self, client, tmp_path):
        route = respx.get(f"{BASE_URL}/v1/jobs/h3_test123/video").mock(
            return_value=httpx.Response(200, content=FAKE_MP4))
        client.download("h3_test123", tmp_path / "out.mp4")
        assert route.calls[0].request.headers["Authorization"] == \
            f"Bearer {API_KEY}"

    @respx.mock
    def test_content_returns_bytes(self, client):
        respx.get(f"{BASE_URL}/v1/jobs/h3_test123/video").mock(
            return_value=httpx.Response(200, content=FAKE_MP4))
        assert client.content("h3_test123") == FAKE_MP4

    @respx.mock
    def test_unfinished_job_conflicts(self, client, tmp_path):
        respx.get(f"{BASE_URL}/v1/jobs/h3_test123/video").mock(
            return_value=httpx.Response(409,
                                        json={"error": "job is generating"}))
        with pytest.raises(H3ConflictError):
            client.download("h3_test123", tmp_path / "out.mp4")

    @respx.mock
    def test_foreign_job_not_found(self, client, tmp_path):
        """Another client's job must be indistinguishable from a missing one."""
        respx.get(f"{BASE_URL}/v1/jobs/h3_other/video").mock(
            return_value=httpx.Response(404, json={"error": "not found"}))
        with pytest.raises(H3NotFoundError):
            client.download("h3_other", tmp_path / "out.mp4")


class TestVideoResult:
    @respx.mock
    def test_download_via_result(self, client, tmp_path, job_done):
        respx.get(f"{BASE_URL}/v1/jobs/h3_test123/video").mock(
            return_value=httpx.Response(200, content=FAKE_MP4))
        video = VideoResult(job=Job.from_dict(job_done), _client=client)
        assert video.download(tmp_path / "out.mp4").exists()

    def test_unbound_result_raises(self, job_done, tmp_path):
        video = VideoResult(job=Job.from_dict(job_done))
        with pytest.raises(RuntimeError, match="not bound"):
            video.download(tmp_path / "out.mp4")


class TestAsyncDownload:
    @respx.mock
    async def test_async_download(self, tmp_path):
        from allens_h3 import AsyncH3Client
        respx.get(f"{BASE_URL}/v1/jobs/h3_test123/video").mock(
            return_value=httpx.Response(200, content=FAKE_MP4))
        async with AsyncH3Client(api_key=API_KEY, base_url=BASE_URL) as c:
            path = await c.download("h3_test123", tmp_path / "out.mp4")
        assert path.read_bytes() == FAKE_MP4
