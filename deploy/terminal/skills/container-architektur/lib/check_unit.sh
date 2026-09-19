#!/usr/bin/env bash
# lib/check_unit.sh — rules for the rootless-Podman systemd user unit
# (User=, limits, health-cmd, network, image reference). Sourced by container-check.sh.

check_unit() {   # $1 = name, $2 = unit path (may be empty), $3 = project dir
    local n="$1" u="$2" dir="$3" a=unit run img
    if [[ -z "$u" ]]; then
        if compgen -G "$dir/docker-compose*.y*ml" >/dev/null || compgen -G "$dir/compose.y*ml" >/dev/null; then info "$n" $a "keine systemd-Unit, Compose vorhanden (Limits/Healthcheck dort prüfen)"
        else warn "$n" $a "keine Unit container-$n.service — läuft der Container anders (Timer, Host-Dienst, Quadlet)?"; fi
        return 0
    fi
    dbg "Unit $u"
    grep -qE '^User=' "$u" && fail "$n" $a "User= in der Unit → rootless Podman scheitert mit 216/GROUP ($(basename "$u"))"
    run="$(logical_lines "$u" | grep -E '^ExecStart=.*podman +run' | head -1)"
    if [[ -z "$run" ]]; then info "$n" $a "Unit ohne 'podman run' in ExecStart (Quadlet/Compose/Skript?) — Flags nicht prüfbar"; return 0; fi
    grep -qE -- '--memory[= ]' <<< "$run" && ok "$n" $a "--memory gesetzt: $(grep -oE -- '--memory[= ][^ ]+' <<< "$run")" \
        || warn "$n" $a "kein --memory in podman run (Richtwerte: FastAPI 512m, Claude-Terminal 1g, Browser/ML 2g+)"
    grep -qE -- '--cpus[= ]' <<< "$run" && ok "$n" $a "--cpus gesetzt: $(grep -oE -- '--cpus[= ][^ ]+' <<< "$run")" \
        || warn "$n" $a "kein --cpus in podman run (Richtwert 1.0, Browser/ML 2)"
    grep -qE -- '--health-cmd' <<< "$run" && ok "$n" $a "--health-cmd gesetzt" \
        || warn "$n" $a "kein --health-cmd (Podman ignoriert HEALTHCHECK aus OCI-Builds; rootless meldet mit --health-cmd nach ~16 s healthy)"
    grep -qE -- '--network[= ]' <<< "$run" && ok "$n" $a "Netz explizit: $(grep -oE -- '--network[= ][^ ]+' <<< "$run")" \
        || info "$n" $a "kein --network (Fallback slirp4netns/pasta, Container sehen sich nicht im monitoring-Netz)"
    grep -qE -- '--sdnotify=conmon' <<< "$run" || info "$n" $a "kein --sdnotify=conmon (Type=notify meldet dann nicht sauber)"
    grep -qE '^Restart=' "$u" || info "$n" $a "kein Restart= in der Unit"
    img="$(awk '{print $NF}' <<< "$run")"
    if [[ "$img" == localhost/* || "$img" == */* ]]; then :
    elif [[ "$img" == *:* || "$img" =~ ^[a-z0-9._-]+$ ]]; then warn "$n" $a "Fremd-Image kurz referenziert: '$img' → vollqualifiziert (docker.io/…)"; fi
}
