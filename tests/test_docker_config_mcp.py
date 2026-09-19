"""Tests for the /api/docker/mcp/* routes (app/api/docker_config.py) — the MCP
switch's reachability gate on setup, and that remove never gates on it.

Calls the route functions directly (same pattern as test_api_version.py), not
via TestClient — this repo does not use TestClient anywhere else.
"""
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.api import docker_config
from app.services import docker_service as ds


@pytest.fixture(autouse=True)
def _tmp_config(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "DOCKER_CONFIG_FILE", tmp_path / "docker_config.json")
    monkeypatch.setattr(ds, "_LOCK", tmp_path / "docker_config.json.lock")
    yield


def test_setup_rejected_when_not_reachable(monkeypatch):
    monkeypatch.setattr(ds, "status", lambda *a, **k: {"reachable": False})
    monkeypatch.setattr(ds, "mcp_setup", lambda: pytest.fail("must not call the bridge"))
    with pytest.raises(HTTPException) as exc:
        docker_config.post_mcp_setup()
    assert exc.value.status_code == 400
    assert exc.value.detail == "docker.mcp.err.not_reachable"


def test_setup_calls_bridge_when_reachable(monkeypatch):
    monkeypatch.setattr(ds, "status", lambda *a, **k: {"reachable": True})
    monkeypatch.setattr(ds, "mcp_setup", lambda: {"ok": True, "already": False})
    assert docker_config.post_mcp_setup() == {"ok": True, "already": False}


def test_remove_ignores_reachability(monkeypatch):
    monkeypatch.setattr(ds, "status", lambda *a, **k: pytest.fail("remove must not probe status"))
    monkeypatch.setattr(ds, "mcp_remove", lambda: {"ok": True})
    assert docker_config.post_mcp_remove() == {"ok": True}


def test_get_status_passthrough(monkeypatch):
    monkeypatch.setattr(ds, "mcp_status", lambda: {"script_present": True, "configured": False})
    assert docker_config.get_mcp_status() == {"script_present": True, "configured": False}
