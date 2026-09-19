"""Tests for deploy/terminal/ili-mcp-docker.py — the MCP server the Settings →
Docker → MCP switch registers in the terminal (claude mcp add --scope user).

Loaded via importlib (filename has dashes, not a valid module name) — same
pattern claude_cli_bridge.py itself uses for loop_logger.py. `docker` is never
actually invoked: subprocess.run is monkeypatched everywhere.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parent.parent / "deploy" / "terminal" / "ili-mcp-docker.py"
_spec = importlib.util.spec_from_file_location("ili_mcp_docker", _SCRIPT)
mcp_docker = importlib.util.module_from_spec(_spec)
sys.modules["ili_mcp_docker"] = mcp_docker
_spec.loader.exec_module(mcp_docker)


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_list_containers_parses_ndjson(monkeypatch):
    lines = (
        '{"ID":"abc123def456","Names":"ili-api","Image":"ili:latest",'
        '"Status":"Up 2 hours","Ports":"8798/tcp","CreatedAt":"2026-09-18"}\n'
        '{"ID":"789xyz000111","Names":"ili-terminal","Image":"ili-terminal:latest",'
        '"Status":"Exited (0) 1 hour ago","Ports":"","CreatedAt":"2026-09-17"}\n'
    )
    monkeypatch.setattr(mcp_docker.subprocess, "run",
                        lambda *a, **k: _Result(0, lines, ""))
    out = mcp_docker.DockerTools().list_containers({})
    assert len(out["containers"]) == 2
    assert out["containers"][0]["id"] == "abc123def456"
    assert out["containers"][0]["names"] == "ili-api"
    assert out["containers"][1]["status"] == "Exited (0) 1 hour ago"


def test_list_containers_all_flag_adds_dash_a(monkeypatch):
    seen = {}

    def fake_run(cmd, **k):
        seen["cmd"] = cmd
        return _Result(0, "", "")
    monkeypatch.setattr(mcp_docker.subprocess, "run", fake_run)
    mcp_docker.DockerTools().list_containers({"all": True})
    assert "-a" in seen["cmd"]
    seen.clear()
    mcp_docker.DockerTools().list_containers({"all": False})
    assert "-a" not in seen["cmd"]


def test_container_logs_requires_container():
    with pytest.raises(ValueError, match="Missing parameter: container"):
        mcp_docker.DockerTools().container_logs({})


def test_container_logs_combines_streams(monkeypatch):
    monkeypatch.setattr(mcp_docker.subprocess, "run",
                        lambda *a, **k: _Result(0, "stdout line\n", "stderr line\n"))
    out = mcp_docker.DockerTools().container_logs({"container": "ili-api", "tail": 50})
    assert "stdout line" in out["logs"] and "stderr line" in out["logs"]
    assert out["tail"] == 50


def test_container_logs_failure_raises(monkeypatch):
    monkeypatch.setattr(mcp_docker.subprocess, "run",
                        lambda *a, **k: _Result(1, "", "no such container"))
    with pytest.raises(RuntimeError, match="no such container"):
        mcp_docker.DockerTools().container_logs({"container": "ghost"})


def test_container_inspect_trims_fields(monkeypatch):
    raw = [{
        "Id": "abc123def456789",
        "Name": "/ili-api",
        "State": {"Status": "running", "Running": True, "ExitCode": 0, "StartedAt": "2026-09-18T10:00:00Z"},
        "Config": {"Image": "ili:latest"},
        "NetworkSettings": {"Ports": {"8798/tcp": [{"HostPort": "8798"}]}},
        "Mounts": [{"Source": "/host/projects", "Destination": "/projects"}],
        "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}},
    }]
    import json
    monkeypatch.setattr(mcp_docker.subprocess, "run",
                        lambda *a, **k: _Result(0, json.dumps(raw), ""))
    out = mcp_docker.DockerTools().container_inspect({"container": "ili-api"})
    assert out["id"] == "abc123def456"
    assert out["name"] == "ili-api"
    assert out["state"]["status"] == "running"
    assert out["mounts"] == [{"source": "/host/projects", "destination": "/projects"}]
    assert out["restart_policy"] == {"Name": "unless-stopped"}


def test_container_inspect_not_found(monkeypatch):
    monkeypatch.setattr(mcp_docker.subprocess, "run", lambda *a, **k: _Result(0, "[]", ""))
    with pytest.raises(RuntimeError, match="Container not found"):
        mcp_docker.DockerTools().container_inspect({"container": "ghost"})


@pytest.mark.parametrize("method,args", [
    ("container_start", ["start"]),
    ("container_stop", ["stop"]),
    ("container_restart", ["restart"]),
])
def test_lifecycle_actions_call_docker(monkeypatch, method, args):
    seen = {}

    def fake_run(cmd, **k):
        seen["cmd"] = cmd
        return _Result(0, "", "")
    monkeypatch.setattr(mcp_docker.subprocess, "run", fake_run)
    result = getattr(mcp_docker.DockerTools(), method)({"container": "ili-api"})
    assert seen["cmd"][:2] == ["docker", args[0]]
    assert "ili-api" in seen["cmd"]
    assert "ili-api" in result["message"]


def test_container_remove_force_flag(monkeypatch):
    seen = {}

    def fake_run(cmd, **k):
        seen["cmd"] = cmd
        return _Result(0, "", "")
    monkeypatch.setattr(mcp_docker.subprocess, "run", fake_run)
    mcp_docker.DockerTools().container_remove({"container": "ili-api", "force": True})
    assert seen["cmd"] == ["docker", "rm", "-f", "ili-api"]
    mcp_docker.DockerTools().container_remove({"container": "ili-api"})
    assert seen["cmd"] == ["docker", "rm", "ili-api"]


def test_call_tool_unknown_name_is_error_not_exception():
    result = mcp_docker.MCPServer().handle_call_tool({"name": "delete_everything", "arguments": {}})
    assert result["isError"] is True
    assert "unknown tool" in result["content"][0]["text"]


def test_call_tool_wraps_runtime_error(monkeypatch):
    monkeypatch.setattr(mcp_docker.subprocess, "run",
                        lambda *a, **k: _Result(1, "", "boom"))
    result = mcp_docker.MCPServer().handle_call_tool(
        {"name": "container_stop", "arguments": {"container": "x"}})
    assert result["isError"] is True
    assert "boom" in result["content"][0]["text"]


def test_tools_list_matches_warning_scope():
    """The Settings → Docker warning says the AI can start/stop/remove containers —
    the tool set must not silently grow beyond list/logs/inspect/lifecycle/remove."""
    names = {t["name"] for t in mcp_docker.TOOLS}
    assert names == {"list_containers", "container_logs", "container_inspect",
                     "container_start", "container_stop", "container_restart",
                     "container_remove"}
    assert "exec" not in " ".join(names)  # no exec tool — Bash+docker-cli already cover it
