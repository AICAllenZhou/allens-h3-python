"""Client construction, configuration and request behaviour."""

from __future__ import annotations

import httpx
import pytest
import respx

from allens_h3 import AsyncH3Client, GPUStatus, H3Client, HealthStatus
from allens_h3.exceptions import H3ValidationError

from .conftest import API_KEY, BASE_URL


class TestConfiguration:
    def test_explicit_arguments(self):
        c = H3Client(api_key="k", base_url="https://example.com")
        assert c.base_url == "https://example.com"
        c.close()

    def test_reads_environment(self, monkeypatch):
        monkeypatch.setenv("ALLENS_H3_API_KEY", "env_key")
        monkeypatch.setenv("ALLENS_H3_BASE_URL", "https://env.example.com")
        c = H3Client()
        assert c.base_url == "https://env.example.com"
        c.close()

    def test_explicit_beats_environment(self, monkeypatch):
        monkeypatch.setenv("ALLENS_H3_BASE_URL", "https://env.example.com")
        c = H3Client(api_key="k", base_url="https://explicit.example.com")
        assert c.base_url == "https://explicit.example.com"
        c.close()

    def test_missing_key_raises(self):
        with pytest.raises(H3ValidationError, match="API key"):
            H3Client(base_url=BASE_URL)

    def test_missing_url_raises(self):
        with pytest.raises(H3ValidationError, match="base URL"):
            H3Client(api_key=API_KEY)

    def test_trailing_slash_stripped(self):
        c = H3Client(api_key="k", base_url="https://example.com/")
        assert c.base_url == "https://example.com"
        c.close()

    def test_no_hardcoded_endpoint(self):
        """The tunnel hostname must never be baked into the package."""
        import pathlib

        import allens_h3
        root = pathlib.Path(allens_h3.__file__).parent
        for py in root.rglob("*.py"):
            assert "trycloudflare.com" not in py.read_text(encoding="utf-8"), \
                f"{py.name} hard-codes a tunnel hostname"


class TestURLValidation:
    @pytest.mark.parametrize("url", [
        "ftp://example.com",
        "not-a-url",
        "https://user:pass@example.com",
        "https://example.com?token=abc",
        "http://remote-host.com",          # plaintext to a remote host
    ])
    def test_rejects_bad_urls(self, url):
        with pytest.raises(H3ValidationError):
            H3Client(api_key="k", base_url=url)

    @pytest.mark.parametrize("url", [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "https://example.com",
    ])
    def test_accepts_good_urls(self, url):
        H3Client(api_key="k", base_url=url).close()


class TestRepr:
    def test_repr_hides_key(self, client):
        assert API_KEY not in repr(client)
        assert "test.example.com" in repr(client)


class TestEndpoints:
    @respx.mock
    def test_health(self, client):
        respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(200, json={
                "status": "ok", "comfyui": "online", "gpu": "available",
                "worker": "idle"}))
        h = client.health()
        assert isinstance(h, HealthStatus)
        assert h.is_ok

    @respx.mock
    def test_gpu(self, client):
        respx.get(f"{BASE_URL}/v1/gpu").mock(
            return_value=httpx.Response(200, json={
                "name": "NVIDIA GeForce RTX 3090", "temperature_c": 45.0,
                "hotspot_c": 60.0, "power_w": 30.0, "power_limit_w": 180.0,
                "worker": "idle", "queue_depth": 0}))
        g = client.gpu()
        assert isinstance(g, GPUStatus)
        assert g.name == "NVIDIA GeForce RTX 3090"
        assert g.hotspot_c == 60.0
        assert not g.is_busy

    @respx.mock
    def test_sends_bearer_header(self, client):
        route = respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"}))
        client.health()
        assert route.calls[0].request.headers["Authorization"] == \
            f"Bearer {API_KEY}"


class TestRetry:
    @respx.mock
    def test_retries_503(self, client):
        route = respx.get(f"{BASE_URL}/health").mock(side_effect=[
            httpx.Response(503), httpx.Response(200, json={"status": "ok"})])
        assert client.health().status == "ok"
        assert route.call_count == 2

    @respx.mock
    def test_never_retries_generation(self, client):
        """A duplicate POST would occupy the single GPU twice."""
        route = respx.post(f"{BASE_URL}/v1/videos").mock(
            return_value=httpx.Response(503))
        from allens_h3.exceptions import H3GPUUnavailableError
        with pytest.raises(H3GPUUnavailableError):
            client.create_video(prompt="test")
        assert route.call_count == 1


class TestAsyncClient:
    @respx.mock
    async def test_async_health(self):
        respx.get(f"{BASE_URL}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"}))
        async with AsyncH3Client(api_key=API_KEY, base_url=BASE_URL) as c:
            assert (await c.health()).is_ok

    async def test_async_repr_hides_key(self):
        async with AsyncH3Client(api_key=API_KEY, base_url=BASE_URL) as c:
            assert API_KEY not in repr(c)
