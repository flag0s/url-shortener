#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting server (gunicorn + uvicorn workers)..."
exec gunicorn src.main:app \
  -k uvicorn.workers.UvicornWorker \
  -w 4 \
  --bind 0.0.0.0:8000 \
  --access-logfile - \
  --error-logfile -
