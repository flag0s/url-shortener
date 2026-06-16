import pytest
from fastapi.testclient import TestClient

from src.main import app, db, url_index


@pytest.fixture(autouse=True)
def clear_db():
    db.clear()
    url_index.clear()
    yield
    db.clear()
    url_index.clear()


client = TestClient(app)


def shorten(url: str):
    return client.post("/shorten", json={"url": url})


# ---------- POST /shorten ----------

def test_shorten_returns_short_code():
    r = shorten("https://example.com")
    assert r.status_code == 200
    body = r.json()
    assert "short_code" in body
    assert "short_url" in body
    assert "created_at" in body


def test_deduplication_returns_same_code():
    r1 = shorten("https://example.com")
    r2 = shorten("https://example.com")
    assert r1.json()["short_code"] == r2.json()["short_code"]


def test_different_urls_get_different_codes():
    r1 = shorten("https://example.com")
    r2 = shorten("https://other.com")
    assert r1.json()["short_code"] != r2.json()["short_code"]


# ---------- GET /{code} ----------

def test_redirect_increments_hit_count():
    code = shorten("https://example.com").json()["short_code"]

    client.get(f"/{code}", follow_redirects=False)
    client.get(f"/{code}", follow_redirects=False)

    stats = client.get(f"/stats/{code}").json()
    assert stats["hit_count"] == 2


def test_redirect_unknown_code_returns_404():
    r = client.get("/doesnotexist", follow_redirects=False)
    assert r.status_code == 404


def test_redirect_follows_to_target():
    code = shorten("https://example.com").json()["short_code"]
    r = client.get(f"/{code}", follow_redirects=False)
    assert r.status_code in (301, 302, 307, 308)
    assert r.headers["location"] == "https://example.com"


# ---------- GET /stats/{code} ----------

def test_stats_returns_correct_fields():
    code = shorten("https://example.com").json()["short_code"]
    r = client.get(f"/stats/{code}")
    assert r.status_code == 200
    body = r.json()
    assert body["target_url"] == "https://example.com"
    assert body["hit_count"] == 0
    assert "created_at" in body


def test_stats_unknown_code_returns_404():
    r = client.get("/stats/doesnotexist")
    assert r.status_code == 404


def test_stats_hit_count_starts_at_zero():
    code = shorten("https://example.com").json()["short_code"]
    assert client.get(f"/stats/{code}").json()["hit_count"] == 0
