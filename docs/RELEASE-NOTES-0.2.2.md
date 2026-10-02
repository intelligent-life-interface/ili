## ili 0.2.2

Projects can now come from GitHub, the project terminal no longer needs a manual
restart to appear, and the terminal password stops changing behind your back.

### Import repositories as projects

A new page (GitHub-Import in the navigation) connects a GitHub account, lists
its repositories — private ones too, with a token — and turns the selected ones
into projects: a board, a project folder, and the repository cloned into it.

An imported project is a real git repository, so the AI working in its terminal
can commit, branch and diff from the first minute. That also closes the older
complaint that freshly created project folders were not under version control.

Authentication is a token you create yourself (`ILI_GITHUB_TOKEN` in `.env`).
Public repositories import without any token at all; a token is needed for
private ones and to look up your own profile. The device-flow login used for bug
reports is deliberately not reused here: its GitHub App is limited to issues on
a single repository, and widening it would have meant asking for write access to
every public repository you own.

The clone keeps whatever the project folder already contains, so the generated
CLAUDE.md and TAGS.md survive, and the stored remote never contains your token.

Not included yet: syncing an imported project back and forth. Pulling and
pushing needs conflict handling and an answer to what should happen when the
automat commits in the project folder while you push from another machine. The
endpoint answers 501 saying exactly that, rather than failing in a way that
looks like a defect.

### The project terminal no longer needs a restart

Adding the terminal to a running stack used to leave `/projterm/` answering 503
until the web container was restarted, because nginx had resolved the upstream
at startup — when the terminal did not exist yet. It now re-resolves, so the
route starts working on its own.

### The terminal password stays put

The password guarding the terminal was generated in the web container on every
start, although it guards the terminal: restarting web rolled a new one, and it
only ever existed in a log line. `init` now writes a generated password into the
`.env` it creates, where it survives restarts and where you can change it.

### Smaller changes

- The board model selector offers myAI as an option.
- The archive view remembers whether it was open.
- The README shows the project logo.
- A decision card with an empty question no longer renders a blank entry.
- Mobile Safari no longer serves a stale tab script from cache.

### Upgrading

`docker compose pull && docker compose up -d`, then rerun `init` to pick up the
new compose files — your `.env` is never overwritten. The api image grew by
roughly 100 MB because it now carries `git`, which the import needs.
