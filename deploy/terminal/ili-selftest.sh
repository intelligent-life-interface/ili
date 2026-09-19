#!/usr/bin/env bash
# ili-selftest — "does this installation work?", answered in one command.
#
# The AI in a project terminal runs this when something looks wrong, and so can a
# person. Most checks come from the api (GET /api/selftest, one source for the
# settings page and here); three things only this container can see are added
# locally: the Claude CLI, the running terminal sessions, and the docker CLI.
#
# --json prints the api answer raw (for the AI), otherwise a readable table.
# Always exits 0: a diagnosis must not abort whatever called it.
set -uo pipefail

API="${ILI_API_URL:-http://api:8798}"
JSON=0
[[ "${1:-}" == "--json" ]] && JSON=1

body="$(curl -fsS --max-time 20 "${API}/api/selftest" 2>/dev/null)"
rc=$?

if [[ $JSON -eq 1 ]]; then
    [[ $rc -eq 0 ]] && printf '%s\n' "$body" || printf '{"ok":false,"error":"api %s not reachable"}\n' "$API"
    exit 0
fi

echo "ili-Selbsttest"
echo "=============="
if [[ $rc -ne 0 ]]; then
    echo "FAIL  api           ${API} nicht erreichbar (curl ${rc})"
    echo "      → docker compose logs api"
else
    python3 - "$body" <<'PYEOF'
import json, sys
try:
    d = json.loads(sys.argv[1])
except Exception as e:
    print(f"FAIL  api           Antwort nicht lesbar: {e}")
    sys.exit(0)
for c in d.get("checks", []):
    mark = "PASS" if c.get("ok") else "FAIL"
    print(f"{mark}  {c.get('title', c.get('id', '?')):<18} {c.get('detail', '')}")
    if not c.get("ok") and c.get("hint"):
        print(f"      → {c['hint']}")
print()
print(d.get("note", ""))
PYEOF
fi

echo
echo "Nur in diesem Container sichtbar:"
if command -v claude > /dev/null 2>&1; then
    v="$(timeout 60 claude --version 2>&1 | head -1)"
    [[ -n "$v" ]] && echo "PASS  Claude-CLI         $v" || echo "FAIL  Claude-CLI         startet nicht → ili-claude-doctor"
else
    echo "FAIL  Claude-CLI         nicht installiert → ili-claude-doctor"
fi

sessions="$(tmux ls 2>/dev/null | wc -l)"
echo "INFO  Terminal-Sitzungen ${sessions} offen ($(tmux ls 2>/dev/null | cut -d: -f1 | tr '\n' ' '))"

if [[ -n "${DOCKER_HOST:-}" ]]; then
    if timeout 10 docker version --format '{{.Server.Version}}' > /tmp/.ili-docker 2>/dev/null; then
        echo "PASS  Docker-CLI         Server $(cat /tmp/.ili-docker) über ${DOCKER_HOST}"
    else
        echo "FAIL  Docker-CLI         ${DOCKER_HOST} antwortet nicht → Einstellungen → Docker"
    fi
    rm -f /tmp/.ili-docker
else
    echo "INFO  Docker-CLI         kein DOCKER_HOST gesetzt (Docker-Anbindung aus)"
fi
exit 0
