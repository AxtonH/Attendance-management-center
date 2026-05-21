# Backend Dockerfile.
#
# Build context: REPO ROOT (not ./backend). This lets us COPY both
# backend/ AND config/ into the image. Railway is configured to use
# this Dockerfile with the repo root as build context — see
# backend/railway.toml.
#
# For local docker-compose the context is also the repo root via
# the override in docker-compose.yml.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# tini is a tiny init that reaps zombie processes and forwards
# signals correctly. Without it, gunicorn doesn't always shut down
# cleanly when Railway sends SIGTERM during a redeploy.
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first so they're cached when only app code changes.
COPY backend/pyproject.toml ./pyproject.toml
RUN pip install --upgrade pip \
    && pip install . \
    && pip install gunicorn

# Application code + shared config.
COPY backend/app ./app
COPY config /config

# CONFIG_DIR points to the in-image config so the app finds shift_rules.yaml
# without needing a volume mount on Railway.
ENV CONFIG_DIR=/config

# Railway injects PORT at runtime; default to 8000 for local docker runs.
ENV PORT=8000
EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
# gunicorn with uvicorn workers is the production-safe runner. Two
# workers is plenty for the dashboard's load profile (mostly cached
# Odoo state, occasional Supabase reads). Bumping workers later is
# a one-env-var change via gunicorn's --workers flag.
CMD ["sh", "-c", "gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 2 -b 0.0.0.0:${PORT} --access-logfile - --error-logfile -"]
