import hashlib
import os
import time

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)
from pydantic import BaseModel

from src import database as db_ops
from src.logger import logger
from src.tracing import setup_tracing

load_dotenv()

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
APP_VERSION = os.getenv("APP_VERSION", "1.0")

setup_tracing()

app = FastAPI(title="URL Shortener")
FastAPIInstrumentor.instrument_app(app)

tracer = trace.get_tracer("url-shortener")

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["endpoint"],
)
ERROR_COUNT = Counter(
    "http_errors_total",
    "Total HTTP errors",
    ["endpoint", "status_code"],
)


# ---------- Metrics middleware ----------
# Records every request/response uniformly (2xx/3xx/4xx from validation or
# routing, and 5xx from unhandled exceptions), instead of each endpoint
# recording its own happy-path metrics. This is what lets errors that never
# reach an endpoint body (422 validation, 405 method not allowed, an
# unhandled exception) still show up in http_requests_total/http_errors_total.

def _endpoint_label(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or request.url.path


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)

    start = time.time()
    try:
        response = await call_next(request)
    except Exception:
        duration = time.time() - start
        endpoint = _endpoint_label(request)
        logger.exception("UNHANDLED_EXCEPTION method=%s path=%s", request.method, request.url.path)
        REQUEST_COUNT.labels(method=request.method, endpoint=endpoint, status_code=500).inc()
        ERROR_COUNT.labels(endpoint=endpoint, status_code=500).inc()
        REQUEST_DURATION.labels(endpoint=endpoint).observe(duration)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    duration = time.time() - start
    endpoint = _endpoint_label(request)
    REQUEST_COUNT.labels(method=request.method, endpoint=endpoint, status_code=response.status_code).inc()
    REQUEST_DURATION.labels(endpoint=endpoint).observe(duration)
    if response.status_code >= 400:
        ERROR_COUNT.labels(endpoint=endpoint, status_code=response.status_code).inc()
    return response


# ---------- Schemas ----------

class ShortenRequest(BaseModel):
    url: str


class ShortenResponse(BaseModel):
    short_code: str
    short_url: str
    created_at: str


class StatsResponse(BaseModel):
    short_code: str
    target_url: str
    created_at: str
    hit_count: int


# ---------- Helpers ----------

def _generate_code(url: str) -> str:
    seed = f"{url}{time.time()}"
    return hashlib.md5(seed.encode()).hexdigest()[:7]


def _is_safe_code(code: str) -> bool:
    """Rejects codes with NUL bytes or other control characters before they
    reach the DB layer, where they'd otherwise raise an unhandled
    ValueError from the DB driver (e.g. GET /%00)."""
    return code.isprintable()


# ---------- Endpoints ----------

@app.get("/version")
def version():
    return {"version": APP_VERSION}


@app.get("/metrics")
def metrics():
    if "PROMETHEUS_MULTIPROC_DIR" in os.environ:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        data = generate_latest(registry)
    else:
        data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.post("/shorten", response_model=ShortenResponse)
def shorten_url(body: ShortenRequest):
    span = trace.get_current_span()
    span.set_attribute("url.target", body.url)

    code = _generate_code(body.url)
    record, created = db_ops.get_or_create_url(code=code, target_url=body.url)

    span.set_attribute("url.code", record.code)
    span.set_attribute("url.deduplicated", not created)
    if created:
        logger.info("SHORTEN url=%s code=%s", body.url, record.code)
    else:
        logger.info("DEDUPLICATE url=%s code=%s", body.url, record.code)
    return ShortenResponse(
        short_code=record.code,
        short_url=f"{BASE_URL}/{record.code}",
        created_at=record.created_at.isoformat(),
    )


@app.get("/stats/{code}", response_model=StatsResponse)
def get_stats(code: str):
    span = trace.get_current_span()
    span.set_attribute("url.code", code)

    record = db_ops.get_by_code(code) if _is_safe_code(code) else None
    if not record:
        span.set_attribute("url.found", False)
        logger.warning("STATS_NOT_FOUND code=%s", code)
        raise HTTPException(status_code=404, detail="Short URL not found")

    span.set_attribute("url.found", True)
    span.set_attribute("url.hit_count", record.hit_count)
    logger.info("STATS code=%s hit_count=%d", code, record.hit_count)
    return StatsResponse(
        short_code=code,
        target_url=record.target_url,
        created_at=record.created_at.isoformat(),
        hit_count=record.hit_count,
    )


@app.get("/{code}")
def redirect(code: str):
    span = trace.get_current_span()
    span.set_attribute("url.code", code)

    record = db_ops.increment_hits(code) if _is_safe_code(code) else None
    if not record:
        span.set_attribute("url.found", False)
        logger.warning("REDIRECT_NOT_FOUND code=%s", code)
        raise HTTPException(status_code=404, detail="Short URL not found")

    span.set_attribute("url.found", True)
    span.set_attribute("url.target", record.target_url)
    span.set_attribute("url.hit_count", record.hit_count)
    logger.info("REDIRECT code=%s -> %s (hit #%d)", code, record.target_url, record.hit_count)
    return RedirectResponse(url=record.target_url)
