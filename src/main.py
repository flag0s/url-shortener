import hashlib
import os
import time

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from src.logger import logger
from src.models import URLRecord

load_dotenv()

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

app = FastAPI(title="URL Shortener")

db: dict[str, URLRecord] = {}
url_index: dict[str, str] = {}  # target_url -> code


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

@app.post("/shorten", response_model=ShortenResponse)
def shorten_url(body: ShortenRequest):
    if body.url in url_index:
        code = url_index[body.url]
        record = db[code]
        logger.info("DEDUPLICATE url=%s code=%s", body.url, code)
        return ShortenResponse(
            short_code=code,
            short_url=f"{BASE_URL}/{code}",
            created_at=record.created_at.isoformat(),
        )

    code = _generate_code(body.url)
    record = URLRecord(code=code, target_url=body.url)
    db[code] = record
    url_index[body.url] = code

    logger.info("SHORTEN url=%s code=%s", body.url, code)
    return ShortenResponse(
        short_code=code,
        short_url=f"{BASE_URL}/{code}",
        created_at=record.created_at.isoformat(),
    )


@app.get("/stats/{code}", response_model=StatsResponse)
def get_stats(code: str):
    record = db.get(code)
    if not record:
        logger.warning("STATS_NOT_FOUND code=%s", code)
        raise HTTPException(status_code=404, detail="Short URL not found")

    logger.info("STATS code=%s hit_count=%d", code, record.hit_count)
    return StatsResponse(
        short_code=code,
        target_url=record.target_url,
        created_at=record.created_at.isoformat(),
        hit_count=record.hit_count,
    )


@app.get("/{code}")
def redirect(code: str):
    record = db.get(code)
    if not record:
        logger.warning("REDIRECT_NOT_FOUND code=%s", code)
        raise HTTPException(status_code=404, detail="Short URL not found")

    record.hit_count += 1
    logger.info("REDIRECT code=%s -> %s (hit #%d)", code, record.target_url, record.hit_count)
    return RedirectResponse(url=record.target_url)
