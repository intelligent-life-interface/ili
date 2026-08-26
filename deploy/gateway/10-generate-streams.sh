#!/bin/sh
# 10-generate-streams.sh — writes the gateway's port forwardings.
#
# Runs from /docker-entrypoint.d/ in the official nginx image, before nginx starts
# (same pattern as deploy/nginx-setup.sh in the web container). nginx' listen knows
# no port ranges, so every port gets its own server block.
#
# Result: host port N -> ${SANDBOX_HOST}:N, 1:1 and without any mapping table.
# Whoever runs `docker run -p 8100:3000 …` inside the sandbox reaches it at host:8100.
set -eu

FROM="${SANDBOX_PORT_FROM:-8100}"
TO="${SANDBOX_PORT_TO:-8119}"
TARGET_HOST="${SANDBOX_HOST:-sandbox}"
# DNS of the container network. 127.0.0.11 is Docker's built-in resolver; under
# Podman/netavark it sits on the network's gateway address (podman network inspect).
RESOLVER="${NGINX_RESOLVER:-127.0.0.11}"
OUT_DIR="/etc/nginx/stream.d"

log() { echo "[ili-gateway] $*"; }

# Catch misconfiguration early and loudly — an empty or inverted range would leave
# a gateway without a single forwarding, and an accidental 1-65535 would produce
# 65k nginx blocks.
case "$FROM$TO" in
    *[!0-9]*)
        log "ERROR: SANDBOX_PORT_FROM/TO must be numbers (from='$FROM' to='$TO')"
        exit 1
        ;;
esac
if [ "$FROM" -lt 1 ] || [ "$TO" -gt 65535 ] || [ "$FROM" -gt "$TO" ]; then
    log "ERROR: invalid port range $FROM-$TO (expected: 1 <= from <= to <= 65535)"
    exit 1
fi
COUNT=$((TO - FROM + 1))
if [ "$COUNT" -gt 200 ]; then
    log "ERROR: $COUNT ports requested ($FROM-$TO), the limit is 200."
    log "       Every port costs one nginx block and one host port mapping."
    exit 1
fi

mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR"/port-*.conf "$OUT_DIR"/00-resolver.conf

# Needed because the proxy_pass targets below are variables: only then does nginx
# resolve the sandbox name at RUNTIME. Without a variable nginx would resolve the
# address once at startup — if the sandbox restarts and gets a new address the
# gateway would point nowhere, and if the sandbox is not up yet nginx would refuse
# to start at all. Included first (00-), so it applies to every block after it.
cat > "$OUT_DIR/00-resolver.conf" <<RESOLV
resolver $RESOLVER valid=10s ipv6=off;
RESOLV

port="$FROM"
while [ "$port" -le "$TO" ]; do
    cat > "$OUT_DIR/port-$port.conf" <<STREAM
server {
    listen $port;
    set \$target ${TARGET_HOST}:$port;
    proxy_pass \$target;
}
STREAM
    port=$((port + 1))
done

log "generated $COUNT forwardings: port $FROM-$TO -> $TARGET_HOST:$FROM-$TO (DNS $RESOLVER)"
log "bind project containers in the sandbox to one of these ports, e.g.:"
log "    docker run -p ${FROM}:3000 my-project"
