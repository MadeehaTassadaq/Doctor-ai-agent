# Multi-stage build for Doctor Service
# Uses uv for fast dependency installation

# -- Builder Stage --
FROM ghcr.io/astral-sh/uv:python3.12-bookworm AS builder

WORKDIR /app

# Copy only dependency files first (layer caching)
COPY pyproject.toml ./

# Install dependencies into a virtual environment
RUN uv venv /app/.venv && \
    uv pip install --no-cache-dir -r <(uv export --no-dev)

# -- Runtime Stage --
FROM python:3.12-slim-bookworm

WORKDIR /app

# Install system dependencies required by asyncpg
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY app/ ./app/

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser
RUN chown -R appuser:appuser /app
USER appuser

# Add venv to path
ENV PATH="/app/.venv/bin:$PATH"

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8003/health')" || exit 1

EXPOSE 8003

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003", "--proxy-headers"]
