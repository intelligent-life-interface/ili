# ili Kanban MCP Server

MCP server that connects Claude Desktop, Claude Code, Cursor, and other
MCP-compatible clients to an **ili** Kanban dashboard. Talks stdio JSON-RPC
to the client and forwards tool calls to your ili instance's REST API
(default port `8798`).

Requires a running ili dashboard — see the main
[QUICKSTART.md](../QUICKSTART.md) if you do not have one yet.

## Tools

| Tool | Purpose |
|---|---|
| `list_boards` | Enumerate all boards (optional `parent` filter) |
| `get_board` | Fetch a board with all columns and cards |
| `get_card` | Fetch a single card by ID |
| `create_card` | Add a new card to a column |
| `move_card` | Move a card between columns or reorder it |
| `update_card` | Update card fields (title, description, owner, labels, status) |
| `add_note` | Append a timestamped note to a card |

## Installation

### Option A: prebuilt image (recommended)

```bash
docker pull ghcr.io/toa1984/ili-mcp:latest
# or: podman pull ghcr.io/toa1984/ili-mcp:latest
```

Public image, no login needed.

### Option B: build locally

```bash
git clone https://github.com/Toa1984/ili-public.git
cd ili-public/release-container/mcp
docker build -t ili-mcp:latest -f Containerfile .
# or: podman build -t ili-mcp:latest -f Containerfile .
```

## Configuring your MCP client

The server reads the dashboard's REST API address from the `DASHBOARD_URL`
environment variable. If ili runs on the **same machine** as your client,
point it at the host from inside the container:

- **Docker Desktop** (macOS/Windows) and recent **Docker Engine** (Linux, with
  `--add-host=host.docker.internal:host-gateway`): `http://host.docker.internal:8798`
- **Podman** (rootless): `http://host.containers.internal:8798` — resolves
  automatically, no extra flag needed.
- **ili running elsewhere on your LAN**: use that machine's address, e.g.
  `http://192.168.1.50:8798` or `http://ili.local:8798`.

### Claude Desktop

Edit `claude_desktop_config.json` (Settings → Developer → Edit Config) and
add an entry under `mcpServers`:

```json
{
  "mcpServers": {
    "ili-kanban": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "DASHBOARD_URL=http://host.docker.internal:8798",
        "ghcr.io/toa1984/ili-mcp:latest"
      ]
    }
  }
}
```

Podman users: replace `docker` with `podman` and the env value with
`http://host.containers.internal:8798`. Restart Claude Desktop afterwards.

### Claude Code (CLI)

`-e` on `claude mcp add` sets the variable for the `docker`/`podman` process
itself, not inside the container — put `DASHBOARD_URL` into the container's
own `-e` flag instead:

```bash
claude mcp add ili-kanban \
  -- docker run --rm -i -e DASHBOARD_URL=http://host.docker.internal:8798 \
  ghcr.io/toa1984/ili-mcp:latest
```

Use `--scope user` to make it available in every project, not just the
current one.

### Cursor

Cursor uses the same `mcpServers` JSON shape as Claude Desktop — add it to
`~/.cursor/mcp.json` (or the project-local `.cursor/mcp.json`) with the same
entry shown above.

### Docker MCP Toolkit / Gateway

Once the server is listed in the official
[docker/mcp-registry](https://github.com/docker/mcp-registry) catalog, it
shows up in Docker Desktop's MCP Toolkit and can be enabled with one click,
or run headless via `docker mcp gateway run`. Until then, use Option A/B
above with any client that speaks stdio MCP directly.

## Verifying it works

A quick manual check without any GUI client — send raw JSON-RPC over stdin:

```bash
printf '%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_boards","arguments":{}}}' \
| docker run --rm -i -e DASHBOARD_URL=http://host.docker.internal:8798 ghcr.io/toa1984/ili-mcp:latest
```

A healthy response to the second line is a JSON board list, not an
`isError: true` entry. If you get a connection error, `DASHBOARD_URL` is
pointing at the wrong host/port (see above) or the ili dashboard is not
running.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Connection error: Connection refused` | `DASHBOARD_URL` still points at `127.0.0.1` (the container itself, not your host) | Set `DASHBOARD_URL` explicitly — see "Configuring your MCP client" above |
| `Connection error: Name or service not known` | Wrong host alias for your container engine (mixed up `host.docker.internal` / `host.containers.internal`) | Match the alias to your engine, see table above |
| `HTTP 404: Board '...' nicht gefunden` | Wrong `board_id` | Call `list_boards` first to get valid IDs |
| Tool call returns `Missing parameter: ...` even though you passed it | Old image built before the `arguments`-field fix | Rebuild/pull the latest image |
| Nothing happens, client shows no tools | `DASHBOARD_URL` unreachable, or ili dashboard container down | Check `docker logs`/`podman logs` on the ili `api` container |

Debug logs (stderr, not part of the MCP stdio protocol) show every request
received and every dashboard API call made — pipe stderr to a file when
diagnosing:

```bash
docker run --rm -i -e DASHBOARD_URL=... ghcr.io/toa1984/ili-mcp:latest 2>mcp-debug.log
```

## License

MIT — see [LICENSE](LICENSE). The MCP server is an independent stdio client
that only talks to ili's REST API over HTTP; it does not embed ili's own
AGPL-3.0-licensed code.
