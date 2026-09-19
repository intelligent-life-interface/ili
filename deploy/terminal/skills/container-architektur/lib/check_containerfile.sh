#!/usr/bin/env bash
# lib/check_containerfile.sh — rules for the Containerfile/Dockerfile itself
# (base image, layer order, runtime content, healthcheck). Sourced by container-check.sh.

check_containerfile() {   # $1 = name, $2 = Containerfile path, $3 = build context dir
    local n="$1" cf="$2" ctx="$3" a=containerfile
    local lines froms last_from img alpine=0 has_run=0 first_run_no=0 label_before_run=0
    lines="$(logical_lines "$cf")"
    dbg "Containerfile $cf ($(wc -l <<< "$lines") logische Zeilen), Kontext $ctx"

    # --- base images: every FROM that is not a previous stage
    froms="$(grep -E '^FROM ' <<< "$lines" | sed -E 's/^FROM +(--platform=[^ ]+ +)?//; s/ +[Aa][Ss] +.*$//')"
    local stages; stages="$(grep -iE '^FROM .* AS ' <<< "$lines" | sed -E 's/.* [Aa][Ss] +//' | tr '\n' ' ')"
    while read -r img; do
        [[ -n "$img" ]] || continue
        [[ " $stages " == *" $img "* ]] && continue
        [[ "$img" == */* ]] || warn "$n" $a "kurzer Image-Name '$img' → vollqualifiziert 'docker.io/library/$img' (Podman löst nur über Suchregistry)"
        if [[ "${img##*/}" != *:* ]]; then warn "$n" $a "Basis-Image '$img' ohne Tag (= latest, nicht reproduzierbar)"
        elif [[ "$img" == *:latest ]]; then warn "$n" $a "Basis-Image '$img' auf :latest gepinnt (nicht reproduzierbar)"; fi
    done <<< "$froms"
    last_from="$(tail -1 <<< "$froms")"
    [[ "$last_from" == *alpine* ]] && alpine=1
    [[ -n "$last_from" ]] && ok "$n" $a "Runtime-Basis: $last_from"

    # --- alpine + bash entrypoint scripts = container does not start
    if [[ $alpine -eq 1 ]]; then
        if grep -qE '^RUN .*apk (add|--no-cache add|add --no-cache)[^&]*\bbash\b' <<< "$lines"; then
            ok "$n" $a "Alpine mit installiertem bash"
        else
            local src bashscripts="" found=0
            for src in $(grep -E '^COPY ' <<< "$lines" | grep -v -- '--from' | sed -E 's/^COPY +(--[^ ]+ +)*//' | awk '{NF--; print}' | tr ' ' '\n' | grep -E '\.sh$'); do
                [[ -f "$ctx/$src" ]] || continue; found=1
                head -1 "$ctx/$src" | grep -qE '^#!.*\bbash\b' && bashscripts="$bashscripts $src"
            done
            if [[ -n "$bashscripts" ]]; then fail "$n" $a "Alpine ohne bash, aber bash-Skripte kopiert:$bashscripts → 'apk add bash' oder Debian-slim"
            elif grep -qE '^(ENTRYPOINT|CMD) .*\bbash\b' <<< "$lines"; then fail "$n" $a "Alpine ohne bash, ENTRYPOINT/CMD ruft bash"
            elif [[ $found -eq 0 ]]; then warn "$n" $a "Alpine ohne bash — Entrypoint-Skripte nicht im Kontext prüfbar (--context setzen)"
            else ok "$n" $a "Alpine: kopierte Skripte brauchen kein bash"; fi
        fi
    fi

    # --- layer order / cache hygiene
    local i=0 l
    while IFS= read -r l; do
        i=$((i+1))
        [[ "$l" == RUN* ]] && { has_run=1; [[ $first_run_no -eq 0 ]] && first_run_no=$i; }
        [[ "$l" == LABEL* && $has_run -eq 0 ]] && label_before_run=1
        if [[ "$l" =~ ^RUN\  ]]; then
            if grep -qE 'apt-get install' <<< "$l"; then
                grep -qE '/var/lib/apt/lists' <<< "$l" || warn "$n" $a "apt-get install ohne 'rm -rf /var/lib/apt/lists/*' im selben RUN (Layer ~20-40 MB grösser)"
                grep -qE 'apt-get update' <<< "$l" || warn "$n" $a "apt-get install ohne apt-get update im selben RUN (veralteter Paket-Cache-Layer)"
                grep -qE -- '--no-install-recommends' <<< "$l" || info "$n" $a "apt-get install ohne --no-install-recommends"
            elif grep -qE 'apt-get update' <<< "$l"; then
                warn "$n" $a "apt-get update als eigener Layer (mit install in einem RUN zusammenlegen)"
            fi
            grep -qE 'pip3? install' <<< "$l" && ! grep -qE -- '--no-cache-dir' <<< "$l" && warn "$n" $a "pip install ohne --no-cache-dir (pip-Cache bleibt im Layer)"
            grep -qE 'chmod \+x' <<< "$l" && info "$n" $a "separater 'RUN chmod +x'-Layer → COPY --chmod=755 spart ihn"
        fi
        if [[ "$l" =~ ^(COPY|ADD)\ +(\./?|\.\ ) ]] || [[ "$l" =~ ^(COPY|ADD)\ +\.\ +/ ]]; then
            grep -qE '^RUN .*(pip3? install|npm (ci|install)|apt-get install)' <<< "$(tail -n +$((i+1)) <<< "$lines")" \
                && warn "$n" $a "ganzer Kontext (COPY .) VOR dem Dependency-Install kopiert → jede Code-Änderung baut die Abhängigkeiten neu"
        fi
    done <<< "$lines"
    [[ $label_before_run -eq 1 ]] && info "$n" $a "LABEL vor dem ersten RUN — Label-Edits invalidieren alle Layer darunter (LABEL ans Ende)"
    grep -qE '^RUN .*apt-get install' <<< "$lines" && ! grep -qE '^RUN .*apt-get upgrade' <<< "$lines" \
        && info "$n" $a "kein 'apt-get upgrade -y' im Build (Basis-CVEs bleiben bis zum nächsten Basis-Pull)"

    # --- runtime content
    if grep -qE 'anthropic-ai/claude-code|claude\.ai/install|/claude-code' "$cf"; then
        # A Claude *runner* image (ttyd terminal, ili) is the one legitimate place for Claude Code.
        if grep -qE 'container-check: *allow claude-code' "$cf" || grep -qE '\bttyd\b' "$cf"; then
            ok "$n" $a "Claude Code im Image — Claude-Läufer-Image (ttyd/Marker), erlaubt"
        else
            fail "$n" $a "Claude Code im App-Image (Entscheid 09.09.2026: Host-Claude + delegate statt Node im App-Image; Läufer-Images markieren: '# container-check: allow claude-code')"
        fi
    fi

    # --- healthcheck
    local hc; hc="$(grep -E '^HEALTHCHECK' <<< "$lines" | head -1)"
    if [[ -z "$hc" ]]; then
        warn "$n" $a "kein HEALTHCHECK (für Docker/Compose-Nutzer; Podman-Unit braucht zusätzlich --health-cmd)"
    else
        if grep -qE '\b(curl|wget)\b' <<< "$hc"; then
            grep -qE '^RUN .*(apt-get install|apk add)[^&]*\b(curl|wget)\b' <<< "$lines" \
                || warn "$n" $a "HEALTHCHECK nutzt curl/wget, aber kein Install-Layer nennt es (python/alpine-slim haben es nicht) → Healthcheck dauerhaft rot"
        fi
        if grep -qE "https?://[^/ \"']+/?[\"' ]|https?://[^/ \"']+/?$" <<< "$hc"; then
            warn "$n" $a "HEALTHCHECK prüft nur die Startseite/Root — echten API-Pfad (/health mit Backend-Logik) nehmen"
        else
            ok "$n" $a "HEALTHCHECK vorhanden: ${hc:0:80}"
        fi
    fi
}
