#!/usr/bin/env python3
"""Continuously generates traffic against the url-shortener app for local
Grafana/Prometheus/Jaeger demo purposes. Ctrl+C to stop."""

import argparse
import os
import random
import sys
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

MAX_KNOWN_CODES = 200


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("BASE_URL", "http://localhost:8000"),
    )
    parser.add_argument(
        "--min-delay", type=float,
        default=float(os.environ.get("SIM_MIN_DELAY", "0.2")),
    )
    parser.add_argument(
        "--max-delay", type=float,
        default=float(os.environ.get("SIM_MAX_DELAY", "1.2")),
    )
    parser.add_argument(
        "--startup-timeout", type=float,
        default=float(os.environ.get("SIM_STARTUP_TIMEOUT", "120")),
    )
    return parser.parse_args()


def wait_for_app(client: httpx.Client, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    delay = 0.5
    while True:
        try:
            r = client.get("/version", timeout=3.0)
            if r.status_code == 200:
                print(f"[ready] app responded on /version: {r.json()}")
                return
        except httpx.HTTPError as exc:
            print(f"[waiting] app not up yet ({exc.__class__.__name__}), retrying...")
        if time.monotonic() > deadline:
            print(f"[error] app did not become ready within {timeout}s, giving up.")
            sys.exit(1)
        time.sleep(delay)
        delay = min(delay * 1.5, 5.0)


def random_target_url() -> str:
    base = random.choice(SAMPLE_URLS)
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}v={uuid.uuid4().hex[:8]}"


def do_shorten(client, known_codes):
    url = random_target_url()
    try:
        r = client.post("/shorten", json={"url": url})
        if r.is_success:
            code = r.json()["short_code"]
            known_codes.append(code)
            del known_codes[:-MAX_KNOWN_CODES]
            print(f"[shorten] {url} -> {code} ({r.status_code})")
        else:
            print(f"[shorten] {url} -> HTTP {r.status_code}")
    except httpx.HTTPError as exc:
        print(f"[shorten] request failed: {exc}")


def do_redirect(client, known_codes):
    if not known_codes:
        return do_shorten(client, known_codes)
    code = random.choice(known_codes)
    try:
        r = client.get(f"/{code}", follow_redirects=False)
        print(f"[redirect] /{code} -> {r.status_code}")
    except httpx.HTTPError as exc:
        print(f"[redirect] request failed: {exc}")


def do_stats(client, known_codes):
    if not known_codes:
        return do_shorten(client, known_codes)
    code = random.choice(known_codes)
    try:
        r = client.get(f"/stats/{code}")
        print(f"[stats] /stats/{code} -> {r.status_code}")
    except httpx.HTTPError as exc:
        print(f"[stats] request failed: {exc}")


def do_bad_code(client, known_codes):
    bogus = uuid.uuid4().hex[:7]
    try:
        r = client.get(f"/{bogus}", follow_redirects=False)
        print(f"[404] /{bogus} -> {r.status_code}")
    except httpx.HTTPError as exc:
        print(f"[404] request failed: {exc}")


ACTIONS = [
    (do_shorten, 3),
    (do_redirect, 4),
    (do_stats, 2),
    (do_bad_code, 1),
]


def main():
    args = parse_args()
    known_codes: list[str] = []

    with httpx.Client(base_url=args.base_url) as client:
        wait_for_app(client, args.startup_timeout)
        print(f"[start] simulating traffic against {args.base_url} (Ctrl+C to stop)")

        actions, weights = zip(*ACTIONS)
        try:
            while True:
                action = random.choices(actions, weights=weights, k=1)[0]
                action(client, known_codes)
                time.sleep(random.uniform(args.min_delay, args.max_delay))
        except KeyboardInterrupt:
            print("\n[stop] interrupted by user, exiting.")


if __name__ == "__main__":
    main()
