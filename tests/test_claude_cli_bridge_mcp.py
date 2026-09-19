"""Tests for the _mcp_docker_* helpers in deploy/terminal/claude_cli_bridge.py —
the terminal-side half of the Settings → Docker → MCP switch.

Loaded via importlib (module lives outside app/, same pattern the bridge itself
uses for loop_logger.py). subprocess.run and os.path.exists are monkeypatched —
no real `claude` binary or docker engine needed.
"""
import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).parent.parent / "deploy" / "terminal" / "claude_cli_bridge.py"
_spec = importlib.util.spec_from_file_location("claude_cli_bridge", _SCRIPT)
bridge = importlib.util.module_from_spec(_spec)
sys.modules["claude_cli_bridge"] = bridge
_spec.loader.exec_module(bridge)


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_status_script_missing_skips_configured_check(monkeypatch):
    monkeypatch.setattr(bridge.os.path, "exists", lambda p: False)
    monkeypatch.setattr(bridge.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run claude")))
    assert bridge._mcp_docker_status() == {"script_present": False, "configured": False}


def test_status_configured(monkeypatch):
    monkeypatch.setattr(bridge.os.path, "exists", lambda p: True)
    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k: _Result(0))
    assert bridge._mcp_docker_status() == {"script_present": True, "configured": True}


def test_status_not_configured(monkeypatch):
    monkeypatch.setattr(bridge.os.path, "exists", lambda p: True)
    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k: _Result(1))
    assert bridge._mcp_docker_status() == {"script_present": True, "configured": False}


def test_setup_rejects_when_script_missing(monkeypatch):
    monkeypatch.setattr(bridge.os.path, "exists", lambda p: False)
    out = bridge._mcp_docker_setup()
    assert out["ok"] is False and "outdated" in out["error"]


def test_setup_idempotent_when_already_configured(monkeypatch):
    monkeypatch.setattr(bridge.os.path, "exists", lambda p: True)
    monkeypatch.setattr(bridge, "_mcp_docker_configured", lambda: True)
    assert bridge._mcp_docker_setup() == {"ok": True, "already": True}


def test_setup_runs_fixed_add_command(monkeypatch):
    monkeypatch.setattr(bridge.os.path, "exists", lambda p: True)
    monkeypatch.setattr(bridge, "_mcp_docker_configured", lambda: False)
    seen = {}

    def fake_run(cmd, **k):
        seen["cmd"] = cmd
        return _Result(0)
    monkeypatch.setattr(bridge.subprocess, "run", fake_run)
    out = bridge._mcp_docker_setup()
    assert out == {"ok": True, "already": False}
    assert seen["cmd"] == [bridge.CLAUDE_BIN, "mcp", "add", "--scope", "user",
                           bridge.MCP_DOCKER_NAME, "--", "python3", bridge.MCP_DOCKER_SCRIPT]


def test_setup_reports_claude_error(monkeypatch):
    monkeypatch.setattr(bridge.os.path, "exists", lambda p: True)
    monkeypatch.setattr(bridge, "_mcp_docker_configured", lambda: False)
    monkeypatch.setattr(bridge.subprocess, "run",
                        lambda *a, **k: _Result(1, "", "permission denied\n"))
    out = bridge._mcp_docker_setup()
    assert out["ok"] is False and "permission denied" in out["error"]


def test_remove_always_returns_ok(monkeypatch):
    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k: _Result(1, "", "not found"))
    assert bridge._mcp_docker_remove() == {"ok": True}


def test_remove_survives_exception(monkeypatch):
    def raise_err(*a, **k):
        raise OSError("no such file")
    monkeypatch.setattr(bridge.subprocess, "run", raise_err)
    assert bridge._mcp_docker_remove() == {"ok": True}


def test_setup_and_remove_paths_require_no_body_params():
    """The security note in claude_cli_bridge.py's docstring/comments: these two
    mutating endpoints must not read anything from the request body — name, scope
    and command are fixed constants. Regression guard: helpers take no arguments."""
    import inspect
    assert inspect.signature(bridge._mcp_docker_setup).parameters == {}
    assert inspect.signature(bridge._mcp_docker_remove).parameters == {}
