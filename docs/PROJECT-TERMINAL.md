# Project Terminal — browser shell with Claude Code per board

> **Tags:** terminal, projterm, ttyd, tmux, claude-code, login, device-code, auth, basic-auth, websocket, compose-datei

Every board in ili can open a terminal: a real shell in the browser, with its own
persistent [tmux](https://github.com/tmux/tmux) session and its own working
directory. That is where the AI work happens — the board is the memory, the
terminal is the workbench.

The terminal is **off by default**, because a browser terminal is full shell
access to the container.

## Start it

```bash
docker compose -f docker-compose.yml -f docker-compose.terminal.yml up -d      # podman-compose works too
docker compose logs web | grep ili-setup
```

The second command prints the password for the terminal route. Without
`TERMINAL_PASSWORD` in `.env` a new one is generated on every start:

```
[ili-setup] ================ ili project terminal ================
[ili-setup]    user:     your_username
[ili-setup]    password: YOUR_PASSWORD_HERE
```

Then open a board and switch to the terminal — the browser asks for those
credentials once.

As long as the password is generated, the board's terminal panel shows a hint
saying so — it reads `/projterm/state`, a two-field endpoint the setup script
writes alongside the route. The endpoint answers without a password (the page
could not read it otherwise) and reveals only *whether* a password was
personalised, never what it is.

To keep a stable password, put it in `.env`:

```ini
TERMINAL_USER=ili
TERMINAL_PASSWORD=choose-something-long
```

## Sign in to Claude

The container has no browser, so the usual OAuth redirect to `localhost` cannot
work. Claude Code covers exactly this case (it is documented for SSH sessions and
containers): it prints a URL and waits for a code.

**Pick whichever fits you — but pick one.** The bare Kanban board works without a
sign-in, yet every new project then stays an empty template: project preparation
(CLAUDE.md, tags, idea cards), the board assistant and the Kanban automat all go
through the Claude bridge inside this container (port 8950, reached by `api` as
`http://terminal:8950`). Since v0.1.7 the board shows a red «KI-Vorbereitung
fehlgeschlagen» card when the bridge is down or not signed in.

| Way | What you do | Good for |
|---|---|---|
| **Interactive login** | Open a board terminal. The board page shows a sign-in panel: **Open** starts the sign-in in your own browser, the code goes into the panel's field and is sent to the terminal for you. (The panel gets the URL from `GET /api/claude-login-url` — `ili-claude` tees Claude's output through `ili-login-url-watch`, which stores the unbroken URL in the terminal home; reading the screen buffer is only the fallback.) (By hand: the URL printed in the terminal breaks across lines — join the pieces without spaces, otherwise the sign-in page answers `Unknown scope: user`.) | Claude subscription, nothing to prepare |
| **`CLAUDE_CODE_OAUTH_TOKEN`** | Run `claude setup-token` once on a machine that has a browser, put the token (valid one year) into `.env` | Claude subscription, unattended start |
| **`ANTHROPIC_API_KEY`** | Create a key in the Anthropic Console, put it into `.env` | Pay-per-use, no login at all |

The interactive login is stored in the `terminal-home` volume
(`/root/.claude` + `/root/.claude.json`) and survives restarts. Removing that
volume means signing in again.

> Copying the URL out of a browser terminal is a bit awkward — select it with the
> mouse, or long-press on a phone. The board page shows a **login helper panel**
> automatically while the interactive login is pending: it reads the sign-in URL
> straight out of the terminal (a clickable link, no more manual selection) and
> writes the code you paste back into the same terminal session for you.
>
> **How it works without a backend call:** `api` and `terminal` are separate
> containers with no shared tmux socket, so the panel cannot ask a server "is
> Claude logged in" by inspecting the pty. Two different channels are used
> instead:
> - *Status* (`GET /api/claude-status`, `app/api/misc.py`): the `terminal-home`
>   volume is mounted **read-only** into `api` (only when
>   `docker-compose.terminal.yml` is active) and the endpoint checks the same
>   file `deploy/terminal/ili-claude.sh` checks — `.credentials.json` — plus
>   the `ANTHROPIC_API_KEY`/`CLAUDE_CODE_OAUTH_TOKEN` env vars.
> - *Sending the code* (`html/claude-login-panel.html`): the terminal is a
>   same-origin `<iframe>` (`/projterm/`), so the panel talks to it directly
>   through `window.PTTerm` (exported by `html/js/project-terminal-fit.js`) —
>   the identical data channel the on-screen keyboard and input line already
>   use to write into the pty. No API round-trip, so it keeps working
>   regardless of how `api` and `terminal` are split across containers.

## Where your code lives

Each board gets a working directory: `/projects/<board-id>`, created on first
open. That is the convention **project = board**.

By default `/projects` is the `./projects` folder next to `docker-compose.yml`.
To work on code you already have:

```ini
ILI_PROJECTS_DIR=/home/you/code
```

**Rootless Podman:** works out of the box — the container's root maps to your
unprivileged user, so bind-mounted files stay writable.
**Docker:** the container runs as root, so files it creates in a bind mount are
owned by root on the host. Either accept that, or pin the container to your own
ids in a `docker-compose.override.yml`:

```yaml
services:
  terminal:
    user: "1000:1000"
    environment:
      HOME: /projects/.home
      CLAUDE_CONFIG_DIR: /projects/.home/.claude
```

## A database for your projects

The standard stack starts a PostgreSQL container called `db`. It is there so
the projects you build in the terminal have a database ready without setting
one up first — ili's own boards stay JSON files, that part has not changed.
ili's `api` container does use `db` for one thing of its own though: it
mirrors its WARNING/ERROR log lines into a `logs` table so `bugs.html` has
real data to show (see below, and `docs/LOGGING.md`) — without `db` that
falls back to stdout-only logging, nothing breaks.

Reach it from code running in the terminal:

```
host db · port 5432
postgresql://ili:CHANGE-ME@db:5432/ili
```

Credentials come from `.env` (`POSTGRES_USER`, `POSTGRES_PASSWORD`,
`POSTGRES_DB`). `CHANGE-ME` is what `init` writes into a fresh `.env`, and also
the fallback the compose file uses when the line is missing entirely — so it is
the password until you pick one yourself. **Change it before you store anything
real.** After editing
`.env` the database has to be recreated, because postgres only reads those
variables when it initialises an empty data directory:

```bash
docker compose down
docker volume rm ili_db-data     # deletes the data in it
docker compose up -d
```

The port is not published to the host, so the database is only reachable inside
the compose network. To attach a database tool, uncomment the `ports:` block in
the `db` service — it binds to `127.0.0.1` so it does not land on the LAN. If
port 5432 is already taken on your machine, map a different one (`"127.0.0.1:5433:5432"`).

**The sandbox path is separate.** Project containers started via
`docker-compose.sandbox.yml` (Docker-in-Docker, below) run in their own network
and can **not** see `db` — from their point of view the name does not exist.
Either run them the socket way, or start a database inside the sandbox for them.
Code running directly in the terminal container is unaffected.

Do not want a database? Delete the `db` service and the `db-data` volume from
`docker-compose.yml`.

### Connecting a BI tool (e.g. Metabase)

Metabase and most other BI tools ship a PostgreSQL driver already — there is
nothing to install. The only question is whether the tool can reach `db` on
the network.

**If the BI tool runs in the same Compose project** (its `docker-compose.yml`
has no `networks:` section of its own, so Compose joins it to this stack's
shared default network), it already reaches the database by service name, no
published port needed:

```
host db · port 5432
postgresql://ili:<POSTGRES_PASSWORD>@db:5432/ili
```

**If the BI tool runs in a different Compose project or a standalone
container**, it lives in its own network namespace and the name `db` resolves
nowhere there. Two options, same trade-off as any other cross-project setup:

- Join it to this stack's network. Compose names the default network
  `<project-directory>_default` (e.g. `ili_default` for a checkout in
  `~/ili`) — add it as `external: true` under the BI tool's `networks:` and
  point the tool's service at it. It then reaches `db` by name as above, no
  port has to be published.
- Or publish the port (uncomment the `ports:` block on the `db` service,
  above) and point the BI tool at the Docker/Podman **host's** address
  instead of `db` — from inside another container that is usually
  `host.docker.internal` or an equivalent gateway address, not `127.0.0.1`
  (`127.0.0.1` only works from the host machine itself, or from a BI tool
  that is not containerized). Check what your container runtime provides.

Either way: the port stays closed by default on purpose (see above) — opening
it or bridging networks is a decision you make, not something the stack does
for you.

## SSH into the terminal (optional, off by default)

The browser terminal is the everyday way in. For scripted access — `ssh host
'command'`, `scp`/`rsync`, an editor that works over SSH — there is a real SSH
login. It is off unless you switch it on, and it needs two things, so it cannot
happen by accident:

```bash
# 1) your PUBLIC key (never the private one) next to the compose files
mkdir -p ssh
cat ~/.ssh/id_ed25519.pub >> ssh/authorized_keys     # no key yet? ssh-keygen -t ed25519

# 2) start with the overlay
docker compose -f docker-compose.yml \
               -f docker-compose.terminal.yml \
               -f docker-compose.ssh.yml up -d

# 3) in you go
ssh -p 2222 ili@127.0.0.1
```

Registry install without a checkout? `docker run --rm -v "$PWD":/out
ghcr.io/toa1984/ili init` writes `docker-compose.ssh.yml` along with the others.

### What this login is — read this before you open it up

You get a shell in the terminal container: your project files, and passwordless
`sudo` (the container runs as root by design, see *How it is wired*). **With
`docker-compose.hostdocker.yml` in the same stack it also holds the Docker
socket, and that makes this login equivalent to root on the host machine.**

Whoever holds the matching **private** key holds those rights. Treat that key
like the machine's own password: no copy on a shared drive, no passphrase-less
key on a laptop you carry around.

That is why the port binds to `127.0.0.1` by default — reachable from the ili
machine itself and nowhere else. Everything else is switched off:

| | |
|---|---|
| Password login | off — the key is the only way in |
| Root login | off (`ili` is the only permitted user) |
| Port forwarding / tunnels | off — otherwise the login would tunnel into the whole compose network, `db:5432` included |
| Failed attempts per connection | 3, with a 20-second grace time |
| Host keys | in the `ssh-hostkeys` volume, generated on first start — so the fingerprint survives updates instead of triggering `REMOTE HOST IDENTIFICATION HAS CHANGED` |

Nothing is baked into the image: no key, no host key, no daemon that runs
without one.

### Working with the project files over SSH

One thing to know before the first attempt, because otherwise it looks like a
bug: you land as the user `ili`, but the project folders belong to the
container's root — that is deliberate, it is what keeps them writable for the
terminal and the automat. So `ili` alone cannot write into `/projects`:

```bash
$ ssh -p 2222 ili@127.0.0.1 'touch /projects/demo/x'
touch: cannot touch '/projects/demo/x': Permission denied
```

`ili` has passwordless `sudo`, so all three normal ways work — you just have to
say so:

```bash
# Interactive work. Do this rather than staying as `ili`: as root you are where
# /projects is writable AND where the Claude login lives (/root/.claude).
ssh -p 2222 -t ili@127.0.0.1 sudo -i

# Copy a folder in (and back out — just swap the two arguments)
rsync -a --no-owner --no-group -e 'ssh -p 2222' --rsync-path='sudo rsync' \
      ./my-project/ ili@127.0.0.1:/projects/my-project/

# A single file, if you would rather not use rsync
scp -P 2222 file.txt ili@127.0.0.1:/tmp/
ssh -p 2222 ili@127.0.0.1 'sudo mv /tmp/file.txt /projects/my-project/'
```

`--no-owner --no-group` matters on rootless Podman: with plain `-a`, rsync keeps
your workstation's uid, which maps to a nobody-ish id on the ili host — the files
land there but neither you nor the container can edit them comfortably
afterwards. Without the flags on the host they end up owned by the container's
root, which under rootless Podman *is* your own host user.

Running `claude` as `ili` will report that it is not signed in: the login lives
in root's home. `sudo -i` first.

### Reaching it from another machine

Only when you have decided you want that. `SSH_BIND=0.0.0.0` in `.env` puts the
port on your LAN:

```bash
SSH_PORT=2222
SSH_BIND=0.0.0.0
```

Into the open internet it does not belong — put it behind a VPN or a tunnel with
its own access control instead.

### It does not start

`docker compose logs terminal | grep ili-sshd` says why. The usual answers:

* `no SSH access: /etc/ssh/ili/authorized_keys does not exist` — the file is
  missing. It goes into `ssh/authorized_keys` **next to the compose files**, and
  the stack has to be restarted afterwards.
* `holds no public key line` — the file exists but has no key in it (a comment
  or an empty line does not count). A public key line starts with `ssh-ed25519`
  or `ssh-rsa`.
* `Permission denied (publickey)` on the client although the daemon is running —
  you copied the private key instead of the `.pub` file, or you are connecting
  as a different user. The user is `ili`, always.

## Running project containers (Docker / Podman)

From within a project terminal, you can build and run Docker containers for your own projects.
This requires either a **Sandbox** (Docker-in-Docker, isolated) or **Socket mount** (direct host access).

The settings page (⚙️ KI-Settings → 🐳 Docker) shows which of the two is active and
whether the engine answers, prints the matching `.env` lines, and offers a third,
restart-free option: a **remote daemon over TCP** (`DOCKER_HOST`, e.g. Docker Desktop's
`tcp://host.docker.internal:2375`; TLS on 2376 for anything beyond localhost). The
choice is stored in `docker_config.json` next to `ai_config.json`; the terminal picks it
up when Claude starts, the automat before every run. As soon as an engine is reachable,
`/projects/CLAUDE.md` is generated with the rules Claude needs (host paths for bind
mounts, port range, `--restart unless-stopped`) — a hand-written file there is left alone.
Mode *off* is advisory: it removes those instructions and injects no `DOCKER_*`, but a
socket mounted by an overlay stays reachable for anyone in the terminal — unmount it
(drop the overlay from `COMPOSE_FILE`) if that matters.

### Option 1: Sandbox (Docker-in-Docker, recommended)

The sandbox is a separate Docker daemon inside ili, completely isolated from your host.
**Use this if:**
- You want experiments to never break the host
- You're on Docker (Desktop Mac/Windows or Linux Docker)
- You want to clean up later: just delete the sandbox volume and nothing is left on the host

**Start with the sandbox:**
```bash
docker compose -f docker-compose.yml -f docker-compose.terminal.yml \
               -f docker-compose.sandbox.yml up -d --build
```

**Or set `COMPOSE_FILE` once in `.env`:**
```ini
COMPOSE_FILE=docker-compose.yml:docker-compose.terminal.yml:docker-compose.sandbox.yml
```

Then `docker compose up -d` will always include all three files.

**Inside the terminal:**
```bash
docker build -t my-app ./projects/board-name
docker run --name my-app -v /projects/board-name:/app:z -p 8100:3000 my-app
```

**Ports:** Bind your project container to a port between **8100 and 8119** and reach it
at `http://<host>:<port>` — nothing else to configure.

Behind that: the sandbox publishes no port at all. A small `gateway` container
(`nginx:alpine`) reserves the range on the host and forwards it 1:1 into the sandbox
(host port N → `sandbox:N`, plain TCP, so WebSockets and databases pass through
unchanged). Keeping the reservation in its own container is what later allows name
based routing or an access check in front of project containers, without touching the
Docker daemon. Config: `deploy/gateway/nginx.conf` plus `deploy/gateway/10-generate-streams.sh`,
which writes one nginx block per port at container start (nginx' `listen` has no port
ranges). Widen the range with `SANDBOX_PORT_FROM` / `SANDBOX_PORT_TO` in `.env` — every
port costs one nginx block and one host mapping, upper limit 200.

**Surviving a restart:** the sandbox keeps images and containers in its own volume, but a
stopped container stays stopped. Start project containers with `--restart unless-stopped`
if they should come back up with the sandbox.

**Cleanup:** `docker system prune` runs inside the sandbox, never touching the host.

**Limitation:** the sandbox needs `privileged: true`. That is unproblematic on Docker; on
rootless Podman it depends on the host — it *did* run on ours (cgroups v2, Podman 4.9),
but if the daemon refuses to start, use **Option 2** instead (socket mount), which needs
no privileges.

### Option 2: Socket mount (direct host Docker / Podman)

Mount the host's Docker socket directly into the terminal. Project containers then run
as regular host containers.

**⚠️ Security:** The Docker socket is **equivalent to root access** to your entire machine.
The terminal is already a full browser shell (behind a password), so this only shifts
the boundary to the whole system. **Only use this on a machine dedicated to ili.**

**Start with socket mount:**
```bash
# Docker
docker compose -f docker-compose.yml -f docker-compose.terminal.yml \
               -f docker-compose.hostdocker.yml up -d

# Podman — start the socket service first, it is off by default
systemctl --user enable --now podman.socket
podman-compose -f docker-compose.yml -f docker-compose.terminal.yml \
               -f docker-compose.hostdocker.yml up -d
```

**Configure socket and project path** (in `.env`):
```ini
# Docker
DOCKER_SOCKET=/var/run/docker.sock
# Podman rootless — run `id -u` for your uid; rootful: /run/podman/podman.sock
# DOCKER_SOCKET=/run/user/1000/podman/podman.sock

# Directory that HOLDS the projects folder — without a trailing /projects,
# the compose file appends it
PROJECTS_HOST_DIR=/home/you/ili
```

`DOCKER_SOCKET` is mounted at the same path inside the container as outside, and
`DOCKER_HOST` points at it. Project containers are started by the **host** daemon, so
their bind mounts are host paths — that is what `PROJECTS_HOST_DIR` is for.

**⚠️ podman-compose 1.0.3** (Debian 12) does not interpolate `${VAR}` at all. Check with
`podman-compose --version`; on that version write the paths straight into
`docker-compose.hostdocker.yml`.

**Inside the terminal:**
```bash
# The build context is read by the CLI, so the container path is correct here
docker build -t my-app ./projects/board-name

# The bind mount is resolved by the HOST daemon — it needs a host path, not the
# /projects path inside the terminal. Using /projects/... here would silently give
# you an empty auto-created directory instead of your project.
docker run --name my-app -v "$PROJECTS_HOST_DIR/projects/board-name:/app:z" \
           -p 8100:3000 my-app
```

`PROJECTS_HOST_DIR` is passed into the terminal by the overlay, so it is available
as a shell variable.

**Ports:** Use 8100–8119 by convention (same range as the sandbox). There is no gateway
here — project containers are plain host containers, so `-p 8100:3000` already publishes
a host port. Nothing reserves the range for you, so conflicts with other services on the
host are possible.

**Cleanup:** `docker system prune` cleans up the host's Docker daemon. Be careful.

**Good for:** Podman, or if you specifically want your project containers to be normal
host containers with direct host network access.

## How it is wired

```
Browser ──► web (nginx, port 80)
              │  /projterm/     Basic auth ──► sets cookie ili_term
              │  /projterm/ws   cookie required
              ▼
           terminal (ttyd, port 7690, no published port)
              └─ ili-term <board> ──► tmux session proj-<board>
                                        └─ ili-claude ──► claude
```

- **One ttyd instance serves every board.** The board id travels as a URL query
  (`/projterm/?arg=<board>`, ttyd `-a`) into `ili-term`, which resolves the tmux
  session and the working directory.
- **`deploy/nginx-setup.sh`** runs before nginx and writes the route. If
  the terminal service is not running, it writes a 503 stub that tells you how to
  enable it — so nginx always starts.
- **Authentication sits in nginx, not in ttyd.** ttyd has no published port and is
  only reachable inside the compose network. The WebSocket path is guarded by a
  cookie instead of Basic auth, because Safari does not send Basic credentials
  during a WebSocket handshake — with Basic auth on the WS path, the terminal
  would load in Safari but stay dead.
- **No HTTPS required.** The cookie is deliberately not marked `Secure`, so the
  terminal also works over plain `http://<lan-ip>` in a home network. If you put
  a TLS proxy in front, nothing changes.
- **`html/ili-terminal-login.html`** is the body of the 401. Browsers suppress the
  Basic-auth dialog for embedded frames, so the board page would otherwise show
  nginx' raw error text; the page offers a "sign in in a new tab" button instead.
  Status and `WWW-Authenticate` stay untouched, so a direct visit still prompts.
  The sign-in link carries the board over (`/projterm/?arg=<board>`, read from
  `location.search` — the 401 body is served under the iframe's own URL). Before
  0.1.16 it pointed at a bare `/projterm/`, so the sign-in tab opened the generic
  `home` session instead of the board's — the "wrong terminal" report of 2026-09-07.

## Do not publish the ttyd port

The compose file gives the `terminal` service `expose` only, never `ports`.
Adding a `ports:` entry would make an unauthenticated shell reachable on your
network. If you need direct access, put your own authentication in front of it.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/projterm/` returns 503 | either the terminal service is not running, or `web` was started before it existed — the route is decided once, when `web` starts | start it: `docker compose -f docker-compose.yml -f docker-compose.terminal.yml up -d`, and if the stack was already running, add `restart web` |
| Board page shows "The project terminal needs a login" | browsers do not show the Basic-auth dialog inside an iframe | use the "Sign in in a new tab" button on that page, then "Reload terminal" |
| Changed `TERMINAL_PASSWORD` has no effect | the route is written once, when the web container starts | `docker compose up -d web` (or `restart web`) |
| Terminal loads, no input accepted, browser console shows a failed WebSocket | cookie missing — the HTML route was not loaded first, or cookies are blocked for the site | reload `/projterm/` directly, then the board |
| `web` container restarts in a loop, log says `host not found in upstream` | nginx resolves its upstreams once at startup and the other container was not registered yet | `deploy/nginx-setup.sh` waits for both (`API_WAIT`, `TERMINAL_WAIT` in seconds); on Podman check that `netavark`/`aardvark-dns` are installed, otherwise there is no container DNS at all |
| Dashboard empty, log says `api:8798 did not answer` | Podman without container DNS (Debian 12 default) | `sudo apt install netavark aardvark-dns`, then `docker compose down && docker compose up -d` |
| Claude asks to sign in on every restart | the `terminal-home` volume was removed | keep the volume, or use `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY` |
| Terminal opens in the wrong folder | no board file for that id, so it fell back to a generic session | check `docker compose logs terminal` |

Debug logs: `docker compose logs -f terminal` (session and directory decisions)
and `docker compose logs web | grep ili-setup` (route and credentials).
