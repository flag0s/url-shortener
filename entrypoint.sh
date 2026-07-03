#!/bin/bash
set -e

# Multiple gunicorn workers each have their own process memory, so
# prometheus_client needs multiprocess mode (shared mmap files) instead of
# its default in-memory registry, or /metrics would only ever reflect
# whichever single worker happened to answer that request.
export PROMETHEUS_MULTIPROC_DIR=${PROMETHEUS_MULTIPROC_DIR:-/tmp/prometheus_multiproc}
rm -rf "$PROMETHEUS_MULTIPROC_DIR"
mkdir -p "$PROMETHEUS_MULTIPROC_DIR"

echo "Running database migrations..."
alembic upgrade head

echo "Starting server (gunicorn + uvicorn workers)..."
exec gunicorn src.main:app \
  -k uvicorn.workers.UvicornWorker \
  -w 4 \
  --bind 0.0.0.0:8000 \
  --access-logfile - \
  --error-logfile - \
  -c gunicorn.conf.py
