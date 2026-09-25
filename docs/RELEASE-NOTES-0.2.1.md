## ili 0.2.1

A field test of 0.2.0 on a Docker Desktop installation found that "create a
container" does not work out of the box: ili reported "no engine" while the
engine was answering, and told the AI the opposite. This release fixes that.

### `auto` now finds Docker Desktop

In mode `auto` ili only looked at what a compose overlay had put into the
environment — a mounted socket or the sandbox's `DOCKER_HOST`. A Docker Desktop
installation without such an overlay has neither, so ili reported no engine,
although `tcp://host.docker.internal:2375` was answering right there. That name
is not the container itself: Docker Desktop resolves it to the host, and behind
it runs the very engine the `ili-*` containers run on.

`auto` now probes the overlay first and, only if that fails, the Desktop
endpoint (`DOCKER_DESKTOP_HOSTS`, empty disables it). A hit is remembered as
`detected_host` and exported like `remote`. The overlay keeps precedence: a
compose overlay is a deliberate choice and an older detection must not override
a socket set up later. On Linux without Docker Desktop the name does not
resolve, the probe fails immediately and nothing changes.

Note that port 2375 is unencrypted. Docker Desktop publishes it locally only;
remote engines still belong in mode `remote` with TLS on 2376.

### The AI is told the truth when there is no engine

`/api/docker/claude-md` answered 503 whenever no engine was reachable, so
`ili-docker-guide.sh` (which fetches with `curl -fsS`) treated it as "api
unreachable", kept the previous file and only added a staleness note. The
honest "No container engine is available in this terminal" text that 0.2.0
introduced was dead code — the AI kept reading "no setup needed" from a guide
written days earlier. The route now returns that text with 200; 503 is left for
the case where the status genuinely cannot be determined.

### Host path for bind mounts is found automatically

Binding a project folder into a container needs a host path, and ili took it
only from `PROJECTS_HOST_DIR` in `.env`, which meant editing a file and
restarting. The engine already knows the answer, so when the variable is empty
ili now reads the source of its own `/projects` mount via `docker inspect`.

### New project folders are Git repos from the start

A newly created project folder under `/projects/<board>` was plain files —
nothing versioned the work an AI session did in there. Both places that
actually write to a project folder now call `git init` on it (idempotent,
`git` missing or the call failing is only logged, never breaks the terminal
connection or the automat run): the board terminal (`ili-term.sh`, on every
connection, so it also covers folders the api container already created
before anyone opened a terminal) and the kanban automat (`worker.py`, so a
card worked without a human ever opening that board's terminal is covered
too). The api container itself was deliberately left without `git` — it has
no need for one and adding it would pull ~50 MB of git+perl into an image
that just dropped `pip` to shrink its own scanner surface. If no `user.name`
is configured anywhere, ili sets one locally on the repo (`ili`/`ili@localhost`
— a neutral placeholder, since this runs in every third-party installation, not
just here) so the first `git commit` in a fresh install does not fail with
"Please tell me who you are". Existing project folders are left untouched.

### Upgrading

`docker compose pull && docker compose up -d`. The terminal changes take effect
with the rebuilt terminal image, so pull all three images.
