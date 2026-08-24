#!/usr/bin/env bash
# ili-update.sh — update ili to a newer version
#
# This script is called by users after installing ili with `git clone` + `docker compose up`.
# It performs the update to a newer version from GitHub, preserving all user data
# (boards, attachments, Claude login, project code in terminal volume).
#
# Usage:
#   ./ili-update.sh
#
# The update channel (stable or beta) is read from .env:
#   ILI_UPDATE_CHANNEL=stable  → latest release (no pre-releases)
#   ILI_UPDATE_CHANNEL=beta    → latest release including pre-releases
#
# What the script does:
#   1. Fetch from GitHub to see what versions are available
#   2. Determine the correct tag based on the update channel
#   3. Check out that tag (git checkout)
#   4. Rebuild all images (podman-compose build)
#   5. Bring down the old containers (podman-compose down)
#   6. Bring up the new containers (podman-compose up -d)
#   7. Wait for the API to respond (health check)
#
# If any step fails, the old version keeps running (down happens only after
# successful build). User data survives in named volumes.

set -euo pipefail

# Configuration
COMPOSE_CMD="podman-compose"
[[ -x "$(command -v docker)" ]] && COMPOSE_CMD="docker compose"

API_PORT="${ILI_PORT:-8080}"
API_TIMEOUT=30
HEALTH_CHECK_RETRIES=30

# Colors for output (can be disabled via NO_COLOR)
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m'  # No Color
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
fi

# Logging functions
log()     { printf "${BLUE}[ili-update]${NC} %s\n" "$*"; }
success() { printf "${GREEN}✓${NC} %s\n" "$*"; }
error()   { printf "${RED}✗${NC} %s\n" "$*" >&2; }
warn()    { printf "${YELLOW}⚠${NC} %s\n" "$*"; }

# Exit on error
die() {
    error "$*"
    exit 1
}

# --- Helpers ---------------------------------------------------------------

read_env_channel() {
    # Read ILI_UPDATE_CHANNEL from .env, default to "stable"
    local channel
    if [[ -f .env ]]; then
        channel=$(grep -E '^ILI_UPDATE_CHANNEL=' .env | cut -d= -f2 | tr -d ' ' | tr '[:upper:]' '[:lower:]') || true
    fi
    case "${channel:-stable}" in
        beta) echo "beta" ;;
        *) echo "stable" ;;
    esac
}

get_latest_tag() {
    # Query GitHub Releases API to find the latest tag matching the channel
    # stable: latest release (excludes pre-releases)
    # beta:   any latest release (includes pre-releases)
    local channel="$1"
    local url="https://api.github.com/repos/Toa1984/ili-public/releases"
    local tag

    log "Checking GitHub for latest $channel release..."

    if [[ "$channel" == "beta" ]]; then
        # Take the first release (latest, including pre-releases)
        tag=$(curl -s --max-time "$API_TIMEOUT" "$url" | grep -m1 '"tag_name"' | grep -o 'v[0-9.]*\(-beta\.[0-9]*\)\?' || true)
    else
        # Take the first non-prerelease
        tag=$(curl -s --max-time "$API_TIMEOUT" "$url" | grep -B1 '"prerelease": false' | grep '"tag_name"' | head -1 | grep -o 'v[0-9.]*' || true)
    fi

    if [[ -z "$tag" ]]; then
        die "Could not determine latest tag from GitHub. Check your internet connection."
    fi

    echo "$tag"
}

get_current_version() {
    # Return the current version (from VERSION file or git tag)
    if [[ -f VERSION ]]; then
        cat VERSION
    else
        git describe --tags --always 2>/dev/null || echo "unknown"
    fi
}

# --- Main workflow ---------------------------------------------------------

main() {
    log "ili update script starting"

    # Verify we're in a git repository
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        die "Not in a git repository. Run this from the ili directory."
    fi

    # Verify docker-compose / podman-compose is available
    if ! command -v $COMPOSE_CMD &> /dev/null; then
        die "$COMPOSE_CMD not found. Please install Docker or Podman."
    fi

    log "Using: $COMPOSE_CMD"

    # Read configuration
    local channel
    channel=$(read_env_channel)
    log "Update channel: $channel"

    # Show current version
    local current_version
    current_version=$(get_current_version)
    log "Current version: $current_version"

    # Fetch from GitHub
    log "Fetching from GitHub..."
    if ! git fetch --quiet origin 2>/dev/null; then
        die "git fetch failed. Check your internet connection and SSH/HTTPS credentials."
    fi
    success "GitHub fetch successful"

    # Determine target tag
    local target_tag
    target_tag=$(get_latest_tag "$channel")
    log "Target tag: $target_tag"

    # Check if already on target version
    local current_tag
    current_tag=$(git describe --tags --exact-match 2>/dev/null || echo "")
    if [[ "$current_tag" == "$target_tag" ]]; then
        warn "Already on $target_tag — running build anyway (volumes may need reinitialization)"
    else
        log "Updating from $current_tag to $target_tag"
    fi

    # Checkout the tag
    log "Checking out $target_tag..."
    if ! git checkout --quiet "$target_tag" 2>/dev/null; then
        die "git checkout $target_tag failed."
    fi
    success "Checked out $target_tag"

    # Rebuild images
    log "Building images (this may take a minute)..."
    if ! $COMPOSE_CMD -f docker-compose.yml -f docker-compose.terminal.yml build > /tmp/ili-build.log 2>&1; then
        error "Build failed. Details:"
        tail -20 /tmp/ili-build.log >&2
        die "Build failed. Old containers are still running."
    fi
    success "Images built successfully"

    # Bring down old containers (only after successful build)
    log "Stopping old containers..."
    $COMPOSE_CMD -f docker-compose.yml -f docker-compose.terminal.yml down >> /tmp/ili-build.log 2>&1 || true
    success "Old containers stopped"

    # Bring up new containers
    log "Starting new containers..."
    if ! $COMPOSE_CMD -f docker-compose.yml -f docker-compose.terminal.yml up -d >> /tmp/ili-build.log 2>&1; then
        error "Failed to start new containers. Manual intervention may be needed."
        exit 1
    fi
    success "New containers started"

    # Health check: wait for API to respond
    log "Waiting for API to be ready..."
    local attempts=0
    local api_ready=false

    while (( attempts < HEALTH_CHECK_RETRIES )); do
        if curl -s --max-time 5 \
            -o /dev/null -w '%{http_code}' \
            "http://localhost:${API_PORT}/boards" 2>/dev/null | grep -q '^200$'; then
            api_ready=true
            break
        fi
        (( attempts++ ))
        sleep 1
    done

    if $api_ready; then
        success "API is responding"
        local new_version
        new_version=$(get_current_version)
        log "Update complete! New version: $new_version"
        log "ili is available at http://localhost:${API_PORT}"
    else
        error "API failed to respond after update. Logs:"
        $COMPOSE_CMD -f docker-compose.yml -f docker-compose.terminal.yml logs --tail=20 api 2>/dev/null | tail -20 >&2
        die "Update completed but API health check failed."
    fi
}

# --- Entry point -----------------------------------------------------------

if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
    cat << 'EOF'
ili update script — update to a newer version

Usage: ./ili-update.sh [OPTIONS]

Options:
  --help, -h      Show this help text
  --channel CHAN  Override update channel (stable or beta)

Environment variables:
  ILI_PORT        Port where ili listens (default: 8080)
  ILI_UPDATE_CHANNEL  Release channel (stable or beta; read from .env by default)
  NO_COLOR        Disable colored output

The script reads .env to determine the release channel (stable or beta).
User data (boards, attachments, Claude login, project code) is preserved
in named volumes and survives every update.

Example:
  ./ili-update.sh
  ILI_UPDATE_CHANNEL=beta ./ili-update.sh
EOF
    exit 0
fi

main
