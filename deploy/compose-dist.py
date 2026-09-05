#!/usr/bin/env python3
"""Write the registry variant of the compose files into dist/.

Usage: compose-dist.py <src-dir> <dist-dir>

Copies the compose files (FILES below) from <src-dir> to
<dist-dir> with every service-level `build:` block removed. The files in the
repository keep their build blocks for source installs; the copies baked into
the api image are handed out by `... init` to installations without a checkout,
where a build block only causes `docker compose` to fail on the missing context.

Line-based on purpose (no PyYAML in the slim image): a build block is the line
`    build:` (service level, 4 spaces) plus every following line indented deeper.
Runs at image build time; fails the build if a `build:` survives.
"""
import os
import sys

FILES = ("docker-compose.yml", "docker-compose.terminal.yml",
         "docker-compose.lan.yml", "docker-compose.sandbox.yml",
         "docker-compose.hostdocker.yml")
SERVICE_INDENT = 4


def strip_build_blocks(text: str) -> tuple[str, int]:
    out, removed, skipping = [], 0, False
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if skipping:
            if stripped.strip() and indent <= SERVICE_INDENT:
                skipping = False
            else:
                continue
        if indent == SERVICE_INDENT and stripped.startswith("build:"):
            skipping = True
            removed += 1
            continue
        out.append(line)
    return "".join(out), removed


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    src, dist = sys.argv[1], sys.argv[2]
    os.makedirs(dist, exist_ok=True)
    for name in FILES:
        with open(os.path.join(src, name), encoding="utf-8") as fh:
            text = fh.read()
        result, removed = strip_build_blocks(text)
        if "build:" in result:
            print(f"[compose-dist] ERROR: build: survived in {name}", file=sys.stderr)
            return 1
        with open(os.path.join(dist, name), "w", encoding="utf-8") as fh:
            fh.write(result)
        print(f"[compose-dist] {name}: removed {removed} build block(s) "
              f"-> {dist}/{name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
