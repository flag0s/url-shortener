import hashlib
import os
import time

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel

from src import database as db_ops
from src.logger import logger

load_dotenv()

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

app = FastAPI(title="URL Shortener")

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


# ---------- Endpoints ----------

@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/shorten", response_model=ShortenResponse)
def shorten_url(body: ShortenRequest):
    start = time.time()
    endpoint = "/shorten"

    existing = db_ops.get_by_target(body.url)
    if existing:
        logger.info("DEDUPLICATE url=%s code=%s", body.url, existing.code)
        REQUEST_COUNT.labels(method="POST", endpoint=endpoint, status_code=200).inc()
        REQUEST_DURATION.labels(endpoint=endpoint).observe(time.time() - start)
        return ShortenResponse(
            short_code=existing.code,
            short_url=f"{BASE_URL}/{existing.code}",
            created_at=existing.created_at.isoformat(),
        )

    code = _generate_code(body.url)
    record = db_ops.create_url(code=code, target_url=body.url)

    logger.info("SHORTEN url=%s code=%s", body.url, code)
    REQUEST_COUNT.labels(method="POST", endpoint=endpoint, status_code=200).inc()
    REQUEST_DURATION.labels(endpoint=endpoint).observe(time.time() - start)
    return ShortenResponse(
        short_code=record.code,
        short_url=f"{BASE_URL}/{record.code}",
        created_at=record.created_at.isoformat(),
    )


@app.get("/stats/{code}", response_model=StatsResponse)
def get_stats(code: str):
    start = time.time()
    endpoint = "/stats/{code}"

    record = db_ops.get_by_code(code)
    if not record:
        logger.warning("STATS_NOT_FOUND code=%s", code)
        ERROR_COUNT.labels(endpoint=endpoint, status_code=404).inc()
        REQUEST_COUNT.labels(method="GET", endpoint=endpoint, status_code=404).inc()
        REQUEST_DURATION.labels(endpoint=endpoint).observe(time.time() - start)
        raise HTTPException(status_code=404, detail="Short URL not found")

    logger.info("STATS code=%s hit_count=%d", code, record.hit_count)
    REQUEST_COUNT.labels(method="GET", endpoint=endpoint, status_code=200).inc()
    REQUEST_DURATION.labels(endpoint=endpoint).observe(time.time() - start)
    return StatsResponse(
        short_code=code,
        target_url=record.target_url,
        created_at=record.created_at.isoformat(),
        hit_count=record.hit_count,
    )


@app.get("/{code}")
def redirect(code: str):
    start = time.time()
    endpoint = "/{code}"

    record = db_ops.increment_hits(code)
    if not record:
        logger.warning("REDIRECT_NOT_FOUND code=%s", code)
        ERROR_COUNT.labels(endpoint=endpoint, status_code=404).inc()
        REQUEST_COUNT.labels(method="GET", endpoint=endpoint, status_code=404).inc()
        REQUEST_DURATION.labels(endpoint=endpoint).observe(time.time() - start)
        raise HTTPException(status_code=404, detail="Short URL not found")

    logger.info("REDIRECT code=%s -> %s (hit #%d)", code, record.target_url, record.hit_count)
    REQUEST_COUNT.labels(method="GET", endpoint=endpoint, status_code=307).inc()
    REQUEST_DURATION.labels(endpoint=endpoint).observe(time.time() - start)
    return RedirectResponse(url=record.target_url)
