FROM python:3.12-slim

ARG ENVIRONMENT=production

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV THOMAS_ENV=${ENVIRONMENT}

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libcairo2-dev \
        libgirepository1.0-dev \
        pkg-config && \
    rm -rf /var/lib/apt/lists/*

# Copy dependency files first for layer caching
COPY pyproject.toml README.md ./

# Production: use lock file for reproducible builds
# Development: install with dev/test extras
COPY requirements-lock.txt ./
COPY thomas ./thomas

RUN python -m pip install --upgrade pip && \
    if [ "$ENVIRONMENT" = "production" ]; then \
        python -m pip install --no-cache-dir -r requirements-lock.txt && \
        python -m pip install --no-cache-dir ".[server]"; \
    else \
        python -m pip install --no-cache-dir ".[server,dev]"; \
    fi

# Copy production config template (dev overrides via volume mount)
COPY thomas.prod.toml ./thomas.prod.toml

# Set config based on environment
ENV THOMAS_CONFIG=${ENVIRONMENT:+/app/thomas.prod.toml}

EXPOSE 8899

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8899/api/health')" || exit 1

CMD ["python", "-m", "thomas.server", "--host", "0.0.0.0", "--port", "8899"]
