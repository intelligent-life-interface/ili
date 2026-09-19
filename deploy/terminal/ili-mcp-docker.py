#!/usr/bin/env python3
"""ili-mcp-docker — stdio MCP server that lets Claude Code control containers on
whatever engine `docker` in THIS terminal already points at (DOCKER_HOST, set by
ili-claude.sh from Settings → Docker). No extra dependency: the `docker` CLI is
already part of the terminal image (Containerfile.terminal), this script only
wraps it the same way the settings-page guide tells the AI to use it by hand.

Registered via `claude mcp add --scope user ili-docker -- python3
/usr/local/bin/ili-mcp-docker` (see claude_cli_bridge.py, POST /mcp/docker/setup).
User scope means one registration covers every board's terminal session.

Deliberately NOT a wrapper around Podman or the Docker MCP Toolkit Gateway: Podman
is home-lab-specific (this image ships to arbitrary Docker hosts), and the Gateway
is a 40+ MB catalog/plugin system for THIRD-PARTY MCP servers — total overkill for
"let the AI see and manage containers", and it spawns containers of its own.

Usage: ili-mcp-docker
       → reads JSON-RPC messages from stdin, writes responses to stdout (MCP stdio)
       → all logging goes to stderr (stdout is the protocol channel)

Tools exposed (mirrors the docker CLI, not a home-stack automation): list_containers,
container_logs, container_inspect, container_start, container_stop, container_restart,
container_remove. No `exec` — Claude already has Bash + docker-cli for that; adding it
here would only duplicate it without any structural benefit.
"""
import json
import logging
import subprocess
import sys
from typing import Any, Optional

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [mcp-docker] %(message)s",
)
log = logging.getLogger("mcp-docker")

_TIMEOUT_S = 20


def _docker(args: list[str], timeout: int = _TIMEOUT_S) -> tuple[int, str, str]:
    """Run `docker <args>` against DOCKER_HOST inherited from this process' own
    environment (set by ili-claude.sh before `claude` starts) — never overridden
    here, so a later Settings → Docker change takes effect on the next terminal
    restart exactly like the plain CLI already does."""
    try:
        r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", "docker CLI not found in this container"
    except subprocess.TimeoutExpired:
        return 124, "", f"docker {' '.join(args)} timed out after {timeout}s"


def _require(container: str) -> str:
    container = (container or "").strip()
    if not container:
        raise ValueError("Missing parameter: container")
    return container


class DockerTools:
    """One method per MCP tool — thin wrappers around `docker`."""

    def list_containers(self, params: dict) -> Any:
        show_all = params.get("all", True)
        args = ["ps", "--format", "{{json .}}"]
        if show_all:
            args.insert(1, "-a")
        rc, out, err = _docker(args)
        if rc != 0:
            raise RuntimeError(f"docker ps failed: {err.strip()}")
        containers = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                c = json.loads(line)
            except json.JSONDecodeError:
                continue
            containers.append({
                "id": c.get("ID", "")[:12],
                "names": c.get("Names", ""),
                "image": c.get("Image", ""),
                "status": c.get("Status", ""),
                "ports": c.get("Ports", ""),
                "created": c.get("CreatedAt", ""),
            })
        return {"containers": containers}

    def container_logs(self, params: dict) -> Any:
        container = _require(params.get("container", ""))
        tail = int(params.get("tail", 100) or 100)
        tail = max(1, min(tail, 2000))
        rc, out, err = _docker(["logs", "--tail", str(tail), container])
        if rc != 0:
            raise RuntimeError(f"docker logs failed for {container}: {err.strip()}")
        return {"container": container, "tail": tail, "logs": (out + err) or "(empty)"}

    def container_inspect(self, params: dict) -> Any:
        container = _require(params.get("container", ""))
        rc, out, err = _docker(["inspect", container])
        if rc != 0:
            raise RuntimeError(f"docker inspect failed for {container}: {err.strip()}")
        try:
            data = json.loads(out)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid docker inspect output: {e}") from e
        if not data:
            raise RuntimeError(f"Container not found: {container}")
        d = data[0]
        state = d.get("State", {})
        cfg = d.get("Config", {})
        return {
            "id": d.get("Id", "")[:12],
            "name": (d.get("Name") or "").lstrip("/"),
            "image": cfg.get("Image", ""),
            "state": {"status": state.get("Status"), "running": state.get("Running"),
                      "exit_code": state.get("ExitCode"), "started_at": state.get("StartedAt")},
            "ports": d.get("NetworkSettings", {}).get("Ports", {}),
            "mounts": [{"source": m.get("Source"), "destination": m.get("Destination")}
                       for m in d.get("Mounts", [])],
            "restart_policy": d.get("HostConfig", {}).get("RestartPolicy", {}),
        }

    def container_start(self, params: dict) -> Any:
        container = _require(params.get("container", ""))
        rc, out, err = _docker(["start", container])
        if rc != 0:
            raise RuntimeError(f"docker start failed for {container}: {err.strip()}")
        return {"container": container, "message": f"Started {container}"}

    def container_stop(self, params: dict) -> Any:
        container = _require(params.get("container", ""))
        rc, out, err = _docker(["stop", container], timeout=_TIMEOUT_S + 15)
        if rc != 0:
            raise RuntimeError(f"docker stop failed for {container}: {err.strip()}")
        return {"container": container, "message": f"Stopped {container}"}

    def container_restart(self, params: dict) -> Any:
        container = _require(params.get("container", ""))
        rc, out, err = _docker(["restart", container], timeout=_TIMEOUT_S + 15)
        if rc != 0:
            raise RuntimeError(f"docker restart failed for {container}: {err.strip()}")
        return {"container": container, "message": f"Restarted {container}"}

    def container_remove(self, params: dict) -> Any:
        container = _require(params.get("container", ""))
        force = bool(params.get("force", False))
        args = ["rm"] + (["-f"] if force else []) + [container]
        rc, out, err = _docker(args)
        if rc != 0:
            raise RuntimeError(f"docker rm failed for {container}: {err.strip()}")
        return {"container": container, "message": f"Removed {container}"}


TOOLS = [
    {"name": "list_containers", "description": "List containers (running + stopped) on the "
     "engine this terminal's DOCKER_HOST points at",
     "inputSchema": {"type": "object", "properties": {
         "all": {"type": "boolean", "default": True, "description": "Include stopped containers"}}}},
    {"name": "container_logs", "description": "Fetch recent logs of a container",
     "inputSchema": {"type": "object", "properties": {
         "container": {"type": "string"}, "tail": {"type": "integer", "default": 100}},
         "required": ["container"]}},
    {"name": "container_inspect", "description": "Detailed metadata for a container "
     "(state, image, ports, mounts, restart policy)",
     "inputSchema": {"type": "object", "properties": {"container": {"type": "string"}},
                      "required": ["container"]}},
    {"name": "container_start", "description": "Start a stopped container",
     "inputSchema": {"type": "object", "properties": {"container": {"type": "string"}},
                      "required": ["container"]}},
    {"name": "container_stop", "description": "Stop a running container",
     "inputSchema": {"type": "object", "properties": {"container": {"type": "string"}},
                      "required": ["container"]}},
    {"name": "container_restart", "description": "Restart a container",
     "inputSchema": {"type": "object", "properties": {"container": {"type": "string"}},
                      "required": ["container"]}},
    {"name": "container_remove", "description": "Remove a container (irreversible)",
     "inputSchema": {"type": "object", "properties": {
         "container": {"type": "string"}, "force": {"type": "boolean", "default": False,
         "description": "Remove even if running (docker rm -f)"}},
         "required": ["container"]}},
]


class MCPServer:
    """Minimal MCP server implementation (stdio JSON-RPC) — same scaffold as
    mcp/server.py (the ili-Kanban MCP server), adapted to Docker tool calls."""

    def __init__(self):
        self.request_id: Optional[Any] = None
        self.protocol_version = "2024-11-05"
        self.tools = DockerTools()

    def _handlers(self) -> dict:
        return {t["name"]: getattr(self.tools, t["name"]) for t in TOOLS}

    def handle_call_tool(self, params: dict) -> Any:
        name = params.get("name")
        args = params.get("arguments", {}) or {}
        handlers = self._handlers()
        if name not in handlers:
            return {"content": [{"type": "text", "text": f"Error: unknown tool {name}"}],
                    "isError": True}
        try:
            result = handlers[name](args)
            return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                    "isError": False}
        except Exception as e:
            log.error("tool %s failed: %s", name, e)
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

    def send_response(self, result: Any = None, error: Optional[dict] = None) -> None:
        response = {"jsonrpc": "2.0"}
        if self.request_id is not None:
            response["id"] = self.request_id
        response["error" if error else "result"] = error if error else result
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

    def run(self) -> None:
        log.info("Starting ili-mcp-docker (stdio mode)")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self.send_response(error={"code": -32700, "message": "Parse error"})
                continue
            method = msg.get("method")
            if "id" not in msg:
                log.debug("notification: %s", method)
                continue
            self.request_id = msg.get("id")
            try:
                if method == "initialize":
                    self.send_response(result={
                        "protocolVersion": self.protocol_version,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "ili-docker", "version": "1.0.0"},
                    })
                elif method == "tools/list":
                    self.send_response(result={"tools": TOOLS})
                elif method == "tools/call":
                    self.send_response(result=self.handle_call_tool(msg.get("params", {})))
                else:
                    self.send_response(error={"code": -32601, "message": f"Method not found: {method}"})
            except Exception as e:
                log.error("unhandled error: %s", e, exc_info=True)
                self.send_response(error={"code": -32603, "message": str(e)})


if __name__ == "__main__":
    try:
        MCPServer().run()
    except KeyboardInterrupt:
        sys.exit(0)
