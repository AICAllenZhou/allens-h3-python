# Changelog

All notable changes to Allen's MiniMax H3 Python SDK.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-09-03

First release.

### Added

- `H3Client` — synchronous client.
- `AsyncH3Client` — asynchronous client with an identical surface.
- `generate()` — one call that submits, polls and returns a finished video, so
  callers never write polling logic.
- Granular methods: `health()`, `gpu()`, `create_video()`, `get_job()`,
  `list_jobs()`, `wait()`, `cancel()`, `download()`, `content()`.
- Typed models: `Job`, `VideoResult`, `GPUStatus`, `HealthStatus`, `JobStatus`.
- Typed exception hierarchy mapping every server status onto a specific error.
- `allens-h3` command line interface.
- Configuration from `ALLENS_H3_API_KEY` / `ALLENS_H3_BASE_URL`, with explicit
  constructor arguments taking precedence. The endpoint is never hard-coded.
- Bounded exponential backoff for transient network failures and 502/503/504.
- `Retry-After` is honoured on 429.

### Security

- TLS certificate verification is always on, with no opt-out.
- Credentials are never written to disk or to any log.
- Exception messages are scrubbed of credential-shaped strings.
- `base_url` validation rejects embedded credentials, query strings and
  plain `http://` to remote hosts.
- Generation requests are never retried automatically, so a network hiccup
  cannot silently produce two videos on a single-GPU server.
- The CLI refuses to take a key as a command-line flag.
