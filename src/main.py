from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
import hashlib
import time

app = FastAPI(title="URL Shortener")

db: dict[str, str] = {}


class ShortenRequest(BaseModel):
    url: str


class ShortenResponse(BaseModel):
    short_url: str
    original_url: str


def generate_short_code(url: str) -> str:
    seed = f"{url}{time.time()}"
    return hashlib.md5(seed.encode()).hexdigest()[:7]


@app.post("/shorten", response_model=ShortenResponse)
def shorten_url(body: ShortenRequest):
    code = generate_short_code(body.url)
    db[code] = body.url
    return ShortenResponse(short_url=f"http://localhost:8000/{code}", original_url=body.url)


@app.get("/{code}")
def redirect(code: str):
    url = db.get(code)
    if not url:
        raise HTTPException(status_code=404, detail="Short URL not found")
    return RedirectResponse(url=url)
