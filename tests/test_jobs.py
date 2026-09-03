"""Job lifecycle: submission, validation, polling, cancellation."""

from __future__ import annotations

import httpx
import pytest
import respx

from allens_h3 import Job, JobStatus, VideoResult
from allens_h3.exceptions import H3JobFailedError, H3TimeoutError, H3ValidationError

from .conftest import BASE_URL


class TestJobModel:
    def test_from_dict(self, job_done):
        j = Job.from_dict(job_done)
        assert j.id == "h3_test123"
        assert j.is_complete and j.is_terminal
        assert j.percent == 100.0
        assert j.created_at is not None and j.completed_at is not None

    def test_active_not_terminal(self, job_running):
        j = Job.from_dict(job_running)
        assert not j.is_terminal
        assert j.percent == 50.0

    def test_unknown_fields_ignored(self):
        j = Job.from_dict({"job_id": "x", "status": "queued",
                           "future_field": "value"})
        assert j.id == "x"
        assert j.raw["future_field"] == "value"

    def test_status_sets(self):
        assert JobStatus.COMPLETED in JobStatus.TERMINAL
        assert JobStatus.GENERATING in JobStatus.ACTIVE
        assert not (JobStatus.TERMINAL & JobStatus.ACTIVE)


class TestValidation:
    """Client-side checks fail fast, before spending a round trip."""

    @pytest.mark.parametrize("kwargs,match", [
        ({"prompt": ""}, "empty"),
        ({"prompt": "x" * 2001}, "2000"),
        ({"prompt": "t", "width": 999}, "multiple of 32"),
        ({"prompt": "t", "height": 100}, "multiple of 32"),
        ({"prompt": "t", "duration": 99}, "duration"),
        ({"prompt": "t", "duration": 0.5}, "duration"),
        ({"prompt": "t", "steps": 500}, "steps"),
        ({"prompt": "t", "steps": 1}, "steps"),
        ({"prompt": "t", "seed": -1}, "seed"),
    ])
    def test_rejects_bad_parameters(self, client, kwargs, match):
        with pytest.raises(H3ValidationError, match=match):
            client.create_video(**kwargs)

    @respx.mock
    def test_seed_omitted_when_none(self, client, job_queued):
        route = respx.post(f"{BASE_URL}/v1/videos").mock(
            return_value=httpx.Response(202, json=job_queued))
        client.create_video(prompt="test", seed=None)
        import json
        assert "seed" not in json.loads(route.calls[0].request.content)


class TestSubmission:
    @respx.mock
    def test_create_video(self, client, job_queued):
        respx.post(f"{BASE_URL}/v1/videos").mock(
            return_value=httpx.Response(202, json=job_queued))
        job = client.create_video(prompt="a test prompt", duration=5)
        assert job.id == "h3_test123"
        assert job.status == JobStatus.QUEUED
        assert job.length_frames == 124

    @respx.mock
    def test_get_job(self, client, job_running):
        respx.get(f"{BASE_URL}/v1/jobs/h3_test123").mock(
            return_value=httpx.Response(200, json=job_running))
        assert client.get_job("h3_test123").percent == 50.0

    @respx.mock
    def test_list_jobs_scoped(self, client, job_done):
        respx.get(f"{BASE_URL}/v1/jobs").mock(
            return_value=httpx.Response(200, json={"jobs": [job_done]}))
        jobs = client.list_jobs()
        assert len(jobs) == 1 and jobs[0].id == "h3_test123"


class TestWait:
    @respx.mock
    def test_polls_until_complete(self, client, job_running, job_done):
        respx.get(f"{BASE_URL}/v1/jobs/h3_test123").mock(side_effect=[
            httpx.Response(200, json=job_running),
            httpx.Response(200, json=job_running),
            httpx.Response(200, json=job_done)])
        job = client.wait("h3_test123", poll_interval=0.01)
        assert job.is_complete

    @respx.mock
    def test_progress_callback(self, client, job_running, job_done):
        respx.get(f"{BASE_URL}/v1/jobs/h3_test123").mock(side_effect=[
            httpx.Response(200, json=job_running),
            httpx.Response(200, json=job_done)])
        seen = []
        client.wait("h3_test123", poll_interval=0.01,
                    on_progress=lambda j: seen.append(j.status))
        assert seen == ["generating", "completed"]

    @respx.mock
    def test_failed_job_raises(self, client):
        respx.get(f"{BASE_URL}/v1/jobs/h3_test123").mock(
            return_value=httpx.Response(200, json={
                "job_id": "h3_test123", "status": "failed",
                "error": "GPU unsafe"}))
        with pytest.raises(H3JobFailedError) as ei:
            client.wait("h3_test123", poll_interval=0.01)
        assert ei.value.job_status == "failed"

    @respx.mock
    def test_cancelled_job_raises(self, client):
        respx.get(f"{BASE_URL}/v1/jobs/h3_test123").mock(
            return_value=httpx.Response(200, json={
                "job_id": "h3_test123", "status": "cancelled"}))
        with pytest.raises(H3JobFailedError):
            client.wait("h3_test123", poll_interval=0.01)

    @respx.mock
    def test_timeout(self, client, job_running):
        respx.get(f"{BASE_URL}/v1/jobs/h3_test123").mock(
            return_value=httpx.Response(200, json=job_running))
        with pytest.raises(H3TimeoutError):
            client.wait("h3_test123", timeout=0.2, poll_interval=0.05)


class TestGenerate:
    @respx.mock
    def test_end_to_end(self, client, job_queued, job_done):
        respx.post(f"{BASE_URL}/v1/videos").mock(
            return_value=httpx.Response(202, json=job_queued))
        respx.get(f"{BASE_URL}/v1/jobs/h3_test123").mock(
            return_value=httpx.Response(200, json=job_done))
        video = client.generate(prompt="a test", duration=5)
        assert isinstance(video, VideoResult)
        assert video.job_id == "h3_test123"


class TestCancel:
    @respx.mock
    def test_cancel(self, client):
        respx.post(f"{BASE_URL}/v1/jobs/h3_test123/cancel").mock(
            return_value=httpx.Response(200, json={"job_id": "h3_test123",
                                                   "status": "cancelling"}))
        respx.get(f"{BASE_URL}/v1/jobs/h3_test123").mock(
            return_value=httpx.Response(200, json={"job_id": "h3_test123",
                                                   "status": "cancelled"}))
        assert client.cancel("h3_test123").status == "cancelled"
