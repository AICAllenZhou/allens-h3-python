# API Schema

Machine-readable OpenAPI 3.1 description of Allen's MiniMax H3 API.

## Files

| File | Purpose |
|---|---|
| `openapi.json` | Current schema. Track this one. |
| `openapi-1.0.0.json` | Frozen snapshot matching SDK `1.0.0`. |
| `export_openapi.py` | Generator. Runs on the API host, not here. |

## Why the server does not serve this

The production service is constructed with:

```python
app = FastAPI(..., docs_url=None, redoc_url=None, openapi_url=None)
```

That is deliberate. It is a credential-protected private service reached through
an operator-managed tunnel, so `/openapi.json`, `/docs` and `/redoc` all return
`404` by design — the route table, parameter ranges and model shapes are not
published from the box.

The schema is instead generated offline and shipped with the SDK. Agents and
integrators get a precise contract; the deployment keeps its small surface.

## How it is produced

`export_openapi.py` imports the **same `app` object the server runs** and calls
FastAPI's own generator, so paths, methods, path/query parameters and the
`VideoRequest` model come from the live application rather than being
transcribed by hand.

FastAPI cannot infer three things from the source, so the exporter adds them
explicitly:

- **Scopes.** Requirements live inside `Depends(require("read" | "generate"))`,
  which is opaque to the generator. Each operation carries `x-required-scope`.
- **Response schemas.** Handlers return plain dicts, not `response_model=`.
- **Error responses.** These come from a custom `HTTPException` handler that
  replaces detail text with generic strings.

Field constraints (`multipleOf: 32`, dimension and duration ranges) live in
Pydantic `field_validator`s and are likewise restored into the document.

## Verification

The committed schema was checked two ways:

1. **Spec validity** — passes `openapi-spec-validator` as OpenAPI 3.1.0.
2. **Live conformance** — responses from the running server were validated
   against the documented schemas, and every documented status code was
   provoked and observed:

   | Check | Result |
   |---|---|
   | `GET /health` → `HealthStatus` | conforms |
   | `GET /v1/gpu` → `GPUStatus` | conforms |
   | `GET /v1/jobs` → `JobList` | conforms |
   | No credential | `401` |
   | Invalid credential | `401` |
   | `read` scope on `POST /v1/videos` | `403` |
   | Unknown job | `404` |
   | Unknown job video | `404` |

## Contract summary

Auth is `Authorization: Bearer <client_id>:<secret>`.

| Method | Path | Scope |
|---|---|---|
| GET | `/health` | none (public) |
| GET | `/v1/gpu` | `read` |
| POST | `/v1/videos` | `generate` |
| GET | `/v1/jobs` | `read` |
| GET | `/v1/jobs/{job_id}` | `read` |
| GET | `/v1/jobs/{job_id}/video` | `read` |
| POST | `/v1/jobs/{job_id}/cancel` | `generate` |

Notes that are easy to get wrong:

- `POST /v1/videos` returns **202**, not 200. Generation is asynchronous.
- `width` and `height` must be **multiples of 32**.
- `VideoRequest` sets `additionalProperties: false` — unknown fields are
  rejected with `422`, not ignored.
- A job owned by another client returns **404**, identical to one that does not
  exist. This is intentional; do not treat 404 as proof of non-existence.
- Cancellation is cooperative: the response is `cancelling`, not `cancelled`.
- `video_url` is a **relative** path. Join it against your base URL.

## Regenerating

On the API host:

```bash
cd <api-server>
.venv/Scripts/python.exe tools/export_openapi.py -o openapi.json
```

The script is import-only and does not alter the running service or its exposed
routes.

## Maintenance

Schema and SDK version together. When the API changes:

1. regenerate `openapi.json`
2. re-run live conformance before committing
3. snapshot as `openapi-<sdk-version>.json` on release

`info.version` is the **API** version (currently `1.0.0`, serving the `/v1`
namespace); `info.x-sdk-version` is the SDK version the snapshot ships with.

The two are tracked separately and may diverge in future — an API change does
not force an SDK release, and vice versa. They happen to agree today.
