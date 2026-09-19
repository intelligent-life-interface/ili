#!/usr/bin/env bash
# lib/check_compose.sh — rules for docker-compose/compose files in the project dir
# (limits, healthcheck, fully qualified images). Sourced by container-check.sh.

check_compose() {   # $1 = name, $2 = project dir
    local n="$1" dir="$2" f
    for f in "$dir"/docker-compose*.y*ml "$dir"/compose.y*ml; do
        [[ -f "$f" ]] || continue
        dbg "Compose $f"
        # process substitution (not a pipe): the loop must run in this shell so the counters survive
        while IFS=$'\t' read -r lvl msg; do
            case "$lvl" in
                OK) ok "$n" compose "$msg" ;; WARN) warn "$n" compose "$msg" ;; INFO) info "$n" compose "$msg" ;;
            esac
        done < <(python3 - "$f" <<'PY'
import sys
try:
    import yaml
except ImportError:
    print("INFO\tpython3-yaml fehlt — Compose nicht geprüft"); sys.exit(0)
path = sys.argv[1]
try:
    data = yaml.safe_load(open(path, encoding="utf-8")) or {}
except Exception as e:
    print(f"WARN\tCompose nicht parsebar: {path}: {e}"); sys.exit(0)
base = path.rsplit("/", 1)[-1]
for svc, cfg in (data.get("services") or {}).items():
    if not isinstance(cfg, dict):
        continue
    limits = (cfg.get("deploy") or {}).get("resources", {}).get("limits", {}) if isinstance(cfg.get("deploy"), dict) else {}
    if not (cfg.get("mem_limit") or limits.get("memory")):
        print(f"WARN\t{base}: Service '{svc}' ohne mem_limit / deploy.resources.limits.memory")
    if not (cfg.get("cpus") or limits.get("cpus")):
        print(f"WARN\t{base}: Service '{svc}' ohne cpus-Limit")
    if not cfg.get("healthcheck") and (cfg.get("build") or str(cfg.get("image", "")).startswith("localhost/")):
        print(f"WARN\t{base}: eigener Service '{svc}' ohne healthcheck:")
    img = str(cfg.get("image", "")) 
    if img and "/" not in img and not cfg.get("build"):
        print(f"WARN\t{base}: Service '{svc}' Fremd-Image kurz referenziert: '{img}'")
    if cfg.get("mem_limit") or limits.get("memory"):
        print(f"OK\t{base}: Service '{svc}' mit Memory-Limit")
PY
        )
    done
    return 0
}
