# Shipped Claude skills

The terminal image ships a set of Claude Code skills — architecture and convention
checklists (backend, frontend, container, database, network, security), planning and
prioritising, plus two scaffolds. Claude in the project terminal loads them on demand.

## How they get into a running installation

- Baked into the terminal image under `/opt/ili/skills/<name>/` (`deploy/Containerfile.terminal`).
- On every start `deploy/terminal/entrypoint.sh` mirrors them into
  `$CLAUDE_CONFIG_DIR/skills/<name>/` (the persistent `terminal-home` volume) and drops a
  `.ili-shipped` marker into each folder.
- Only folders with that marker are replaced on update. A skill you created or edited under
  the same name (no marker) is never touched — delete the marker to take a shipped skill over.
- `ILI_SKILLS=off` on the terminal service disables the mirroring.

## Where they come from

`deploy/terminal/skills/` is **generated** — do not edit it here. The maintainer's export
tool copies a whitelist of skills, replaces installation-specific values with placeholders
(`<DOMAIN>`, `<SERVER_IP>`, `<LAN_SUBNET>`, …), drops house-internal evidence sections and
refuses to write anything if its privacy gate still finds a hit.
`deploy/terminal/skills/EXPORT-MANIFEST.txt` lists the exported skills with a source hash.

The skills describe the conventions of the maintainer's stack (rootless Podman, Caddy, SQLite
first, central UI kit). Treat placeholders and paths as examples and adapt them to your setup;
the bundled check scripts report OK/WARN/FAIL; checks for things that only exist in the
maintainer's setup (Kanban board file, Caddyfile, systemd unit) degrade to WARN/INFO.
