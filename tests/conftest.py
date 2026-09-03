"""Shared fixtures. All unit tests are fully mocked — no network, no GPU."""

from __future__ import annotations

import os

import pytest

BASE_URL = "https://test.example.com"
API_KEY = "test_key_not_a_real_credential"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Never let a developer's real credentials leak into a unit test."""
    monkeypatch.delenv("ALLENS_H3_API_KEY", raising=False)
    monkeypatch.delenv("ALLENS_H3_BASE_URL", raising=False)


@pytest.fixture
def client():
    from allens_h3 import H3Client
    c = H3Client(api_key=API_KEY, base_url=BASE_URL)
    yield c
    c.close()


@pytest.fixture
def job_queued() -> dict:
    return {"job_id": "h3_test123", "status": "queued",
            "queue_position": 1, "length_frames": 124}


@pytest.fixture
def job_running() -> dict:
    return {"job_id": "h3_test123", "status": "generating", "progress": 0.5,
            "created_at": "2026-09-03T05:00:00+00:00"}


@pytest.fixture
def job_done() -> dict:
    return {"job_id": "h3_test123", "status": "completed", "progress": 1.0,
            "created_at": "2026-09-03T05:00:00+00:00",
            "finished_at": "2026-09-03T05:05:00+00:00",
            "video_url": "/v1/jobs/h3_test123/video"}
