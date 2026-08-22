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
[ili-setup]    user:     ili
[ili-setup]    password: 7Kq2mXbA91LpZr4t
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

**Pick whichever fits you — all three are optional, the Kanban core works without
any of them:**

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
