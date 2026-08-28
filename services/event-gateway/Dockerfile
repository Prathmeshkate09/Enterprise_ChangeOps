# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.11.15 AS uv

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN groupadd --system --gid 1001 changeops \
    && useradd --system --uid 1001 --gid changeops --create-home changeops

WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
COPY enterprise-sandbox/pyproject.toml enterprise-sandbox/pyproject.toml
COPY packages/contracts-python/pyproject.toml packages/contracts-python/pyproject.toml
COPY packages/changeops-core/pyproject.toml packages/changeops-core/pyproject.toml
COPY packages/persistence/pyproject.toml packages/persistence/pyproject.toml
COPY packages/policy-engine/pyproject.toml packages/policy-engine/pyproject.toml
COPY services/agent-fleet/pyproject.toml services/agent-fleet/pyproject.toml
COPY services/control-api/pyproject.toml services/control-api/pyproject.toml
COPY services/event-gateway/pyproject.toml services/event-gateway/pyproject.toml
COPY services/tool-gateway/pyproject.toml services/tool-gateway/pyproject.toml
COPY services/workflow-coordinator/pyproject.toml services/workflow-coordinator/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_HTTP_TIMEOUT=120 uv sync --frozen --no-dev --package changeops-event-gateway \
    --no-install-workspace

COPY packages/contracts-python packages/contracts-python
COPY packages/changeops-core packages/changeops-core
COPY packages/persistence packages/persistence
COPY services/event-gateway services/event-gateway
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_HTTP_TIMEOUT=120 uv sync --frozen --no-dev --package changeops-event-gateway

USER changeops
EXPOSE 8400
CMD ["/app/.venv/bin/uvicorn", "changeops_event_gateway.main:app", "--host", "0.0.0.0", "--port", "8400"]
