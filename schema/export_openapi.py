"""Export a static OpenAPI 3.1 document for Allen's MiniMax H3 API.

The production server runs with openapi_url=None / docs_url=None / redoc_url=None
on purpose: the public attack surface stays minimal and the schema is never
served from the box. This script imports the SAME `app` object the server runs
and asks FastAPI to generate the schema in-process, so the route table, request
models and validation constraints are derived from the real application rather
than transcribed by hand.

FastAPI's generated document is then enriched with what the framework cannot
infer from signatures alone:

  * bearer security scheme + per-route scope requirements (these live inside
    Depends(require("read"|"generate")) and are invisible to the generator)
  * response schemas (the handlers return plain dicts, not response_model=...)
  * the error envelope produced by the custom HTTPException handler
  * the binary video download response

Run:  .venv/Scripts/python.exe tools/export_openapi.py [-o out.json]

Nothing here mutates the running service. It is import-only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
API_SERVER = HERE.parent
sys.path.insert(0, str(API_SERVER))

from fastapi.openapi.utils import get_openapi  # noqa: E402

import config  # noqa: E402
import main  # noqa: E402
import store  # noqa: E402

SDK_VERSION = "1.0.0"

W_LO, W_HI = config.LIMITS["width"]
H_LO, H_HI = config.LIMITS["height"]
D_LO, D_HI = config.LIMITS["duration"]
S_LO, S_HI = config.LIMITS["steps"]
PROMPT_MAX = config.LIMITS["prompt_chars"]
DEF = config.DEFAULTS

JOB_STATUSES = [store.QUEUED, store.LOADING, store.GENERATING,
                store.DECODING, store.COMPLETED, store.FAILED,
                store.CANCELLED]

# --------------------------------------------------------------- error bodies
# main.http_exc() replaces every detail with a generic string unless
# H3_DEBUG_ERRORS=1, except 409/422/429 which keep semantic text clients need.
ERROR_SCHEMA = {
    "type": "object",
    "required": ["detail"],
    "properties": {
        "detail": {
            "type": "string",
            "description": "Generic reason. Server-side detail is deliberately "
                           "withheld so responses cannot leak paths, "
                           "tracebacks, usernames or package versions.",
        },
        "request_id": {
            "type": "string",
            "description": "Correlates with the server audit log.",
        },
    },
}


def err(desc: str, example: str) -> dict:
    return {
        "description": desc,
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/Error"},
                "example": {"detail": example, "request_id": "a1b2c3d4e5f6"},
            }
        },
    }


AUTH_ERRORS = {
    "401": err("Missing, malformed or invalid credential. Every failure mode "
               "returns an identical body so the API cannot be used as a "
               "credential oracle.", "unauthorized"),
    "403": err("Authenticated, but the credential lacks the required scope.",
               "forbidden"),
    "429": err("Per-client rate limit exceeded. Retry-After header is set.",
               "client rate limit exceeded"),
}


def main_export(out_path: Path) -> int:
    schema = get_openapi(
        title="Allen's MiniMax H3 API",
        version=main.app.version,
        routes=main.app.routes,
        description=(
            "Text-to-video generation on a private RTX 3090 workstation.\n\n"
            "**This is a credential-protected private service.** There is no "
            "public sign-up and no anonymous access. The host is reachable "
            "only through an operator-managed tunnel whose hostname changes "
            "between restarts, so clients must configure `ALLENS_H3_BASE_URL` "
            "themselves — no endpoint is ever hardcoded in the SDK.\n\n"
            "### Authentication\n"
            "`Authorization: Bearer <client_id>:<secret>`\n\n"
            "### Scopes\n"
            "- `read` — inspect GPU telemetry, list and poll your own jobs, "
            "download your own finished videos.\n"
            "- `generate` — submit and cancel jobs.\n\n"
            "A credential carries a comma-separated scope set (commonly "
            "`generate,read`). A `read`-only credential receives `403` on any "
            "generating route.\n\n"
            "### Isolation\n"
            "Jobs are strictly per-client. A job belonging to another client "
            "is indistinguishable from one that does not exist — both return "
            "`404`.\n\n"
            "### Schema provenance\n"
            "The production server runs with `openapi_url=None`, `docs_url="
            "None` and `redoc_url=None`. This document is generated offline "
            "from the live application object and shipped with the SDK; the "
            "server itself never exposes it."
        ),
    )

    schema["info"]["x-sdk-version"] = SDK_VERSION
    schema["info"]["contact"] = {
        "name": "Allen Zhou",
        "url": "https://github.com/AICAllenZhou/allens-h3-python",
    }
    schema["info"]["license"] = {
        "name": "MIT",
        "url": "https://github.com/AICAllenZhou/allens-h3-python/blob/main/LICENSE",
    }
    schema["servers"] = [{
        "url": "{base_url}",
        "description": "Operator-supplied endpoint (ALLENS_H3_BASE_URL). The "
                       "tunnel hostname rotates on restart.",
        "variables": {"base_url": {"default": "http://127.0.0.1:8000"}},
    }]

    comp = schema.setdefault("components", {})
    comp.setdefault("securitySchemes", {})["bearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "description": "Value is `<client_id>:<secret>`, issued by the "
                       "operator with `h3_admin.py issue`. Shown once and "
                       "not recoverable.",
    }

    sch = comp.setdefault("schemas", {})
    sch["Error"] = ERROR_SCHEMA

    sch["HealthStatus"] = {
        "type": "object",
        "required": ["status", "comfyui", "gpu", "worker"],
        "properties": {
            "status": {"type": "string", "enum": ["ok", "degraded"]},
            "comfyui": {"type": "string", "enum": ["online", "offline"]},
            "gpu": {"type": "string", "enum": ["available", "unavailable"]},
            "worker": {"type": "string", "enum": ["idle", "busy"]},
        },
        "example": {"status": "ok", "comfyui": "online",
                    "gpu": "available", "worker": "idle"},
    }

    sch["GPUStatus"] = {
        "type": "object",
        "required": ["name", "vram_used_mb", "vram_total_mb", "temperature_c",
                     "power_w", "power_limit_w", "utilization_pct", "worker",
                     "queue_depth"],
        "properties": {
            "name": {"type": "string"},
            "vram_used_mb": {"type": "number"},
            "vram_total_mb": {"type": "number"},
            "temperature_c": {"type": "number"},
            "hotspot_c": {"type": ["number", "null"],
                          "description": "Hotspot sensor; null when the "
                                         "driver does not expose it."},
            "vram_max_c": {"type": ["number", "null"]},
            "power_w": {"type": "number"},
            "power_limit_w": {
                "type": "number",
                "description": "Enforced limit. This deployment pins 180 W; "
                               "the card has dropped off the bus at higher "
                               "sustained draw.",
            },
            "utilization_pct": {"type": "number"},
            "worker": {"type": "string", "enum": ["idle", "busy"]},
            "queue_depth": {"type": "integer"},
        },
        "example": {"name": "NVIDIA GeForce RTX 3090", "vram_used_mb": 1207.0,
                    "vram_total_mb": 24576.0, "temperature_c": 32.0,
                    "hotspot_c": 44.0, "vram_max_c": 40.0, "power_w": 18.25,
                    "power_limit_w": 180.0, "utilization_pct": 0.0,
                    "worker": "idle", "queue_depth": 0},
    }

    sch["JobAccepted"] = {
        "type": "object",
        "required": ["job_id", "status", "queue_position", "length_frames"],
        "properties": {
            "job_id": {"type": "string"},
            "status": {"type": "string", "enum": [store.QUEUED]},
            "queue_position": {"type": "integer"},
            "length_frames": {"type": "integer"},
        },
        "example": {"job_id": "job_7f2a91c4", "status": "queued",
                    "queue_position": 0, "length_frames": 81},
    }

    sch["JobStatus"] = {
        "type": "object",
        "required": ["job_id", "status", "progress", "created_at",
                     "finished_at"],
        "properties": {
            "job_id": {"type": "string"},
            "status": {"type": "string", "enum": JOB_STATUSES},
            "progress": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "created_at": {"type": "string", "format": "date-time"},
            "finished_at": {"type": ["string", "null"],
                            "format": "date-time"},
            "error": {"type": "string", "maxLength": 200,
                      "description": "Present only when status is 'failed'."},
            "video_url": {
                "type": "string",
                "description": "Relative path, present only when status is "
                               "'completed'. Join against your base URL.",
            },
        },
        "example": {"job_id": "job_7f2a91c4", "status": "completed",
                    "progress": 1.0, "created_at": "2026-09-03T21:40:00Z",
                    "finished_at": "2026-09-03T21:43:12Z",
                    "video_url": "/v1/jobs/job_7f2a91c4/video"},
    }

    sch["JobSummary"] = {
        "type": "object",
        "required": ["job_id", "status", "progress", "created_at",
                     "finished_at"],
        "properties": {
            "job_id": {"type": "string"},
            "status": {"type": "string", "enum": JOB_STATUSES},
            "progress": {"type": "number"},
            "created_at": {"type": "string", "format": "date-time"},
            "finished_at": {"type": ["string", "null"],
                            "format": "date-time"},
        },
    }

    sch["JobList"] = {
        "type": "object",
        "required": ["jobs"],
        "properties": {
            "jobs": {"type": "array",
                     "items": {"$ref": "#/components/schemas/JobSummary"}},
        },
    }

    sch["CancelAccepted"] = {
        "type": "object",
        "required": ["job_id", "status"],
        "properties": {
            "job_id": {"type": "string"},
            "status": {"type": "string", "enum": ["cancelling"]},
        },
        "example": {"job_id": "job_7f2a91c4", "status": "cancelling"},
    }

    paths = schema["paths"]

    def op(path: str, method: str) -> dict:
        return paths[path][method]

    # ------------------------------------------------------------- /health
    o = op("/health", "get")
    o["summary"] = "Liveness probe"
    o["description"] = ("The only unauthenticated route. Deliberately returns "
                        "no hostnames, versions or filesystem paths.")
    o["operationId"] = "health"
    o["security"] = []
    o["responses"] = {
        "200": {"description": "Service reachable. `status` is 'degraded' "
                               "when ComfyUI or the GPU is unavailable.",
                "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/HealthStatus"}}}},
    }

    # ------------------------------------------------------------- /v1/gpu
    o = op("/v1/gpu", "get")
    o["summary"] = "GPU telemetry"
    o["operationId"] = "getGpu"
    o["security"] = [{"bearerAuth": []}]
    o["x-required-scope"] = "read"
    o["responses"] = {
        "200": {"description": "Live telemetry.",
                "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/GPUStatus"}}}},
        **AUTH_ERRORS,
        "503": err("GPU not available to the driver.", "service unavailable"),
    }

    # ---------------------------------------------------------- /v1/videos
    o = op("/v1/videos", "post")
    o["summary"] = "Submit a generation job"
    o["description"] = (
        "Returns `202` immediately; generation is asynchronous. Poll "
        "`GET /v1/jobs/{job_id}` until the status is terminal, then fetch the "
        "video.\n\nRejected with `503` when ComfyUI is down or the GPU "
        "thermal/power gate considers it unsafe to start work."
    )
    o["operationId"] = "createVideo"
    o["security"] = [{"bearerAuth": []}]
    o["x-required-scope"] = "generate"
    o["responses"] = {
        "202": {"description": "Job queued.",
                "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/JobAccepted"}}}},
        "400": err("Malformed request.", "bad request"),
        **AUTH_ERRORS,
        "409": err("Per-client queue depth exceeded.",
                   "too many queued jobs"),
        "413": err(f"Body larger than {config.MAX_BODY_BYTES} bytes.",
                   "payload too large"),
        "422": err("Parameter failed validation — dimensions out of range or "
                   "not a multiple of 32, duration/steps out of range, or an "
                   "unknown field was supplied (extra fields are rejected).",
                   "width must be a multiple of 32"),
        "503": err("ComfyUI offline, or the GPU safety gate blocked the "
                   "start.", "service unavailable"),
    }

    # ------------------------------------------------------------ /v1/jobs
    o = op("/v1/jobs", "get")
    o["summary"] = "List your recent jobs"
    o["description"] = ("Scoped to the calling credential. Other clients' jobs "
                        "are never returned.")
    o["operationId"] = "listJobs"
    o["security"] = [{"bearerAuth": []}]
    o["x-required-scope"] = "read"
    for p in o.get("parameters", []):
        if p.get("name") == "limit":
            p["description"] = "Clamped server-side to 1-100."
            p.setdefault("schema", {}).update(
                {"minimum": 1, "maximum": 100, "default": 20})
    o["responses"] = {
        "200": {"description": "Most recent first.",
                "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/JobList"}}}},
        **AUTH_ERRORS,
    }

    # -------------------------------------------------- /v1/jobs/{job_id}
    o = op("/v1/jobs/{job_id}", "get")
    o["summary"] = "Poll one job"
    o["operationId"] = "getJob"
    o["security"] = [{"bearerAuth": []}]
    o["x-required-scope"] = "read"
    o["responses"] = {
        "200": {"description": "Current state. `video_url` appears once the "
                               "job completes; `error` only on failure.",
                "content": {"application/json": {
                    "schema": {"$ref": "#/components/schemas/JobStatus"}}}},
        **AUTH_ERRORS,
        "404": err("Unknown job, or a job owned by another client. The two "
                   "cases are intentionally indistinguishable.", "not found"),
    }

    # -------------------------------------------- /v1/jobs/{job_id}/video
    o = op("/v1/jobs/{job_id}/video", "get")
    o["summary"] = "Download the finished video"
    o["operationId"] = "getJobVideo"
    o["security"] = [{"bearerAuth": []}]
    o["x-required-scope"] = "read"
    o["responses"] = {
        "200": {"description": "MP4 file attachment.",
                "content": {"video/mp4": {
                    "schema": {"type": "string", "format": "binary"}}}},
        **AUTH_ERRORS,
        "404": err("Unknown job, foreign job, or the file is missing.",
                   "not found"),
        "409": err("Job has not completed yet.", "job is generating"),
    }

    # ------------------------------------------- /v1/jobs/{job_id}/cancel
    o = op("/v1/jobs/{job_id}/cancel", "post")
    o["summary"] = "Cancel a running or queued job"
    o["description"] = ("Cancellation is cooperative: the response is "
                        "`cancelling`, not `cancelled`. Poll the job to "
                        "observe the terminal state.")
    o["operationId"] = "cancelJob"
    o["security"] = [{"bearerAuth": []}]
    o["x-required-scope"] = "generate"
    o["responses"] = {
        "200": {"description": "Cancellation requested.",
                "content": {"application/json": {
                    "schema": {
                        "$ref": "#/components/schemas/CancelAccepted"}}}},
        **AUTH_ERRORS,
        "404": err("Unknown or foreign job.", "not found"),
        "409": err("Job already reached a terminal state.",
                   "job already completed"),
    }

    # Constraints live in field_validators, which the generator cannot see.
    vr = sch.get("VideoRequest", {}).get("properties", {})
    if vr:
        vr["prompt"].update({"maxLength": PROMPT_MAX, "minLength": 1})
        vr["width"].update({"minimum": W_LO, "maximum": W_HI,
                            "multipleOf": 32, "default": DEF["width"]})
        vr["height"].update({"minimum": H_LO, "maximum": H_HI,
                             "multipleOf": 32, "default": DEF["height"]})
        vr["duration"].update({"minimum": D_LO, "maximum": D_HI,
                               "default": DEF["duration"]})
        vr["steps"].update({"minimum": S_LO, "maximum": S_HI,
                            "default": DEF["steps"]})
        vr["seed"].update({"default": DEF["seed"]})
        sch["VideoRequest"]["additionalProperties"] = False

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"  openapi     {schema['openapi']}")
    print(f"  api version {schema['info']['version']}")
    print(f"  sdk version {SDK_VERSION}")
    print(f"  paths       {len(schema['paths'])}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=str(HERE / "openapi.json"))
    a = ap.parse_args()
    raise SystemExit(main_export(Path(a.out)))
