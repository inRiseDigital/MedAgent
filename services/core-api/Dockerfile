# syntax=docker/dockerfile:1
# Multi-stage build per 10 §1: build stage discarded, slim non-root runtime.
# Build context is the REPO ROOT so the shared packages/py-common can be installed.

# ---- build stage: install dependencies into an isolated venv -----------------
FROM python:3.12-slim AS build

WORKDIR /src
COPY packages/py-common /py-common
COPY services/core-api/pyproject.toml ./
COPY services/core-api/app ./app

RUN python -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --upgrade pip \
    && /venv/bin/pip install --no-cache-dir /py-common \
    && /venv/bin/pip install --no-cache-dir .

# ---- base runtime layer -------------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/venv/bin:$PATH"

WORKDIR /app
COPY --from=build /venv /venv
COPY services/core-api/app ./app
# Alembic tree ships in the image so the pre-rollout migration job can run
# `alembic upgrade head` (10 §9) — the app itself NEVER creates schema.
COPY services/core-api/alembic.ini ./alembic.ini
COPY services/core-api/alembic ./alembic

# Non-root numeric UID >= 10000 (10 §1).
USER 10001
EXPOSE 8000

# NOTE: no HEALTHCHECK here — compose/IaC own healthchecks and probe
# GET /healthz (liveness) and GET /readyz (readiness) per 10 §1.

# ---- dev target: uvicorn --reload, source bind-mounted by compose -------------
FROM base AS dev
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---- runtime target (default) --------------------------------------------------
FROM base AS runtime
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
