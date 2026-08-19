#!/bin/sh
# Container entrypoint: migrate, optionally seed, then serve.
#
# `set -e` matters here. Without it a failed migration would be logged and the
# API would start anyway against a stale schema -- which is far worse than
# failing to start, because it fails silently.
set -e

echo "==> Running database migrations"
alembic upgrade head

if [ "${DEMO_MODE}" = "true" ]; then
    echo "==> Seeding demo data"
    # Idempotent: exits immediately if the demo tenants already exist, so this
    # is safe on every container start, including the wake-ups that a free-tier
    # instance does after sleeping.
    python -m app.seed_demo
fi

echo "==> Starting API on port ${PORT:-8000}"
# exec so uvicorn becomes PID 1 and receives SIGTERM directly. Without it the
# shell holds PID 1, swallows the signal, and every deploy waits for the
# platform's kill timeout instead of shutting down cleanly.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips '*'
