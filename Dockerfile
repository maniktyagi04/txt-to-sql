# ==============================================================================
# Multi-stage secure build for Enterprise Text-to-SQL API
# ==============================================================================

# Stage 1: Build dependencies & download sentence-transformers model
FROM python:3.11-slim-bookworm AS builder

# Set shell and standard python environment flags
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install basic build tools and git
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install packages into a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .

# Install standard dependencies, forcing CPU-only torch to keep image light
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Pre-download the SentenceTransformer embedding model into builder cache
# so that the production run does not fetch models over the internet during startup.
RUN python -c "from sentence_transformers import SentenceTransformer; Model = SentenceTransformer('all-MiniLM-L6-v2')"

# ------------------------------------------------------------------------------
# Stage 2: Final minimal production image
# ------------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runner

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000 \
    ENVIRONMENT=production

WORKDIR /app

# Install standard utilities like sqlite3 and curl (for healthchecks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy pre-downloaded huggingface models from builder cache
COPY --from=builder /root/.cache/huggingface /home/appuser/.cache/huggingface

# Copy codebase
COPY app/ /app/app/

# Create database directories and empty structures
RUN mkdir -p /app/app/database/embeddings

# Add non-root system user for security hardening
RUN groupadd -g 1000 appgroup && \
    useradd -r -u 1000 -g appgroup -d /home/appuser -m -s /sbin/nologin appuser && \
    chown -R appuser:appgroup /app /home/appuser

USER appuser

# Expose server port
EXPOSE 8000

# Healthcheck for production container monitoring
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start production server with uvicorn running on 0.0.0.0
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--log-config", "/dev/null"]
