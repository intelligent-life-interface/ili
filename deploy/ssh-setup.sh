#!/bin/bash
# ssh-setup.sh — one-step setup of the optional SSH access to the project terminal.
#
# Runs inside the api image (docker-entrypoint.sh: `ssh-setup`), with the
# installation folder mounted at /out — the same way `init` works:
#
#   docker run --rm -v "$PWD":/out ghcr.io/toa1984/ili ssh-setup "$(cat ~/.ssh/id_ed25519.pub)"
#   cat ~/.ssh/id_ed25519.pub | docker run --rm -i -v "$PWD":/out ghcr.io/toa1984/ili ssh-setup
#
# What it does (idempotent — running it twice changes nothing the second time):
#   1. checks the key(s): PUBLIC keys only, a private key is refused outright
#   2. appends them to /out/ssh/authorized_keys (creates the folder, skips duplicates)
#   3. writes docker-compose.ssh.yml and .env if they are missing
#   4. adds docker-compose.ssh.yml to COMPOSE_FILE in .env (existing entries stay)
#   5. sets SSH_BIND / SSH_PORT in .env — an existing value stays unless --bind /
#      --port is given explicitly
#   6. prints the one command that starts it
#
# It edits ONLY text files in /out. It never starts, stops or reaches into a
# container. Security frame is unchanged: key login only, user ili, no root login,
# default bind 127.0.0.1 — LAN only on an explicit --bind lan.
#
# Windows/PowerShell: a redirected .pub file may arrive as UTF-16 or with a BOM,
# and an .env saved by Set-Content may start with a BOM. Both are cleaned here
# (the reason this is a script and not a paragraph of documentation).
#
# Env (tests): OUT_DIR (default /out), DIST_DIR (default /app/dist).
# Debug: every step logs to stderr with the prefix [ssh-setup].
set -eu

OUT_DIR="${OUT_DIR:-/out}"
DIST_DIR="${DIST_DIR:-/app/dist}"
SSH_DIR="$OUT_DIR/ssh"
KEYS_FILE="$SSH_DIR/authorized_keys"
ENV_FILE="$OUT_DIR/.env"
OVERLAY="docker-compose.ssh.yml"

log()  { echo "[ssh-setup] $*" >&2; }
warn() { echo "[ssh-setup] WARN: $*" >&2; }
die()  { echo "[ssh-setup] ERROR: $*" >&2; exit 1; }

usage() {
    cat >&2 <<'USAGE'
ssh-setup — set up SSH access to the project terminal (key login only)

  docker run --rm -v "$PWD":/out ghcr.io/toa1984/ili ssh-setup [options] "<public key>"
  cat ~/.ssh/id_ed25519.pub | docker run --rm -i -v "$PWD":/out ghcr.io/toa1984/ili ssh-setup [options]
  (Podman: -v "$PWD":/out:Z)   (PowerShell: -v "${PWD}:/out", key via Get-Content | ... -i)

The key is the PUBLIC one (~/.ssh/id_ed25519.pub). No key pair yet? ssh-keygen -t ed25519

Options:
  --bind localhost   only this machine (default; writes SSH_BIND=127.0.0.1)
  --bind lan         reachable from your LAN (SSH_BIND=0.0.0.0) — deliberate, never the internet
  --bind <ipv4>      one specific interface address
  --port <1-65535>   host port (default 2222, never 22)
  -h, --help         this text
USAGE
}

# ─── arguments ───────────────────────────────────────────────────────────
BIND_ARG=""
PORT_ARG=""
KEY_ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --bind)   [ $# -ge 2 ] || die "--bind needs a value (localhost | lan | <ipv4>)"; BIND_ARG="$2"; shift 2 ;;
        --bind=*) BIND_ARG="${1#--bind=}"; shift ;;
        --port)   [ $# -ge 2 ] || die "--port needs a value"; PORT_ARG="$2"; shift 2 ;;
        --port=*) PORT_ARG="${1#--port=}"; shift ;;
        -h|--help) usage; exit 0 ;;
        *)        KEY_ARGS+=("$1"); shift ;;
    esac
done

BIND_VALUE=""
if [ -n "$BIND_ARG" ]; then
    case "$BIND_ARG" in
        localhost|local|127.0.0.1) BIND_VALUE="127.0.0.1" ;;
        lan|0.0.0.0)               BIND_VALUE="0.0.0.0" ;;
        *)
            printf '%s' "$BIND_ARG" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$' \
                || die "--bind '$BIND_ARG' is not localhost, lan or an IPv4 address"
            BIND_VALUE="$BIND_ARG" ;;
    esac
fi
if [ -n "$PORT_ARG" ]; then
    { printf '%s' "$PORT_ARG" | grep -Eq '^[0-9]{1,5}$' && [ "$PORT_ARG" -ge 1 ] && [ "$PORT_ARG" -le 65535 ]; } \
        || die "--port '$PORT_ARG' is not a port number (1-65535)"
    [ "$PORT_ARG" != "22" ] || die "port 22 is refused on purpose: it collides with an sshd on the host and attracts scanners"
fi

# ─── environment checks ──────────────────────────────────────────────────
[ -d "$OUT_DIR" ] || die "$OUT_DIR is not mounted. Run with:  -v \"\$PWD\":/out   (Podman: -v \"\$PWD\":/out:Z)"
[ -w "$OUT_DIR" ] || die "$OUT_DIR is not writable (SELinux? add :Z to the -v option)"

# ─── read + clean the key text ───────────────────────────────────────────
# tr removes CR, NUL, BOMs and UTF-16 marker bytes: none of them can occur in a
# valid key line, so dropping them globally repairs PowerShell output safely.
CLEAN='\r\000\377\376\357\273\277'
if [ ${#KEY_ARGS[@]} -gt 0 ]; then
    log "reading key from the command line"
    KEY_TEXT="$(printf '%s\n' "${KEY_ARGS[*]}" | tr -d "$CLEAN")"
elif [ ! -t 0 ]; then
    log "reading key from stdin"
    KEY_TEXT="$(tr -d "$CLEAN")"
else
    usage
    die "no public key given"
fi
[ -n "$(printf '%s' "$KEY_TEXT" | tr -d '[:space:]')" ] \
    || die "no public key received (with stdin, docker run needs the -i flag)"

KEY_RE='^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com)[[:space:]]+[A-Za-z0-9+/]+=*([[:space:]].*)?$'
VALID_KEYS=()
if printf '%s' "$KEY_TEXT" | grep -q 'PRIVATE KEY'; then
    die "that is a PRIVATE key. Never paste it anywhere. You need the PUBLIC one: ~/.ssh/id_ed25519.pub"
fi
while IFS= read -r line || [ -n "$line" ]; do
    line="$(printf '%s' "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    [ -z "$line" ] && continue
    case "$line" in \#*) continue ;; esac
    printf '%s' "$line" | grep -Eq "$KEY_RE" \
        || die "not a public key line (must start with ssh-ed25519 / ssh-rsa / ecdsa-sha2-… / sk-…): '${line:0:40}…'"
    VALID_KEYS+=("$line")
done <<< "$KEY_TEXT"
[ ${#VALID_KEYS[@]} -gt 0 ] || die "no public key line found"
log "${#VALID_KEYS[@]} valid public key line(s) received"

# Ownership of the mounted folder — files written as root would otherwise be
# owned by root on the host and annoying to edit or delete.
OWNER="$(stat -c '%u:%g' "$OUT_DIR" 2>/dev/null || echo "")"
own() { if [ -n "$OWNER" ]; then chown "$OWNER" "$@" 2>/dev/null || true; fi; }

# ─── 1) authorized_keys ──────────────────────────────────────────────────
mkdir -p "$SSH_DIR"
own "$SSH_DIR"
[ -f "$KEYS_FILE" ] || : > "$KEYS_FILE"
ADDED=0
for key in "${VALID_KEYS[@]}"; do
    id="$(printf '%s' "$key" | awk '{print $1 " " $2}')"
    if grep -qF -- "$id" "$KEYS_FILE"; then
        log "key already in ssh/authorized_keys — skipped (${key##* })"
        continue
    fi
    # Guarantee the previous last line ends in a newline before appending.
    if [ -s "$KEYS_FILE" ] && [ -n "$(tail -c1 "$KEYS_FILE")" ]; then
        printf '\n' >> "$KEYS_FILE"
    fi
    printf '%s\n' "$key" >> "$KEYS_FILE"
    ADDED=$((ADDED + 1))
    log "added key to ssh/authorized_keys (${key##* })"
done
chmod 644 "$KEYS_FILE"
own "$KEYS_FILE"
log "ssh/authorized_keys now holds $(grep -cE '^[[:space:]]*(ssh-|ecdsa-|sk-)' "$KEYS_FILE") key(s), $ADDED new"

# ─── 2) compose overlay + .env ───────────────────────────────────────────
if [ ! -f "$OUT_DIR/$OVERLAY" ]; then
    [ -f "$DIST_DIR/$OVERLAY" ] || die "$DIST_DIR/$OVERLAY missing in this image"
    cp "$DIST_DIR/$OVERLAY" "$OUT_DIR/$OVERLAY"
    own "$OUT_DIR/$OVERLAY"
    log "wrote $OVERLAY (was missing)"
elif ! cmp -s "$DIST_DIR/$OVERLAY" "$OUT_DIR/$OVERLAY"; then
    warn "$OVERLAY differs from the version in this image — left untouched (refresh with: ... init)"
fi

if [ ! -f "$ENV_FILE" ]; then
    [ -f "$DIST_DIR/.env.example" ] || die "$DIST_DIR/.env.example missing in this image"
    cp "$DIST_DIR/.env.example" "$ENV_FILE"
    own "$ENV_FILE"
    log "wrote .env from .env.example (was missing — still needs CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY)"
fi

# A BOM from Windows Set-Content -Encoding utf8 hides the first variable.
if [ "$(head -c3 "$ENV_FILE" | od -An -tx1 | tr -d ' \n')" = "efbbbf" ]; then
    warn ".env starts with a UTF-8 BOM (Windows) — removing it"
    sed -i '1s/^\xEF\xBB\xBF//' "$ENV_FILE"
fi

CR=""
if grep -q $'\r' "$ENV_FILE"; then CR=$'\r'; log ".env uses Windows line endings — keeping them"; fi

# env_get KEY — value of the LAST active KEY=... line (what docker compose uses).
env_get() { { grep -E "^$1=" "$ENV_FILE" || true; } | tail -n1 | cut -d= -f2- | tr -d '\r'; }

# env_set KEY VALUE — replace every active KEY=... line, or append one.
env_set() {
    local key="$1" value="$2"
    if grep -qE "^$key=" "$ENV_FILE"; then
        sed -i "s|^$key=.*|$key=$value$CR|" "$ENV_FILE"
    else
        # Guarantee the previous last line ends in a newline before appending.
        if [ -s "$ENV_FILE" ] && [ -n "$(tail -c1 "$ENV_FILE")" ]; then
            printf '%s\n' "$CR" >> "$ENV_FILE"
        fi
        printf '%s=%s%s\n' "$key" "$value" "$CR" >> "$ENV_FILE"
    fi
    own "$ENV_FILE"
    log ".env: $key=$value"
}

# ─── 3) COMPOSE_FILE ─────────────────────────────────────────────────────
COMPOSE_NOW="$(env_get COMPOSE_FILE)"
SEP="$(env_get COMPOSE_PATH_SEPARATOR)"
if [ -z "$COMPOSE_NOW" ]; then
    if [ -z "$SEP" ]; then SEP=":"; env_set COMPOSE_PATH_SEPARATOR ":"; fi
    env_set COMPOSE_FILE "docker-compose.yml${SEP}docker-compose.terminal.yml${SEP}$OVERLAY"
elif printf '%s' "$COMPOSE_NOW" | grep -qF "$OVERLAY"; then
    log ".env: COMPOSE_FILE already contains $OVERLAY — unchanged"
else
    if [ -z "$SEP" ]; then
        # No separator pinned: infer it from the existing value (Windows default is ';').
        case "$COMPOSE_NOW" in *";"*) SEP=";" ;; *) SEP=":" ;; esac
        warn "COMPOSE_PATH_SEPARATOR not set in .env — using '$SEP' as found in COMPOSE_FILE"
    fi
    env_set COMPOSE_FILE "${COMPOSE_NOW}${SEP}${OVERLAY}"
fi
printf '%s' "$(env_get COMPOSE_FILE)" | grep -qF "docker-compose.terminal.yml" \
    || warn "COMPOSE_FILE has no docker-compose.terminal.yml — SSH needs the terminal service"

# ─── 4) SSH_BIND / SSH_PORT ──────────────────────────────────────────────
# ensure_var NAME WANTED DEFAULT OPTION — WANTED comes from an explicit option and
# wins; without one an existing value stays, and only a missing one gets DEFAULT.
ensure_var() {
    local name="$1" wanted="$2" default="$3" option="$4" current
    current="$(env_get "$name")"
    if [ -n "$wanted" ]; then
        if [ "$current" = "$wanted" ]; then log ".env: $name=$wanted already set — unchanged"
        else env_set "$name" "$wanted"; fi
    elif [ -n "$current" ]; then
        log ".env: $name=$current stays (change it with $option)"
    else
        env_set "$name" "$default"
    fi
}
ensure_var SSH_BIND "$BIND_VALUE" "127.0.0.1" "--bind"
ensure_var SSH_PORT "$PORT_ARG" "2222" "--port"
if [ -n "$(env_get SSH_KEYS_DIR)" ]; then
    warn "SSH_KEYS_DIR is set in .env — the key was written to ./ssh, make sure that is the folder it points to"
fi

BIND_NOW="$(env_get SSH_BIND)"; PORT_NOW="$(env_get SSH_PORT)"
if [ "$BIND_NOW" != "127.0.0.1" ]; then
    warn "SSH listens on $BIND_NOW, not only on this machine. Anyone who can reach that address"
    warn "  and holds a listed key gets a shell with passwordless sudo. Never expose it to the internet."
fi

# ─── 5) next step ────────────────────────────────────────────────────────
HOST_HINT="127.0.0.1"
[ "$BIND_NOW" = "127.0.0.1" ] || HOST_HINT="<address-of-this-machine>"
log "done. Start (or restart) the stack:"
log "  docker compose up -d"
log "  (podman-compose ignores COMPOSE_FILE from .env — use: podman-compose -f docker-compose.yml -f docker-compose.terminal.yml -f $OVERLAY up -d)"
log "then connect:  ssh -p $PORT_NOW ili@$HOST_HINT"
log "if it does not answer:  docker compose logs terminal | grep ili-sshd"
