FROM docker.io/library/python:3.11-slim as builder

WORKDIR /app

# System Dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Build Python dependencies (separate layer for better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Final stage: minimal runtime image
FROM docker.io/library/python:3.11-slim

LABEL org.opencontainers.image.title="ili Dashboard"
LABEL org.opencontainers.image.description="Lightweight self-hosted Kanban Dashboard"
LABEL org.opencontainers.image.licenses="AGPL-3.0"
LABEL org.opencontainers.image.source="https://github.com/Toa1984/ili-public"
LABEL org.opencontainers.image.url="https://github.com/Toa1984/ili-public"
LABEL org.opencontainers.image.documentation="https://github.com/Toa1984/ili-public/blob/main/QUICKSTART.md"

WORKDIR /app

# System Dependencies — `upgrade` picks up the security fixes the base image
# does not carry yet.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Refresh setuptools/wheel AFTER the copy: the base image's own copies (and the
# jaraco.* vendored inside setuptools) stay behind as stale dist-info directories
# otherwise, and scanners keep flagging the old versions. Then drop pip itself:
# the runtime never installs anything, and pip carries vendored copies of
# msgpack/setuptools that scanners flag but nobody can update separately.
RUN pip install --no-cache-dir --upgrade setuptools wheel \
    && echo "[build] $(pip list --format=freeze 2>/dev/null | grep -i '^setuptools\|^wheel' | tr '\n' ' ')" \
    && pip uninstall -y pip \
    && rm -rf /root/.cache/pip

# Version + build metadata (ILI_COMMIT/ILI_BUILD_DATE are passed by ili-update.sh,
# plain `compose build` leaves them "unknown" — git is not needed inside the image)
ARG ILI_COMMIT=unknown
ARG ILI_BUILD_DATE=unknown
ENV ILI_COMMIT=${ILI_COMMIT} \
    ILI_BUILD_DATE=${ILI_BUILD_DATE}
COPY VERSION .

# Application Code & Root Modules
COPY *.py .
COPY app/ app/
COPY html/ html/
# Build-time import gate: app.main registers every router at import time, so a
# missing module (v0.1.11: claude_limits_service) fails the build here instead of
# shipping an image that crash-loops at runtime.
RUN python -c "import app.main" && echo "[build] app.main import OK"

# Starter boards: the entrypoint copies them into the boards volume on first start
# only, so an update never touches an existing installation.
COPY demo/ demo/
# Compose files + .env template, handed out by `... init` / `... compose` so an
# installation from the registry needs no clone (see docker-entrypoint.sh).
# The compose files in the repo carry `build:` blocks for source installs; the
# registry variant in dist/ must not — without a checkout docker compose would
# fall back to building when a pull fails and die on the missing deploy/ folder.
COPY .env.example dist/
COPY docker-compose.yml docker-compose.terminal.yml docker-compose.lan.yml \
     docker-compose.sandbox.yml docker-compose.hostdocker.yml \
     deploy/compose-dist.py /tmp/compose-src/
RUN python3 /tmp/compose-src/compose-dist.py /tmp/compose-src dist \
    && rm -rf /tmp/compose-src
# The sandbox overlay bind-mounts these two files by relative path
# (./deploy/gateway/...) — without them baked in, `init` cannot hand them out
# and `docker compose -f docker-compose.sandbox.yml up` fails on a registry
# install (no checkout to bind-mount from).
COPY deploy/gateway/nginx.conf deploy/gateway/10-generate-streams.sh dist/gateway/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Persistent Volumes
VOLUME ["/app/boards"]

# Configuration via Environment Variables
ENV DASHBOARD_DIR=/app \
    BOARDS_DIR=/app/boards \
    DASHBOARD_HOST=0.0.0.0 \
    DASHBOARD_PORT=8798 \
    DASHBOARD_DOMAIN=home.arpa

EXPOSE 8798

# Health Check
# Do NOT grep for board content here: a fresh installation has no boards, so
# looking for "columns" would keep the container "starting" forever.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fs http://localhost:8798/boards > /dev/null || exit 1

# Start Application — the entrypoint seeds the starter boards, then execs the CMD.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8798", "--log-level", "info"]
