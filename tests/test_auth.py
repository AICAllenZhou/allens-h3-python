"""Authentication, error mapping and secret hygiene."""

from __future__ import annotations

import httpx
import pytest
import respx

from allens_h3 import H3Client
from allens_h3.exceptions import (
    H3AuthenticationError,
    H3ConflictError,
    H3Error,
    H3GPUUnavailableError,
    H3NotFoundError,
    H3PermissionError,
    H3RateLimitError,
    H3ValidationError,
    _scrub,
)

from .conftest import API_KEY, BASE_URL


class TestStatusMapping:
    @pytest.mark.parametrize("status,exc", [
        (400, H3ValidationError),
        (401, H3AuthenticationError),
        (403, H3PermissionError),
        (404, H3NotFoundError),
        (409, H3ConflictError),
        (413, H3ValidationError),
        (422, H3ValidationError),
        (429, H3RateLimitError),
        (503, H3GPUUnavailableError),
    ])
    @respx.mock
    def test_maps_status(self, client, status, exc):
        respx.get(f"{BASE_URL}/v1/gpu").mock(
            return_value=httpx.Response(status, json={"error": "denied"}))
        with pytest.raises(exc):
            client.gpu()

    @respx.mock
    def test_request_id_preserved(self, client):
        respx.get(f"{BASE_URL}/v1/gpu").mock(
            return_value=httpx.Response(
                401, json={"error": "unauthorized", "request_id": "abc123"}))
        with pytest.raises(H3AuthenticationError) as ei:
            client.gpu()
        assert ei.value.request_id == "abc123"
        assert "abc123" in str(ei.value)

    @respx.mock
    def test_retry_after_captured(self, client):
        respx.get(f"{BASE_URL}/v1/gpu").mock(
            return_value=httpx.Response(429, json={"error": "slow down"},
                                        headers={"Retry-After": "600"}))
        with pytest.raises(H3RateLimitError) as ei:
            client.gpu()
        assert ei.value.retry_after == 600.0

    def test_all_inherit_base(self):
        for exc in (H3AuthenticationError, H3PermissionError, H3NotFoundError,
                    H3ConflictError, H3RateLimitError, H3ValidationError,
                    H3GPUUnavailableError):
            assert issubclass(exc, H3Error)


class TestSecretRedaction:
    @pytest.mark.parametrize("raw,forbidden", [
        ("Authorization: Bearer h3s_supersecret", "h3s_supersecret"),
        ("bearer h3c_abcdef0123456789", "h3c_abcdef0123456789"),
        ("key is h3s_verylongsecretvalue123", "h3s_verylongsecretvalue123"),
    ])
    def test_scrub_removes_secrets(self, raw, forbidden):
        out = _scrub(raw)
        assert forbidden not in out
        assert "<redacted>" in out

    def test_exception_message_scrubbed(self):
        e = H3Error("failed with Authorization: Bearer h3s_leaked_secret")
        assert "h3s_leaked_secret" not in str(e)

    @respx.mock
    def test_server_echo_is_scrubbed(self, client):
        """Even if a server echoed a credential back, it must not surface."""
        respx.get(f"{BASE_URL}/v1/gpu").mock(
            return_value=httpx.Response(
                401, json={"error": "bad token h3s_should_not_appear"}))
        with pytest.raises(H3AuthenticationError) as ei:
            client.gpu()
        assert "h3s_should_not_appear" not in str(ei.value)


class TestTLS:
    def test_verification_enabled(self, client):
        # httpx exposes no public flag; assert there is no opt-out parameter
        import inspect
        sig = inspect.signature(H3Client.__init__)
        assert "verify" not in sig.parameters, \
            "the SDK must not offer a way to disable TLS verification"

    def test_no_verify_false_in_source(self):
        import pathlib

        import allens_h3
        root = pathlib.Path(allens_h3.__file__).parent
        for py in root.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            assert "verify=False" not in text, f"{py.name} disables TLS"


class TestCredentialsNeverPersisted:
    def test_key_not_written_to_disk(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        c = H3Client(api_key=API_KEY, base_url=BASE_URL)
        c.close()
        for f in tmp_path.rglob("*"):
            if f.is_file():
                assert API_KEY not in f.read_text(encoding="utf-8",
                                                  errors="ignore")
