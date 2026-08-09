# syntax=docker/dockerfile:1.6
#
# Yielda Ambience Profiling — single-image FastAPI container.
#
#   Build:  docker compose build
#   Run:    docker compose up
#   Open:   http://localhost:8000
#
# The image serves both the FastAPI backend and the Jinja-rendered UI
# (templates/demo.html) on $PORT, defaulting to 8000.
#
# No browser is installed: the Playwright-based moneypin crawler was replaced by
# `app/services/biz_lookup_service.py` (bizno REST). Nothing in `app/` imports
# playwright, and it is not in requirements.txt — installing Chromium here added
# ~700MB and broke the build.

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Minimal build-time tooling. `tini` gives us proper PID-1 signal handling
# so Ctrl-C stops uvicorn cleanly. `curl` powers the compose healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so this layer is cached across code-only edits.
COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Application code + assets. Order is fine-grained to maximise cache hits.
COPY app ./app
COPY templates ./templates
COPY static ./static
COPY data ./data

# Cache directories the services write into at runtime. Bind-mounting over
# these from the host (see docker-compose.yml) is optional but handy for
# inspecting what the app saved.
RUN mkdir -p cache/analyse cache/moneypin cache/places

EXPOSE 8000

# tini -> uvicorn ; `--host 0.0.0.0` is required for the port to be reachable
# from outside the container. `$PORT` is honoured because PaaS hosts (Render,
# Fly, Cloud Run) assign the port at runtime; locally it falls back to 8000.
# Shell form is deliberate — exec form would pass "${PORT:-8000}" literally.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
