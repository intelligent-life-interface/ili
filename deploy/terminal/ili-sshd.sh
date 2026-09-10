#!/usr/bin/env bash
# ili-sshd.sh — starts the OpenSSH daemon inside the project terminal, but only
# if the operator actually asked for it by providing a public key.
#
# Called by entrypoint.sh in the background. Every exit path is non-fatal: a
# terminal container must come up even when the SSH part is misconfigured.
#
# The gate is deliberately the key file, not an on/off variable. No key means no
# way in, so there is no point in running a daemon; and an operator who mounts a
# key has unambiguously asked for SSH.
#
# Debug: docker compose logs -f terminal | grep ili-sshd
set -uo pipefail

log() { echo "[ili-sshd] $*" >&2; }

# Directory bind-mounted by docker-compose.ssh.yml (read-only). A directory
# rather than a single file on purpose: if the host path does not exist, the
# container runtime silently creates it — an empty directory is harmless and
# detectable, a directory where a file was expected is not.
KEYS_DIR="${SSH_KEYS_DIR_IN:-/etc/ssh/ili}"
HOSTKEY_DIR="${SSH_HOSTKEY_DIR:-/etc/ssh/hostkeys}"
SSH_USER="${SSH_USER:-ili}"

src="${KEYS_DIR}/authorized_keys"

if [[ ! -f "$src" ]]; then
    if [[ -d "$KEYS_DIR" ]]; then
        log "no SSH access: ${KEYS_DIR}/authorized_keys does not exist"
        log "  to enable it, put your PUBLIC key (~/.ssh/id_ed25519.pub) into"
        log "  ./ssh/authorized_keys next to the compose files and restart"
    fi
    exit 0
fi

# A file with only comments/blank lines would start a daemon nobody can log into.
if ! grep -qE '^[[:space:]]*(ssh-|ecdsa-|sk-)' "$src"; then
    log "WARN: ${src} holds no public key line — not starting sshd"
    exit 0
fi

# Absolute path on purpose: sshd refuses to run when it is invoked through a
# relative name or a PATH lookup ("sshd requires execution with an absolute
# path") — it needs to be able to re-exec itself for privilege separation.
SSHD_BIN="$(command -v sshd 2>/dev/null || true)"
[[ -z "$SSHD_BIN" && -x /usr/sbin/sshd ]] && SSHD_BIN=/usr/sbin/sshd
if [[ -z "$SSHD_BIN" ]]; then
    log "ERROR: sshd is not installed in this image — rebuild the terminal image"
    exit 0
fi

# Copy instead of pointing sshd at the mount: sshd's StrictModes rejects an
# authorized_keys file whose path is not owned as it expects, and a bind mount's
# ownership depends on the host user and the runtime (root vs. rootless).
home="$(getent passwd "$SSH_USER" | cut -d: -f6)"
if [[ -z "$home" ]]; then
    log "ERROR: user ${SSH_USER} does not exist in this image — rebuild the terminal image"
    exit 0
fi
mkdir -p "${home}/.ssh" || { log "ERROR: cannot create ${home}/.ssh"; exit 0; }
install -m 600 -o "$SSH_USER" -g "$SSH_USER" "$src" "${home}/.ssh/authorized_keys" \
    || { log "ERROR: cannot install authorized_keys"; exit 0; }
chown "$SSH_USER":"$SSH_USER" "${home}/.ssh" && chmod 700 "${home}/.ssh"
log "installed $(grep -cE '^[[:space:]]*(ssh-|ecdsa-|sk-)' "$src") public key(s) for ${SSH_USER}"

# Host keys in a volume, generated once. Without this the fingerprint changes on
# every container recreate and every client refuses to connect after an update.
mkdir -p "$HOSTKEY_DIR" || { log "ERROR: cannot create ${HOSTKEY_DIR}"; exit 0; }
for type in ed25519 rsa; do
    key="${HOSTKEY_DIR}/ssh_host_${type}_key"
    if [[ ! -f "$key" ]]; then
        log "generating ${type} host key (first start)"
        ssh-keygen -q -t "$type" -f "$key" -N '' -C "ili-terminal" \
            || log "WARN: could not generate ${type} host key"
    fi
    [[ -f "$key" ]] && chmod 600 "$key"
done
if [[ ! -f "${HOSTKEY_DIR}/ssh_host_ed25519_key" ]]; then
    log "ERROR: no host key available — not starting sshd"
    exit 0
fi

# sshd needs this for privilege separation; it lives on tmpfs and is gone after
# every restart.
mkdir -p /run/sshd && chmod 0755 /run/sshd

if ! "$SSHD_BIN" -t -f /etc/ssh/sshd_config; then
    log "ERROR: sshd config rejected — not starting sshd"
    exit 0
fi

log "starting sshd (key-only, user ${SSH_USER}, container port 22)"
# -D foreground, -e log to stderr so the lines show up in `docker compose logs`.
exec "$SSHD_BIN" -D -e -f /etc/ssh/sshd_config
