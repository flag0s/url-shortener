#!/bin/bash
# Rolling update demo for url-shortener.
#
# Usage:
#   ./scripts/rolling_update.sh          # rebuild and deploy with current APP_VERSION
#   APP_VERSION=1.1 ./scripts/rolling_update.sh   # deploy a new version
#
# True zero-downtime rolling updates require multiple replicas + a load balancer.
# This script shows the standard docker-compose update flow: build → replace container.
# The window without service (~1-2s) is the time between old container stop and new start.

set -e

cd "$(dirname "$0")/.."

echo "=== URL Shortener — Rolling Update ==="

# 1. Show what's currently running
echo ""
echo "[1] Current version:"
curl -sf http://localhost:8000/version && echo || echo "    (app not running yet)"

# 2. Rebuild only the app image; other services (postgres, jaeger, etc.) stay up
echo ""
echo "[2] Building new image..."
docker-compose build app

echo ""
echo "[3] Replacing container (other services stay up)..."
docker-compose up -d --no-deps app

# 4. Wait until the container passes its healthcheck
echo ""
echo "[4] Waiting for app to become healthy..."
until curl -sf http://localhost:8000/version > /dev/null 2>&1; do
  printf '.'
  sleep 1
done
echo " ready!"

# 5. Confirm the new version is live
echo ""
echo "[5] New version:"
curl -sf http://localhost:8000/version && echo

echo ""
echo "=== Done. Downtime was only the container restart gap (~1-2s). ==="
echo ""
echo "To deploy v1.1:"
echo "  1. Edit APP_VERSION in docker-compose.yml  (or export APP_VERSION=1.1)"
echo "  2. Run:  ./scripts/rolling_update.sh"
