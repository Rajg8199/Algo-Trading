# One image for all Python services; SERVICE selects the entrypoint package.
# Build context is the repo root.
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

COPY pyproject.toml uv.lock alembic.ini ./
COPY libs ./libs
COPY services ./services
COPY migrations ./migrations
COPY scripts ./scripts
COPY docs/data ./docs/data

ARG SERVICE
RUN uv sync --frozen --no-dev --package "tp-${SERVICE}"

FROM python:3.12-slim
RUN groupadd -r app && useradd -r -g app app \
    && apt-get update && apt-get install -y --no-install-recommends curl tzdata \
    && rm -rf /var/lib/apt/lists/*
ENV TZ=Asia/Kolkata PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=builder /app /app
USER app

ARG SERVICE
ENV SERVICE=${SERVICE}
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD curl -fsS "http://localhost:${HEALTH_PORT:-8000}/health" || exit 1
CMD ["sh", "-c", "tp-${SERVICE}"]
