#!/usr/bin/env python3
"""Simulates many independent people using the app at the same time.

Unlike stress_test.py's load burst (uniform workers hammering with near-zero
delay), this staggers virtual users' start times and gives each one
human-like think-time between actions, so the concurrency comes from many
independent sessions overlapping rather than a synchronized flood.

Also seeds a handful of "viral" short links that a chunk of the simulated
users click on, to check whether concurrent hit_count increments
(read-modify-write in src/database.py:increment_hits) lose updates under
real concurrent access.

Ctrl+C aborts cleanly.
"""

import argparse
import asyncio
import collections
import os
import random
import time
import uuid

import httpx


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://localhost:8000"))
    parser.add_argument("--users", type=int, default=80, help="concurrent simulated users")
    parser.add_argument("--duration", type=float, default=45.0, help="seconds each user stays active")
    parser.add_argument("--popular-links", type=int, default=4, help="number of shared 'viral' short links")
    parser.add_argument("--popular-share", type=float, default=0.35, help="probability a user clicks a viral link instead of their own")
    parser.add_argument("--min-think", type=float, default=0.3, help="min seconds between a user's actions")
    parser.add_argument("--max-think", type=float, default=2.5, help="max seconds between a user's actions")
    parser.add_argument("--max-arrival-delay", type=float, default=5.0, help="users trickle in over this many seconds instead of starting at once (ignored if --arrival-interval > 0)")
    parser.add_argument("--initial-parallel", type=int, default=None, help="how many users start at once, in parallel (default: all of --users, i.e. plain jittered burst)")
    parser.add_argument("--arrival-interval", type=float, default=0.0, help="seconds between each subsequent user's arrival after the initial parallel batch (0 = disabled, falls back to --max-arrival-delay jitter)")
    return parser.parse_args()


def _arrival_delay(user_id: int, args) -> float:
    initial = args.initial_parallel if args.initial_parallel is not None else args.users
    if user_id < initial:
        return random.uniform(0, min(0.5, args.max_arrival_delay))
    if args.arrival_interval > 0:
        return (user_id - initial + 1) * args.arrival_interval
    return random.uniform(0, args.max_arrival_delay)


async def create_popular_codes(client: httpx.AsyncClient, n: int) -> list[str]:
    codes = []
    for _ in range(n):
        url = f"https://viral.example/{uuid.uuid4().hex[:8]}"
        r = await client.post("/shorten", json={"url": url})
        r.raise_for_status()
        codes.append(r.json()["short_code"])
    return codes


async def user_session(
    user_id: int,
    client: httpx.AsyncClient,
    popular_codes: list[str],
    popular_hits: collections.Counter,
    stats: collections.Counter,
    args,
) -> None:
    await asyncio.sleep(_arrival_delay(user_id, args))
    stop_at = time.monotonic() + args.duration

    own_codes: list[str] = []
    while time.monotonic() < stop_at:
        try:
            if popular_codes and random.random() < args.popular_share:
                code = random.choice(popular_codes)
                r = await client.get(f"/{code}", follow_redirects=False)
                stats[r.status_code] += 1
                if r.status_code == 307:
                    popular_hits[code] += 1
            else:
                roll = random.random()
                if roll < 0.3 or not own_codes:
                    url = f"https://user-{user_id}.example/?v={uuid.uuid4().hex[:6]}"
                    r = await client.post("/shorten", json={"url": url})
                    stats[r.status_code] += 1
                    if r.is_success:
                        own_codes.append(r.json()["short_code"])
                elif roll < 0.75:
                    code = random.choice(own_codes)
                    r = await client.get(f"/{code}", follow_redirects=False)
                    stats[r.status_code] += 1
                else:
                    code = random.choice(own_codes)
                    r = await client.get(f"/stats/{code}")
                    stats[r.status_code] += 1
        except httpx.HTTPError as exc:
            stats[f"error:{exc.__class__.__name__}"] += 1

        await asyncio.sleep(random.uniform(args.min_think, args.max_think))


async def main():
    args = parse_args()
    async with httpx.AsyncClient(base_url=args.base_url, timeout=15.0) as client:
        try:
            r = await client.get("/version")
            r.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"[error] app not reachable at {args.base_url}: {exc}")
            return

        print(f"Seeding {args.popular_links} viral short links...")
        popular_codes = await create_popular_codes(client, args.popular_links)
        print(f"Viral codes: {popular_codes}")

        popular_hits: collections.Counter = collections.Counter()
        stats: collections.Counter = collections.Counter()

        initial = args.initial_parallel if args.initial_parallel is not None else args.users
        if args.arrival_interval > 0:
            last_arrival = (args.users - initial) * args.arrival_interval if args.users > initial else 0
            arrival_desc = (
                f"first {initial} in parallel, then 1 every {args.arrival_interval:.0f}s "
                f"(last of {args.users} arrives at ~{last_arrival:.0f}s)"
            )
        else:
            arrival_desc = f"trickling in over {args.max_arrival_delay:.0f}s"
        print(
            f"\nLaunching {args.users} concurrent virtual users "
            f"({arrival_desc}, {args.min_think:.1f}-{args.max_think:.1f}s think-time each, "
            f"each active for {args.duration:.0f}s once it arrives)...\n"
        )
        start = time.monotonic()
        try:
            await asyncio.gather(
                *(
                    user_session(i, client, popular_codes, popular_hits, stats, args)
                    for i in range(args.users)
                )
            )
        except KeyboardInterrupt:
            print("\n[stop] interrupted by user.")
        elapsed = time.monotonic() - start

        total = sum(v for k, v in stats.items() if isinstance(k, int))
        print(f"=== {total} requests from {args.users} simulated users in {elapsed:.1f}s (~{total / elapsed:.1f} req/s) ===")
        print(f"status breakdown: {dict(stats)}")

        print("\n=== Checking viral links for lost hit-count updates (concurrent read-modify-write race) ===")
        for code in popular_codes:
            r = await client.get(f"/stats/{code}")
            actual = r.json()["hit_count"] if r.is_success else None
            expected = popular_hits[code]
            flag = "OK" if actual == expected else "MISMATCH (lost update under concurrency!)"
            print(f"  {code}: expected={expected} actual={actual} -> {flag}")


if __name__ == "__main__":
    asyncio.run(main())
