# Allen's MiniMax H3 Python SDK

[![PyPI](https://img.shields.io/pypi/v/allens-h3.svg)](https://pypi.org/project/allens-h3/)
[![Python](https://img.shields.io/pypi/pyversions/allens-h3.svg)](https://pypi.org/project/allens-h3/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Text-to-video with synchronised audio, generated on a private RTX 3090.

You do not need to know anything about HTTP endpoints, job polling, ComfyUI or
workflow graphs — submit a prompt, get an MP4.

> **This SDK is open source; the API behind it is not public.**
> Every request needs a credential. If you do not already have an endpoint URL
> and an API key, this package will install fine but has nothing to talk to.

```python
from allens_h3 import H3Client

client = H3Client()
video = client.generate(prompt="A cinematic AI business school commercial",
                        duration=5)
video.download("video.mp4")
```

---

## Install

```bash
pip install allens-h3
```

From source:

```bash
git clone https://github.com/AICAllenZhou/allens-h3-python.git
cd allens-h3-python
pip install -e ".[dev]"
```

Requires Python 3.9+. The only runtime dependency is `httpx`.

---

## Configure

Two values are needed. Neither is ever hard-coded in the SDK, because the
endpoint hostname can change.

| Variable | Meaning |
|---|---|
| `ALLENS_H3_BASE_URL` | HTTPS endpoint, e.g. `https://xxxx.trycloudflare.com` |
| `ALLENS_H3_API_KEY` | your credential |

```bash
# macOS / Linux
export ALLENS_H3_BASE_URL="https://xxxx.trycloudflare.com"
export ALLENS_H3_API_KEY="..."
```

```powershell
# Windows PowerShell
$env:ALLENS_H3_BASE_URL = "https://xxxx.trycloudflare.com"
$env:ALLENS_H3_API_KEY  = "..."
```

Or pass them explicitly:

```python
client = H3Client(api_key="...", base_url="https://xxxx.trycloudflare.com")
```

Explicit arguments win; otherwise the environment is used.

> The endpoint currently runs through a Cloudflare Quick Tunnel, whose
> hostname **changes whenever the tunnel restarts**. Ask for the current URL,
> or update `ALLENS_H3_BASE_URL` when it moves.

---

## Generate

```python
video = client.generate(
    prompt="A cinematic nighttime shot of downtown Vancouver after rain",
    width=608,        # multiple of 32
    height=352,       # multiple of 32
    duration=5,       # 1-10 seconds
    steps=20,         # 4-40
    seed=None,        # omit for the server default
    timeout=1800,
)

print(video.job_id)
video.download("output.mp4")
data = video.content()      # or get the bytes directly
```

`generate()` submits the job, polls until it finishes, and returns the result.
A 5-second clip takes roughly 4-5 minutes.

With a progress callback:

```python
video = client.generate(
    prompt="...",
    on_progress=lambda job: print(f"{job.status} {job.percent}%"),
)
```

---

## Job control

For long jobs you may not want to block:

```python
job = client.create_video(prompt="...", duration=5)
print(job.id, job.status)          # queued

job = client.get_job(job.id)       # poll whenever you like
print(job.status, job.percent)

job = client.wait(job.id)          # block until terminal
client.download(job.id, "out.mp4")
```

Cancel a queued or running job:

```python
client.cancel(job.id)
```

List your recent jobs (only ever your own):

```python
for job in client.list_jobs(limit=10):
    print(job.id, job.status)
```

---

## Service and GPU status

```python
health = client.health()
print(health.is_ok, health.comfyui, health.worker)

gpu = client.gpu()
print(gpu.name, gpu.temperature_c, gpu.hotspot_c, gpu.power_w, gpu.is_busy)
```

---

## Async

```python
import asyncio
from allens_h3 import AsyncH3Client

async def main():
    async with AsyncH3Client() as client:
        video = await client.generate(prompt="A cinematic commercial",
                                      duration=5)
        await video.download("output.mp4")

asyncio.run(main())
```

The async API mirrors the sync one method for method.

---

## Error handling

Every failure is a typed exception, so you never inspect a status code:

```python
from allens_h3 import (
    H3Error, H3AuthenticationError, H3RateLimitError,
    H3ValidationError, H3GPUUnavailableError, H3JobFailedError,
    H3TimeoutError,
)

try:
    video = client.generate(prompt="...")
except H3AuthenticationError:
    print("bad or revoked key")
except H3RateLimitError as e:
    print(f"slow down; retry after {e.retry_after}s")
except H3ValidationError as e:
    print(f"bad parameters: {e}")
except H3GPUUnavailableError:
    print("GPU busy or too hot; try later")
except H3JobFailedError as e:
    print(f"job {e.job_id} ended as {e.job_status}")
except H3TimeoutError:
    print("still running — poll get_job() to keep checking")
except H3Error as e:
    print(f"unexpected: {e}")
```

| Exception | HTTP |
|---|---|
| `H3ValidationError` | 400, 413, 422 |
| `H3AuthenticationError` | 401 |
| `H3PermissionError` | 403 |
| `H3NotFoundError` | 404 |
| `H3ConflictError` | 409 |
| `H3RateLimitError` | 429 |
| `H3GPUUnavailableError` | 502, 503, 504 |

---

## Command line

For colleagues who do not write Python:

```bash
allens-h3 health
allens-h3 gpu

allens-h3 generate \
  --prompt "A cinematic BBA AI commercial" \
  --duration 5 \
  --output output.mp4

allens-h3 jobs
allens-h3 status h3_abc123
allens-h3 cancel h3_abc123
allens-h3 download h3_abc123 -o video.mp4
```

The CLI reads credentials from the environment only — passing a key as a flag
would leave it in your shell history.

---

## Limits

Server-enforced, per credential:

| Limit | Default |
|---|---|
| API requests | 20 / minute |
| Generations | 12 / hour |
| Queued jobs | 3 |
| Prompt length | 2000 characters |
| Resolution | 256-1280 × 256-720, multiples of 32 |
| Duration | 1-10 seconds |
| Steps | 4-40 |

Only one job runs on the GPU at a time; the rest queue.

---

## Security

- TLS verification is always on and **cannot** be disabled.
- The API key travels in the `Authorization` header, never in a URL.
- The key is never written to disk or to any log by this SDK.
- Exception messages are scrubbed of anything credential-shaped.
- `base_url` is validated; embedded credentials are rejected.
- Plain `http://` to a remote host is refused.
- Failed reads and 502/503/504 are retried with exponential backoff;
  generation requests are **never** retried automatically, to avoid
  producing a duplicate video.

---

## Version

1.0.0 — see [CHANGELOG.md](CHANGELOG.md).

## Development

```bash
git clone https://github.com/AICAllenZhou/allens-h3-python.git
cd allens-h3-python
pip install -e ".[dev]"

pytest -m "not integration"      # 76 unit tests, fully mocked
```

Integration tests hit the real API and consume GPU time, so they are
deselected by default:

```bash
export ALLENS_H3_BASE_URL="..."
export ALLENS_H3_API_KEY="..."
pytest -m integration -s
```

## Security

TLS verification is always on, credentials never reach a log or a URL, and
generation requests are never retried automatically. See
[SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE).
