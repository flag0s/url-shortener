# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Local dev (app only, no observability stack):**
```bash
python -m venv .venv && .venv\Scripts\activate   # Windows; source .venv/bin/activate elsewhere
pip install -r requirements.txt
uvicorn src.main:app --reload
```

**Full stack (app + Postgres + Prometheus + Grafana + Loki + Jaeger):**
```bash
docker-compose up -d --build
```
App: `:8000` · Grafana: `:3000` (admin/admin) · Prometheus: `:9090` · Jaeger UI: `:16686` · Loki: `:3100`.
Grafana dashboards (golden signals, HTTP error segmentation) auto-provision from
`grafana/provisioning/dashboards/` — no manual setup needed.

**Tests** (require a reachable Postgres — either `docker-compose up -d postgres` or local Postgres matching `DATABASE_URL` in `.env`):
```bash
pytest tests/                          # full suite
pytest tests/test_shortener.py::test_shorten_returns_short_code   # single test
```

**Migrations:**
```bash
alembic upgrade head        # apply
alembic revision -m "..."   # new migration (write upgrade/downgrade manually; see alembic/versions/)
```
The `app` container runs `alembic upgrade head` automatically on startup (`entrypoint.sh`).

**Rolling update / redeploy just the app container** (rebuilds image, replaces container, waits for healthcheck):
```bash
./scripts/rolling_update.sh
APP_VERSION=1.3.0 ./scripts/rolling_update.sh   # deploy under a specific version
```

**Traffic/load tools** (`scripts/`, require the app reachable at `--base-url`, default `http://localhost:8000`):
- `simulate_traffic.py` — continuous low-volume traffic for keeping dashboards populated during local dev. Retries until the app is up, so it's safe to start alongside `docker-compose up`.
- `stress_test.py` — one-off burst: concurrent-identical-URL dedup race, malformed/edge-case requests (422/405/404), then a sustained high-concurrency load phase. Prints a summary at the end.
- `concurrent_users_test.py` — simulates many independent users with staggered arrivals and think-time (not a synchronized flood). Seeds shared "viral" links and reports whether their `hit_count` matches expected, to catch concurrent-write regressions. Key flags: `--users`, `--initial-parallel` (how many start at once), `--arrival-interval` (seconds between subsequent arrivals), `--duration` (seconds each user stays active once it arrives).

## Git workflow

`main` is release-only — nothing is committed or pushed to it directly. Flow:

1. Branch off `develop` for any change: `git checkout -b <type>/<short-description> develop` (e.g. `fix/…`, `feat/…`, `docs/…`, `ci/…`).
2. Open a PR back into `develop` (`gh pr create --base develop`). This is where day-to-day work lands; CI (`.github/workflows/tests.yml`) runs on it automatically.
3. When `develop` has a coherent, tested set of changes ready to ship, open a `develop` → `main` PR. This is the release gate — it requires explicit human approval before merging, even if the individual `develop`-bound PRs were already reviewed.

## Architecture

**Single-file FastAPI app** (`src/main.py`) backed by Postgres via SQLAlchemy (`src/database.py`, `src/models.py`), fronted in production by gunicorn with 4 Uvicorn workers (`entrypoint.sh`).

**Metrics are centralized in one HTTP middleware, not per-endpoint.** `metrics_middleware` in `main.py` wraps every request/response — including validation errors (422), method-not-allowed (405), and unhandled exceptions (500) — and is the *only* place that increments `REQUEST_COUNT`/`REQUEST_DURATION`/`ERROR_COUNT`. Endpoint functions must not record these themselves (it would double-count); they only set OpenTelemetry span attributes and log. The endpoint label used is the matched route template (`request.scope["route"].path`, e.g. `/{code}`), not the raw path, to keep Prometheus label cardinality bounded — falls back to the raw path only when no route matched at all (e.g. a path that doesn't fit any pattern).

**Prometheus multiprocess mode is required and already wired up.** Because gunicorn runs 4 worker processes, `prometheus_client`'s default in-memory registry would make `/metrics` reflect only whichever single worker answered that scrape. `entrypoint.sh` sets `PROMETHEUS_MULTIPROC_DIR` and clears it on startup; `gunicorn.conf.py` has a `child_exit` hook to clean up dead workers' metric files; `/metrics` in `main.py` uses `MultiProcessCollector` when that env var is present. Any new `Counter`/`Histogram`/`Gauge` added to the app is automatically covered by this — no per-metric wiring needed. This only matters under gunicorn; local `uvicorn --reload` (single process) uses the plain in-memory registry.

**DB writes that can race are done as single atomic SQL statements, not read-modify-write in Python** — this was the source of two real concurrency bugs (lost hit-count updates, duplicate rows on concurrent `/shorten` for the same URL), found via `concurrent_users_test.py` and fixed by relying on Postgres rather than app-level locking:
- `increment_hits` (`database.py`) is a single `UPDATE ... SET hit_count = hit_count + 1 WHERE code = ...`.
- `get_or_create_url` (`database.py`) is a single `INSERT ... ON CONFLICT (target_url) DO NOTHING RETURNING ...`, backed by the unique index on `urls.target_url` added in migration `0002_unique_target_url`. If that unique index is ever removed, dedup silently degrades back into a check-then-insert race.
- Follow this pattern (atomic statement + DB constraint) for any new stateful/concurrent-write logic instead of fetch-mutate-save.

**Short codes** are `md5(url + time.time())[:7]` (`_generate_code` in `main.py`) — collisions are astronomically unlikely (7 hex chars) and are not explicitly handled beyond the generic exception path (an `IntegrityError` on the `code` unique constraint would surface as a logged 500, not silently swallowed).

**`GET /{code}` and `GET /stats/{code}` reject non-printable codes (`_is_safe_code`, `str.isprintable()`) before hitting the DB.** This exists specifically because a NUL byte in the path (e.g. `GET /%00`) used to crash the DB driver with an unhandled `ValueError`, bypassing all metrics/logging. Anything else — wrong length, wrong charset, path-traversal-looking strings — is allowed through and just 404s from the normal not-found path, matching existing test expectations (`test_redirect_unknown_code_returns_404` uses an arbitrary non-hex string).

**Observability stack** (`docker-compose.yml`, `prometheus.yml`, `grafana/provisioning/`): Prometheus scrapes the app's own `/metrics` (self-instrumented via `prometheus-client`, not an exporter) at `host.docker.internal:8000` — note this is *not* the `app:8000` compose DNS name, it's `host.docker.internal` with `extra_hosts: host.docker.internal:host-gateway` on the `prometheus` service, so keep that in mind if the network topology changes. Tracing goes through OpenTelemetry (`src/tracing.py`) → OTLP HTTP → Jaeger. Loki and its datasource are provisioned but nothing currently ships logs to it (the app logs to stdout + a local `app.log` file only, no Promtail/Docker logging driver configured).

**Versioning**: `APP_VERSION` (env var, surfaced at `GET /version`) is tracked in `CHANGELOG.md` (Keep a Changelog format) — bump both together when making a release-worthy change.
