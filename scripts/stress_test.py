#!/usr/bin/env python3
"""One-off stress/chaos burst against the local url-shortener app, meant to
spike the Grafana golden-signals & error-segmentation dashboards with
something more interesting than steady-state traffic. Not for use against
anything but your own local stack.

Phases:
  1. Race burst   - many concurrent /shorten calls with the SAME url, to see
                     whether the dedup check-then-insert holds under concurrency.
  2. Malformed burst - 422 (validation), 405 (method not allowed) requests.
     These never touch the app's custom Prometheus counters (they're
     rejected by FastAPI/Starlette before reaching the endpoint code), so
     they'll show up in Jaeger/logs but NOT in http_requests_total.
  3. Load burst   - sustained high concurrency against /shorten, /{code},
                     /stats/{code} (mixed valid + 404) for --duration seconds.

Ctrl+C aborts cleanly at any point.
"""

import argparse
import asyncio
import collections
import os
import random
import time
import uuid

import httpx

SAMPLE_URLS = [
    "https://example.com/",
    "https://www.wikipedia.org/",
    "https://github.com/",
    "https://news.ycombinator.com/",
    "https://httpbin.org/get",
]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://localhost:8000"))
    parser.add_argument("--race-concurrency", type=int, default=25)
    parser.add_argument("--malformed-count", type=int, default=40)
    parser.add_argument("--load-concurrency", type=int, default=50)
    parser.add_argument("--duration", type=float, default=30.0, help="seconds for the load burst")
    return parser.parse_args()


def random_target_url() -> str:
    base = random.choice(SAMPLE_URLS)
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}v={uuid.uuid4().hex[:8]}"


async def race_burst(client: httpx.AsyncClient, n: int) -> None:
    print(f"\n=== Phase 1: race burst ({n} concurrent /shorten on the SAME url) ===")
    shared_url = f"https://example.com/race?v={uuid.uuid4().hex[:8]}"

    async def one():
        r = await client.post("/shorten", json={"url": shared_url})
        return r.status_code, (r.json().get("short_code") if r.is_success else None)

    results = await asyncio.gather(*(one() for _ in range(n)), return_exceptions=True)
    codes = set()
    statuses = collections.Counter()
    for res in results:
        if isinstance(res, Exception):
            statuses["exception"] += 1
            continue
        status, code = res
        statuses[status] += 1
        if code:
            codes.add(code)
    print(f"[race] status codes: {dict(statuses)}")
    if len(codes) <= 1:
        print(f"[race] dedup held: {len(codes)} distinct code for {n} concurrent identical requests -> {codes}")
    else:
        print(f"[race] dedup RACE CONDITION: {len(codes)} distinct codes for the same url under concurrency -> {codes}")


async def malformed_burst(client: httpx.AsyncClient, n: int) -> None:
    print(f"\n=== Phase 2: malformed/edge-case burst ({n} requests) ===")

    async def missing_field():
        r = await client.post("/shorten", json={})
        return "missing_field", r.status_code

    async def wrong_type():
        r = await client.post("/shorten", json={"url": 12345})
        return "wrong_type", r.status_code

    async def null_url():
        r = await client.post("/shorten", json={"url": None})
        return "null_url", r.status_code

    async def bad_json():
        r = await client.post(
            "/shorten", content=b"{not valid json", headers={"Content-Type": "application/json"}
        )
        return "bad_json", r.status_code

    async def method_not_allowed():
        r = await client.delete("/shorten")
        return "method_not_allowed", r.status_code

    async def huge_url():
        r = await client.post("/shorten", json={"url": "https://example.com/" + "x" * 50_000})
        return "huge_url", r.status_code

    async def weird_code_lookup():
        weird = random.choice(["../../etc/passwd", "%00", "a" * 500, "código-ñ"])
        r = await client.get(f"/{weird}", follow_redirects=False)
        return "weird_code_lookup", r.status_code

    variants = [missing_field, wrong_type, null_url, bad_json, method_not_allowed, huge_url, weird_code_lookup]
    tasks = [random.choice(variants)() for _ in range(n)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    by_kind = collections.defaultdict(collections.Counter)
    for res in results:
        if isinstance(res, Exception):
            print(f"[malformed] exception: {res!r}")
            continue
        kind, status = res
        by_kind[kind][status] += 1
    for kind, statuses in by_kind.items():
        print(f"[malformed] {kind}: {dict(statuses)}")


async def load_burst(client: httpx.AsyncClient, concurrency: int, duration: float) -> None:
    print(f"\n=== Phase 3: load burst ({concurrency} concurrent workers, {duration:.0f}s) ===")
    known_codes: list[str] = []
    stats = collections.Counter()
    stop_at = time.monotonic() + duration

    async def do_shorten():
        url = random_target_url()
        r = await client.post("/shorten", json={"url": url})
        if r.is_success:
            known_codes.append(r.json()["short_code"])
            del known_codes[:-500]
        return r.status_code

    async def do_redirect():
        if not known_codes:
            return await do_shorten()
        code = random.choice(known_codes)
        r = await client.get(f"/{code}", follow_redirects=False)
        return r.status_code

    async def do_stats():
        if not known_codes:
            return await do_shorten()
        code = random.choice(known_codes)
        r = await client.get(f"/stats/{code}")
        return r.status_code

    async def do_404():
        r = await client.get(f"/{uuid.uuid4().hex[:7]}", follow_redirects=False)
        return r.status_code

    actions = [do_shorten, do_redirect, do_redirect, do_stats, do_404]

    async def worker():
        while time.monotonic() < stop_at:
            action = random.choice(actions)
            try:
                status = await action()
                stats[status] += 1
            except httpx.HTTPError as exc:
                stats[f"error:{exc.__class__.__name__}"] += 1

    start = time.monotonic()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    elapsed = time.monotonic() - start
    total = sum(v for k, v in stats.items() if isinstance(k, int))
    print(f"[load] {total} requests in {elapsed:.1f}s (~{total / elapsed:.1f} req/s)")
    print(f"[load] status breakdown: {dict(stats)}")


async def main():
    args = parse_args()
    async with httpx.AsyncClient(base_url=args.base_url, timeout=15.0) as client:
        try:
            r = await client.get("/version")
            r.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"[error] app not reachable at {args.base_url}: {exc}")
            return

        t0 = time.monotonic()
        try:
            await race_burst(client, args.race_concurrency)
            await malformed_burst(client, args.malformed_count)
            await load_burst(client, args.load_concurrency, args.duration)
        except KeyboardInterrupt:
            print("\n[stop] interrupted by user.")
        print(f"\n=== Done in {time.monotonic() - t0:.1f}s. Check Grafana for the spike. ===")


if __name__ == "__main__":
    asyncio.run(main())
