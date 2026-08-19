# ServiceLine API
#
# Docker rather than a host's native Python runtime, for two reasons:
#
#   1. The Python version is pinned here rather than in a hosting provider's
#      settings, so a local build and a deployed build are the same build.
#   2. It keeps the app portable. Moving off Render later is a change of
#      hosting, not a rewrite of the deployment.

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, in their own layer. Application code changes far more
# often than requirements.txt, so this keeps rebuilds fast.
#
# psycopg[binary] ships its own libpq, so no system Postgres client is needed.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user. Nothing here needs root, and a container that does not
# need it should not have it.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Render supplies $PORT; 8000 is the local default.
ENV PORT=8000
EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
