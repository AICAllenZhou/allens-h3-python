"""Integration test — hits the real API and uses real GPU time.

Deselected by default. Run explicitly:

    pytest tests/test_integration.py -m integration -s

Requires ALLENS_H3_BASE_URL and ALLENS_H3_API_KEY in the environment.
Generates exactly ONE 5-second clip, to avoid wasting GPU time.
"""

from __future__ import annotations

import os
import time

import pytest

from allens_h3 import H3Client, JobStatus
from allens_h3.exceptions import H3AuthenticationError

pytestmark = pytest.mark.integration

CONFIGURED = bool(os.environ.get("ALLENS_H3_BASE_URL")
                  and os.environ.get("ALLENS_H3_API_KEY"))
# Captured at import time: the autouse `clean_env` fixture clears these from
# os.environ for every test, which is right for unit tests but would hide the
# real configuration from this module.
_BASE_URL = os.environ.get("ALLENS_H3_BASE_URL", "")
_API_KEY = os.environ.get("ALLENS_H3_API_KEY", "")

requires_api = pytest.mark.skipif(
    not CONFIGURED, reason="ALLENS_H3_BASE_URL / ALLENS_H3_API_KEY not set")


@pytest.fixture(scope="module")
def live():
    c = H3Client(api_key=_API_KEY, base_url=_BASE_URL)
    yield c
    c.close()


@requires_api
def test_health(live):
    h = live.health()
    print(f"\n  health: status={h.status} comfyui={h.comfyui} worker={h.worker}")
    assert h.is_ok, f"service not healthy: {h.raw}"


@requires_api
def test_authentication_required():
    """A bad credential must be rejected by the live server."""
    bad = H3Client(api_key="h3c_invalid:h3s_invalid", base_url=_BASE_URL)
    try:
        with pytest.raises(H3AuthenticationError):
            bad.gpu()
    finally:
        bad.close()


@requires_api
def test_gpu_telemetry(live):
    g = live.gpu()
    print(f"\n  gpu: {g.name} {g.temperature_c}C hotspot={g.hotspot_c}C "
          f"{g.power_w}W/{g.power_limit_w}W worker={g.worker}")
    assert g.name
    assert g.power_limit_w and g.power_limit_w <= 200, \
        "power limit must stay at the verified-safe value"


@requires_api
def test_validation_rejected_by_server(live):
    from allens_h3.exceptions import H3ValidationError
    # bypass the client-side check to confirm the server also rejects it
    with pytest.raises(H3ValidationError):
        live._request("POST", "/v1/videos", retry=False,
                      json={"prompt": "t", "width": 999})


@requires_api
def test_full_generation_cycle(live, tmp_path):
    """health -> submit -> poll -> complete -> authenticated download."""
    t0 = time.time()
    print("\n  submitting one 5-second clip...")

    states: list[str] = []
    video = live.generate(
        prompt="A cinematic close-up of raindrops on a window at night, "
               "neon reflections, shallow depth of field.",
        duration=5, width=608, height=352, steps=20, timeout=1800,
        on_progress=lambda j: states.append(j.status))

    assert video.job.status == JobStatus.COMPLETED
    print(f"  job {video.job_id} completed in {time.time()-t0:.0f}s")

    dest = video.download(tmp_path / "integration.mp4")
    size = dest.stat().st_size
    print(f"  downloaded {size} bytes -> {dest.name}")

    assert size > 100_000, "video suspiciously small"
    assert dest.read_bytes()[4:8] == b"ftyp", "not an MP4 container"
    assert JobStatus.GENERATING in states or JobStatus.QUEUED in states


@requires_api
def test_foreign_job_returns_not_found(live):
    """No IDOR: an id we do not own is indistinguishable from a missing one."""
    from allens_h3.exceptions import H3NotFoundError
    with pytest.raises(H3NotFoundError):
        live.get_job("h3_00000000000000000000000000000000")
