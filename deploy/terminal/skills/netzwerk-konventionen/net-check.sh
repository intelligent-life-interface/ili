#!/usr/bin/env bash
# net-check.sh — static + live check of a service against the netzwerk-konventionen
# rules (monitoring-Netz, Caddy-VHost + DNS-Doku, Upstream-Adresse, IPv6 aus).
#
# Usage:
#   net-check.sh <containername>     z.B. net-check.sh grafana
#   net-check.sh <port>              z.B. net-check.sh 8828
#
# Severity:  FAIL = nachweislich kaputt (dokumentierter Port, aber nichts lauscht)
#            WARN = ungeklaert oder bekannte Stolperfalle (Upstream-IP statt
#                   host.containers.internal, kein monitoring-Netz, kein Caddy-Bezug)
#            INFO = Hinweis, nichts lokal Pruefbares (Cloudflare-Access-Policy,
#                   IPv6-Abschaltung am Router) steht als Merkposten in der SKILL.md
# Output style folgt container-check.sh/repo-check.sh. Debug: CHECK_DEBUG=1
set -uo pipefail

CONTAINERS_MD="$HOME/containers/CONTAINERS.md"
CADDYFILE="$HOME/containers/caddy/Caddyfile"
DNS_DOC="$HOME/containers/caddy/docs/subdomains-dns.md"

JSON=0
OK=0 WARN=0 FAIL=0 INFO=0
FINDINGS_FILE=""

dbg() { [[ "${CHECK_DEBUG:-0}" == "1" ]] && echo "[net-check-debug $(date +%H:%M:%S)] $*" >&2; return 0; }
init_findings() { FINDINGS_FILE="$(mktemp)"; trap 'rm -f "$FINDINGS_FILE"' EXIT; }

record() {
    local lvl="$1" name="$2" area="$3" msg="$4"
    printf '%s\t%s\t%s\t%s\n' "$lvl" "$name" "$area" "$msg" >> "$FINDINGS_FILE"
    [[ "$JSON" == "1" ]] || printf '  %-5s %s\n' "$lvl" "$msg"
}
ok()   { record OK   "$1" "$2" "$3"; OK=$((OK+1)); }
warn() { record WARN "$1" "$2" "$3"; WARN=$((WARN+1)); }
fail() { record FAIL "$1" "$2" "$3"; FAIL=$((FAIL+1)); }
info() { record INFO "$1" "$2" "$3"; INFO=$((INFO+1)); }
header() { [[ "$JSON" == "1" ]] || echo "== $1"; }

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --json)    JSON=1; shift ;;
        -h|--help) usage 0 ;;
        -*)        echo "unbekannte Option: $1" >&2; usage 1 ;;
        *)         TARGET="${TARGET:-}$1"; shift ;;
    esac
done
[[ -n "${TARGET:-}" ]] || { echo "Ziel fehlt (Containername oder Port). -h fuer Hilfe." >&2; exit 2; }

init_findings

NAME="" PORT=""
if [[ "$TARGET" =~ ^[0-9]+$ ]]; then
    PORT="$TARGET"
    # Name aus CONTAINERS.md-Tabelle oder Unit mit -p ...:$PORT ableiten
    if [[ -f "$CONTAINERS_MD" ]]; then
        NAME="$(grep -E "\| $PORT( |$)|\`$PORT\`" "$CONTAINERS_MD" 2>/dev/null | head -1 | sed -E 's/^\|\s*`?([a-zA-Z0-9_-]+)`?.*/\1/')"
    fi
    if [[ -z "$NAME" ]]; then
        NAME="$(grep -lE -- "-p [^ ]*:?$PORT:" "$HOME"/.config/systemd/user/container-*.service 2>/dev/null | head -1 | sed -E 's#.*/container-(.+)\.service#\1#')"
    fi
    [[ -z "$NAME" ]] && NAME="port-$PORT"
else
    NAME="$TARGET"
    if [[ -f "$CONTAINERS_MD" ]]; then
        PORT="$(grep -iE "\`$NAME\`" "$CONTAINERS_MD" 2>/dev/null | head -1 | grep -oE '\b[0-9]{2,5}\b' | head -1)"
    fi
    if [[ -z "$PORT" && -f "$HOME/.config/systemd/user/container-$NAME.service" ]]; then
        PORT="$(grep -oE -- '-p [^ ]+:([0-9]+)(/tcp)?' "$HOME/.config/systemd/user/container-$NAME.service" 2>/dev/null | head -1 | sed -E 's#.*:([0-9]+)(/tcp)?#\1#')"
    fi
fi

header "$NAME${PORT:+ (Port $PORT)}"

# 1. Port frei/belegt
if [[ -n "$PORT" ]]; then
    listen_line="$(ss -ltnp 2>/dev/null | grep -E "[:.]$PORT[[:space:]]" | head -1)"
    if [[ -n "$listen_line" ]]; then
        ok "$NAME" port "Port $PORT belegt: $(awk '{print $1, $4}' <<<"$listen_line")"
    else
        fail "$NAME" port "Port $PORT ist dokumentiert, aber nichts lauscht — Dienst down oder Doku veraltet?"
    fi
else
    info "$NAME" port "kein Port ermittelt (weder CONTAINERS.md noch Unit-Datei) — als Argument mitgeben falls bekannt"
fi

# 2. Container im monitoring-Netz?
if command -v podman >/dev/null 2>&1 && podman inspect "$NAME" >/dev/null 2>&1; then
    nets="$(podman inspect "$NAME" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' 2>/dev/null)"
    if grep -qw monitoring <<<"$nets"; then
        ok "$NAME" network "im monitoring-Netz"
    elif [[ "$nets" == *"host"* ]]; then
        info "$NAME" network "läuft im Host-Netz (z.B. homeassistant) — monitoring-Netz nicht zutreffend"
    else
        warn "$NAME" network "NICHT im monitoring-Netz (gefunden: ${nets:-keins}) — ohne --network=monitoring fällt Podman auf slirp4netns zurück, andere Container sehen den Dienst dann nicht (Vorfall grafana)"
    fi
else
    info "$NAME" network "kein laufender Container '$NAME' gefunden — Netzwerk nicht geprüft (evtl. kein Container, z.B. Web-Terminal/systemd-Dienst)"
fi

# 3. Caddy-VHost + Upstream-Adresse (auskommentierte Bloecke ignorieren)
if [[ -f "$CADDYFILE" ]]; then
    match_line="$(grep -n -iE "\b$NAME\b" "$CADDYFILE" | grep -vE '^[0-9]+:[[:space:]]*#' | head -1)"
    if [[ -n "$match_line" ]]; then
        lineno="${match_line%%:*}"
        ok "$NAME" caddy "Caddyfile referenziert '$NAME' (Zeile $lineno)"
        # Upstream-Adresse in den 15 folgenden Zeilen pruefen, auskommentierte Zeilen ignorieren
        upstream="$(sed -n "${lineno},$((lineno+15))p" "$CADDYFILE" | grep -E 'reverse_proxy' | grep -vE '^[[:space:]]*#' | head -1)"
        if [[ -n "$upstream" ]]; then
            if [[ "$upstream" == *"127.0.0.1"* || "$upstream" == *"192.168."* ]]; then
                warn "$NAME" upstream "Upstream hardcodiert eine IP ($upstream) — host.containers.internal driftet je nach Default-Route (seit Reboot 04.09.2026 auf eth0/<SERVER_IP_ETH0>); bei restriktivem Bind stattdessen {\$CADDY_INTRANET_IP} verwenden, nie eine feste 127.0.0.1/192.168.x.x"
            else
                ok "$NAME" upstream "Upstream: $(sed -E 's/^\s*//' <<<"$upstream")"
            fi
        fi
    else
        warn "$NAME" caddy "kein Caddy-Block-Bezug zu '$NAME' gefunden — falls der Dienst über Caddy erreichbar sein soll, VHost fehlt (sonst ok, wenn rein LAN-intern ohne Subdomain)"
    fi
else
    info "$NAME" caddy "Caddyfile nicht gefunden ($CADDYFILE) — Check übersprungen"
fi

# 4. DNS-Doku
if [[ -f "$DNS_DOC" ]]; then
    if grep -qi "$NAME" "$DNS_DOC"; then
        ok "$NAME" dns "in docs/subdomains-dns.md dokumentiert"
    else
        info "$NAME" dns "kein Eintrag in docs/subdomains-dns.md — nur relevant, wenn '$NAME' eine eigene Subdomain hat"
    fi
fi

# 5. IPv6 aus (host-weit, nicht zielspezifisch)
if command -v ip >/dev/null 2>&1; then
    v6="$(ip -6 addr show scope global 2>/dev/null | grep -c inet6)"
    if [[ "${v6:-0}" -eq 0 ]]; then
        ok "$NAME" ipv6 "keine globale IPv6-Adresse auf diesem Host"
    else
        warn "$NAME" ipv6 "Host hat $v6 globale IPv6-Adresse(n) — LAN soll IPv6-frei bleiben (Policy: AdGuard aaaa_disabled am Router)"
    fi
fi

# 6. Internet-Exposure ohne Access — nur Hinweis, lokal nicht abschliessend pruefbar
if [[ -f "$CADDYFILE" ]] && grep -qi "\b$NAME\b" "$CADDYFILE" 2>/dev/null; then
    block="$(awk -v n="$NAME" 'BEGIN{IGNORECASE=1} /^[[:space:]]*#/{next} /^\*\.\{?\$?CADDY_DOMAIN\}? \{/{pub=1} /^\*\.intranet/{pub=0} pub && $0 ~ n {print; exit}' "$CADDYFILE")"
    if [[ -n "$block" ]]; then
        info "$NAME" exposure "'$NAME' scheint im OEFFENTLICHEN *.{\$CADDY_DOMAIN}-Block zu stehen — manuell verifizieren, dass eine Cloudflare-Access-Policy davorsteht (nicht lokal pruefbar, siehe security-konventionen §3 und SKILL.md Regel 5)"
    fi
fi

summary() {
    if [[ "$JSON" == "1" ]]; then
        python3 - "$FINDINGS_FILE" "$OK" "$WARN" "$FAIL" "$INFO" <<'PY'
import json, sys
rows = [l.rstrip("\n").split("\t", 3) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
print(json.dumps({
    "summary": {"ok": int(sys.argv[2]), "warn": int(sys.argv[3]), "fail": int(sys.argv[4]), "info": int(sys.argv[5])},
    "findings": [{"level": r[0], "target": r[1], "area": r[2], "message": r[3]} for r in rows if r[0] != "OK"],
}, ensure_ascii=False, indent=1))
PY
    else
        echo; echo "Ergebnis: OK=$OK WARN=$WARN FAIL=$FAIL INFO=$INFO"
        [[ $FAIL -eq 0 ]] || echo "FAIL beheben (Regeln: ~/.claude/skills/netzwerk-konventionen/SKILL.md)"
    fi
    [[ $FAIL -eq 0 ]]
}

summary
