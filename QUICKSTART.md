# ili Dashboard — Quickstart

Welcome! **ili** is a lightweight, self-hosted Kanban dashboard for organizing projects, tasks, and ideas. This container gets you up and running in minutes.

## Prerequisites

- **Docker Compose** or **podman-compose** (`podman compose` also works on recent Podman)
- A couple of minutes

**Where to run it — ideally on a machine of its own.** ili is not a passive web
app: the project terminal is full shell access, and Claude acts inside it
autonomously (the Kanban automat works on cards while you are away). Upcoming
features let projects start their own containers. Everything ili can do, it can
do to the machine it runs on — so give it a dedicated one: an old laptop, a
mini PC, a Raspberry Pi 4/5 (arm64 images are provided), a small VM or a cheap
VPS. Your daily workstation works for a first look, but is not where ili should
live long-term.

**Very old `podman-compose` (seen: a Debian package reporting `0.0.1`) does not
substitute `${VAR}` placeholders in `docker-compose.yml` at all — it passes the
literal text through.** Terminal login (`TERMINAL_USER`/`TERMINAL_PASSWORD`) is
unaffected: it is read from `.env` directly via `env_file`, not `${}` syntax. But
anything that still relies on substitution — most notably pinning a registry
image with `ILI_VERSION` in `.env` (see below) — breaks: the tool tries to pull
an image whose tag is the literal text `${ILI_VERSION:-latest}` and fails. If
`docker compose pull` or `up` reports an image tag that literally contains `${`,
upgrade to `podman-compose >= 1.0` / `podman compose`, or edit the `image:`
lines in `docker-compose.yml` by hand.

**Podman users, one extra package:** the frontend reaches the backend by its
service name, which needs container DNS. Docker has that built in; Podman needs
`netavark` + `aardvark-dns`. On Debian 12 they are *not* pulled in by
`apt install podman` — without them the dashboard stays empty:

```bash
sudo apt install netavark aardvark-dns    # plus iptables, if your system lacks it
```

Symptom when it is missing: `docker compose logs web | grep ili-setup` reports
`api:8798 did not answer`.

## Why two containers?

The FastAPI backend (`api`) only serves the JSON API. The static frontend
(`html/`) is served by a small nginx (`web`) that also proxies API calls to
`api`. **Running only the `api` container gives you a working JSON backend
but no browser UI** — always use `docker compose up`, not a bare `docker run`.

## Quick Start

### 1. Prepare a Config File

```bash
cp .env.example .env
# Edit .env if you want to change DASHBOARD_DOMAIN or other settings
# (Optional: all defaults work out of the box)
```

### 2. Start the Stack

```bash
docker compose -f docker-compose.yml -f docker-compose.terminal.yml up -d --build
# or: podman-compose -f docker-compose.yml -f docker-compose.terminal.yml up -d
# (the terminal overlay is part of the standard start: it carries the Claude
#  bridge and the Kanban automat — without it new projects stay empty templates)
```

This builds the `api` image (`Containerfile`) and the `web` image
(`Containerfile.web`, nginx with the frontend baked in) and starts both. First
build takes a minute; subsequent starts are instant.

### Alternative: install from the registry (no clone, no build)

Prebuilt images for `linux/amd64` and `linux/arm64` (Apple Silicon, Raspberry Pi)
live on GitHub Container Registry — `ghcr.io/toa1984/ili` (api), `ghcr.io/toa1984/ili-web`
(web), `ghcr.io/toa1984/ili-terminal` (optional terminal) — and as a mirror on Docker Hub
(`toa1984/ili`, `toa1984/ili-web`, `toa1984/ili-terminal`). Both are public, no login
needed; the commands below use ghcr.io, swap in `toa1984/ili` if you prefer Docker Hub.

The api image carries its own compose files — let it write them (`init`), then start.

**macOS / Linux (Docker Desktop, Docker Engine, OrbStack) — bash/zsh:**

```bash
mkdir -p ~/ili && cd ~/ili
docker run --rm --pull always -v "$PWD":/out ghcr.io/toa1984/ili init
printf 'TERMINAL_USER=me\nTERMINAL_PASSWORD=change-me\n' >> .env      # optional, see step 4
docker compose -f docker-compose.yml -f docker-compose.terminal.yml up -d   # no --build
```

**Windows (Docker Desktop) — PowerShell:**

```powershell
New-Item -ItemType Directory -Force ~/ili | Out-Null; cd ~/ili
docker run --rm --pull always -v "${PWD}:/out" ghcr.io/toa1984/ili init
Add-Content -Path .env -Value "TERMINAL_USER=me`nTERMINAL_PASSWORD=change-me" -Encoding utf8   # optional
docker compose -f docker-compose.yml -f docker-compose.terminal.yml up -d
```

Two PowerShell traps: the mount must be quoted as `"${PWD}:/out"` — `"$PWD":/out`
splits the argument and Docker answers `invalid reference format`; and always append
to `.env` with `Add-Content -Encoding utf8` — `echo >> .env` writes UTF-16 in
Windows PowerShell 5 and Compose then cannot read the file.

**Linux with Podman (rootless):**

```bash
mkdir -p ~/ili && cd ~/ili
podman run --rm --pull always -v "$PWD":/out:Z ghcr.io/toa1984/ili init
podman-compose -f docker-compose.yml -f docker-compose.terminal.yml up -d
```

`:Z` relabels the folder on SELinux hosts; harmless elsewhere. Podman needs
`netavark` + `aardvark-dns` for container DNS (see Prerequisites).

**All platforms:** open <http://localhost:8080> after ~30 s. Leave the terminal file
out (`docker compose up -d` with only `docker-compose.yml`) if you do not want the
browser terminal. `--pull always` matters: without it an older `latest` already on
your machine is used silently (its entrypoint then fails with `exec: init: not found`).

`init` writes `docker-compose.yml`, `docker-compose.terminal.yml` and `.env` (from
`.env.example`; an existing `.env` is never touched). Other subcommands print a single
file instead: `... compose`, `... compose-terminal`, `... env`, `... help`.

Pin a version with `ILI_VERSION=0.1.11` in `.env` (default `latest`). Updates:
`docker compose pull && docker compose up -d` — rerun `init` after a release to pick
up compose changes (your `.env` stays).

### 3. Access the Dashboard

Open your browser and go to:
- **http://localhost:8080**

Port 8080 is the default because a rootless Docker or Podman user cannot bind
ports below 1024. Change it with `ILI_PORT` in `.env`.

That's it! You're running ili.

### 4. Optional: the project terminal

Each board can open a real shell in the browser, with its own persistent tmux
session and Claude Code inside. It is **not started by default**, because a
browser terminal is full shell access:

```bash
docker compose -f docker-compose.yml -f docker-compose.terminal.yml up -d --build
docker compose logs web | grep ili-setup   # prints the terminal password
```

**Already had the stack running?** Then `web` still carries the configuration from
its last start, where the terminal did not exist yet — the terminal route keeps
answering 503. One extra command fixes it:

```bash
docker compose -f docker-compose.yml -f docker-compose.terminal.yml restart web
```

Tired of typing both files? Remember the file list once, then plain `up`/`down`/
`logs` commands include the terminal:

```bash
# Docker Compose: put it in .env (the separator line makes it work on Windows too,
# where Compose expects `;` between files by default)
echo 'COMPOSE_PATH_SEPARATOR=:' >> .env
echo 'COMPOSE_FILE=docker-compose.yml:docker-compose.terminal.yml' >> .env

# podman-compose: it does not read COMPOSE_FILE from .env — export it in your shell
export COMPOSE_FILE=docker-compose.yml:docker-compose.terminal.yml
```

Signing in to Claude takes one extra step, because the container has no browser:
open a board terminal, copy the URL it prints, sign in with your own browser and
paste the code back. Prefer not to log in interactively? Put `ANTHROPIC_API_KEY`
or `CLAUDE_CODE_OAUTH_TOKEN` into `.env` instead.

Full details, including where your project code lives: **[docs/PROJECT-TERMINAL.md](docs/PROJECT-TERMINAL.md)**.

## What You Get

- **Kanban Boards** — organize projects and tasks
- **A guided setup** — a fresh install ships a `Einrichtung` project whose cards
  walk you through data, address, backups, AI and git; the options are decision
  cards with answer buttons, so you pick and your AI implements
- **Project Terminal** (optional) — browser shell with Claude Code per board
- **Responsive Design** — works on desktop, tablet, mobile
- **Zero External Dependencies** — runs locally, no cloud sync
- **Browser-based** — no installation needed for end users

## Configuration

All settings are in `.env` (see `.env.example` for the full, commented list):

| Variable | Default | Purpose |
|---|---|---|
| `DASHBOARD_PORT` | 8798 | Container-internal API port |
| `DASHBOARD_DOMAIN` | `home.arpa` | Domain used for generated links (nav, terminal, …) |
| `ANTHROPIC_API_KEY` | unset | Optional — enables Claude-based AI features |
| `CLAUDE_CODE_OAUTH_TOKEN` | unset | Optional — subscription token from `claude setup-token` |
| `OLLAMA_URL` | unset | Optional — enables local Ollama AI features |
| `TERMINAL_USER` / `TERMINAL_PASSWORD` | `ili` / generated | Login for the project terminal route |
| `ILI_PROJECTS_DIR` | `./projects` | Where the terminal keeps project code |

Without any AI key/URL set, all core Kanban functionality works normally —
only the AI-assisted features stay disabled.

## Troubleshooting

### Containers Won't Start
```bash
docker compose logs api
docker compose logs web
```

### Port Already in Use
Set `ILI_PORT` in `.env` to a free port, then `docker compose up -d` again. The
`api` service publishes no host port at all — the frontend reaches it inside the
compose network.

### `/` shows raw JSON instead of the dashboard
You started only the `api` container. Run `docker compose up -d` (both
services), not `docker run` against the API image alone.

### Reset Everything
```bash
docker compose down -v   # removes containers AND the boards/data volumes
docker compose up -d     # start fresh
```

## Updating to a Newer Version

```bash
git pull
docker compose build          # rebuild the api image with the new code
docker compose down           # existing containers would keep the old image
docker compose up -d
```

With the project terminal, add both files to every command (or set `COMPOSE_FILE`
as shown above):

```bash
CF="-f docker-compose.yml -f docker-compose.terminal.yml"
git pull && docker compose $CF build && docker compose $CF down && docker compose $CF up -d
```

Docker Compose users can shorten this to `up -d --build`. **podman-compose cannot**:
it ignores `--build` on `up` and keeps existing containers on the old image, so
`git pull` would appear to change nothing. The four steps above work on both.

That is the whole update. Afterwards the footer of the start page shows the new
version; `curl http://localhost:8080/api/version` prints it as JSON (version,
commit, build date, channel). Set `ILI_UPDATE_CHANNEL=beta` in `.env` to follow
pre-releases (`vX.Y.Z-beta.N`) instead of tagged releases only.

Everything of yours stays where it is:

| Yours | Where it lives | Survives an update |
|---|---|---|
| Boards and cards | volume `ili_dashboard-boards` | yes |
| App data | volume `ili_dashboard-data` | yes |
| Claude login of the terminal | volume `ili_terminal-home` | yes |
| Your settings | `.env` (git-ignored) | yes — `git pull` never touches it |
| Project code | `./projects`, or wherever `ILI_PROJECTS_DIR` points | yes — git-ignored |

Two things worth knowing:

- **Keep real project code outside the clone.** `./projects` works, but it lives
  inside the git working tree. Set `ILI_PROJECTS_DIR=/somewhere/else` in `.env` and
  a `git clean` or a fresh clone can never touch your code.
- **New settings appear in `.env.example`, not in your `.env`.** After an update,
  compare the two (`diff .env .env.example`) to see what is new.

## Reaching ili by its own address

Three ways, from simple to special. The first one is what we recommend.

### A. The machine's address is ili's address (recommended)

Run ili on a machine of its own (see Prerequisites) and that machine already
has an IP from your router's DHCP — you only need ili to answer on the normal
web port and to have a name:

1. `ILI_PORT=80` in `.env`, then `docker compose up -d`. Rootless Docker/Podman
   cannot bind ports below 1024 by default; allow it once on the host:
   ```bash
   echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/80-ili.conf
   sudo sysctl --system
   ```
2. A name instead of an IP: name the machine `ili` and install mDNS on the host
   (`sudo apt install avahi-daemon` on Debian/Ubuntu/Raspberry Pi OS; macOS and
   Windows resolve `.local` names out of the box). Then `http://ili.local/`
   works from every device in your LAN — no DNS, no router config.

Works with Docker and Podman, wired or Wi-Fi, on every OS.

### B. A separate IP for the web container (macvlan, static)

For a shared Linux box where ili should appear as its own device in the LAN.
Docker has **no DHCP client for containers** — the address is static; pick one
outside the router's DHCP range (or reserve it there).

1. In `.env`: `LAN_PARENT` (wired interface, e.g. `eth0`), `LAN_SUBNET`,
   `LAN_GATEWAY`, `LAN_IP`.
2. Add the overlay: `COMPOSE_FILE=docker-compose.yml:docker-compose.terminal.yml:docker-compose.lan.yml`
   (or pass all three `-f`), then `docker compose up -d`.

Limits (Docker / Linux kernel, not ili): Linux only — Docker Desktop on macOS
and Windows does not support macvlan. **The ili machine itself cannot reach
the macvlan address** — every other device can, so test from a phone or a
second computer. Wi-Fi as parent interface usually fails (one MAC per
association). The web container stays on the default network as well; that is
how it reaches the api container — keep both.

### C. Real DHCP with Podman (root)

Podman can let the container ask your DHCP server itself — with `netavark` ≥ 1.6
/ Podman ≥ 4.5, and **only as root** (rootless Podman has no access to the host
interfaces, with or without DHCP):

```bash
sudo systemctl enable --now netavark-dhcp-proxy.socket
sudo podman network create -d macvlan -o parent=eth0 --ipam-driver=dhcp ili-lan
```

Then use an overlay that attaches `web` to that external network **without** a
fixed address (the DHCP server assigns it):

```yaml
services:
  web:
    networks:
      default: {}
      lan: {}
networks:
  lan:
    external: true
    name: ili-lan
```

Because the network is root-owned, the whole stack runs as root then
(`sudo podman-compose …`). The kernel restriction from B applies here too.

## Data Persistence

Data lives in named volumes, prefixed with the compose project name `ili`
(fixed in `docker-compose.yml`, so renaming the folder does not orphan your
boards):

```bash
docker volume ls | grep ili_
```

To back up your boards:
```bash
docker run --rm -v ili_dashboard-boards:/data -v $(pwd):/backup \
  alpine tar czf /backup/ili-boards-backup.tar.gz -C /data .
```

`docker compose down` keeps the volumes; only `down -v` deletes them.

## Next Steps

A fresh installation starts with three projects — nothing is empty:

1. **👋 Willkommen** — the method in a handful of cards (a board is a project,
   who does what, decisions as cards)
2. **🔧 Einrichtung** — five sub-projects that configure your instance: data and
   database, address and external access, backups/updates/logs, AI connection,
   git and contributions. Cards marked 🟡 ENTSCHEIDUNG carry answer buttons —
   choose the variant you want, then let your AI implement it in that
   sub-project's terminal. Skip whatever you do not need.
3. **💡 Ideen** — tools that ship as ideas rather than code, ready to be built

Then: **➕ Neues Projekt** for your own work, and delete the starter boards once
they have served their purpose.

**To understand the methodology** — how boards work, adoption paths (use as-is vs.
custom structure), decision cards, and ownership roles — see **[docs/METHODIK.md](docs/METHODIK.md)**
(German, practical guide with examples).

## More Information

- **Privacy**: No tracking, all data stored locally
- **License**: AGPL-3.0

---

**Enjoy ili!** 🚀
