# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions match
the `APP_VERSION` reported by `GET /version`.

## [1.2.0] - 2026-07-03

### Added
- Grafana dashboards, auto-provisioned on startup (`grafana/provisioning/dashboards/`):
  golden signals (traffic, latency, error rate) and HTTP error segmentation
  (errors by endpoint/status code).
- `scripts/simulate_traffic.py` — continuous low-volume traffic generator for
  local demo/dashboard purposes.
- `scripts/stress_test.py` — one-off burst test: concurrent-identical-URL race,
  malformed/edge-case requests (422/405/404), sustained high-concurrency load.
- `scripts/concurrent_users_test.py` — simulates many independent users with
  staggered arrivals and human-like think-time (vs. a synchronized flood),
  including shared "viral" links to catch concurrent-write races.
- Unique index on `urls.target_url` (migration `0002_unique_target_url`).

### Fixed
- **Crash on malformed short codes**: `GET /<code>` with non-printable
  characters (e.g. a NUL byte) raised an unhandled `ValueError` from the DB
  driver and returned a bare 500. Now rejected before reaching the DB layer,
  returns a normal 404.
- **Lost hit-count updates under concurrency**: `increment_hits` did a
  read-modify-write in Python (fetch, `+= 1`, commit), which could drop
  increments when multiple requests hit the same short link at once. Replaced
  with a single atomic `UPDATE ... SET hit_count = hit_count + 1`.
- **Duplicate rows on concurrent `/shorten`**: the dedup check
  (`get_by_target` then insert) was a check-then-act race — concurrent
  requests for the same URL could each pass the check and insert their own
  row. Replaced with an atomic `INSERT ... ON CONFLICT DO NOTHING`, backed by
  the new unique index on `target_url`.
- **Blind spots in HTTP metrics**: validation errors (422), method-not-allowed
  (405), and unhandled exceptions (500) never incremented
  `http_requests_total`/`http_errors_total`, because metrics were recorded
  manually inside each endpoint's happy path. Centralized into a single
  `metrics_middleware` that records every response uniformly, including ones
  that never reach an endpoint body.
- **Prometheus metrics fragmented across gunicorn workers**: with `-w 4`
  workers and `prometheus_client`'s default in-memory registry, each worker
  had an isolated set of counters — a given `/metrics` scrape only reflected
  whichever single worker answered it. Enabled `prometheus_client`
  multiprocess mode (`PROMETHEUS_MULTIPROC_DIR`, `MultiProcessCollector`,
  `child_exit` hook in `gunicorn.conf.py`) so `/metrics` aggregates all workers.

### Changed
- `APP_VERSION` bumped to `1.2.0`.

## [1.1] - 2026-06-22
Observability and deployment stack: PostgreSQL persistence, Prometheus
metrics, Grafana, Loki, Jaeger, and OpenTelemetry tracing; Dockerized
deployment with a rolling-update script.
(`a299787`, `0bc6d6a`, `df48009`)

## [1.0] - 2026-06-16
Deduplication (same URL returns the same short code), hit-count tracking,
and structured logging on top of the initial FastAPI scaffold.
(`1b1023e`, `b05da73`)
