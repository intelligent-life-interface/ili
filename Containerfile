FROM docker.io/library/python:3.11-slim

LABEL org.opencontainers.image.title="ili Dashboard"
LABEL org.opencontainers.image.description="Lightweight self-hosted Kanban Dashboard"
LABEL org.opencontainers.image.licenses="AGPL-3.0"
LABEL org.opencontainers.image.source="https://github.com/Toa1984/ili-dashboard"
LABEL org.opencontainers.image.url="https://github.com/Toa1984/ili-dashboard"

WORKDIR /app

# System Dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python Dependencies (separate layer for better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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

# Starter boards: the entrypoint copies them into the boards volume on first start
# only, so an update never touches an existing installation.
COPY demo/ demo/
# Compose files + .env template, handed out by `... init` / `... compose` so an
# installation from the registry needs no clone (see docker-entrypoint.sh).
COPY docker-compose.yml docker-compose.terminal.yml .env.example dist/
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
