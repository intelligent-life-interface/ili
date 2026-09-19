"""No query string may ever reach the logs — GitHub issue #2.

Two independent leak paths, one test each:

1. uvicorn's own access logger prints the full request line
   (`"GET /path?token=secret HTTP/1.1"`). It is on by default, so the
   Containerfile has to switch it off explicitly.
2. Our own middleware could start logging `request.url` instead of
   `request.url.path` — that would put the query back in, silently.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _containerfile_cmd() -> str:
    for line in (REPO / "Containerfile").read_text().splitlines():
        if line.startswith("CMD ") and "uvicorn" in line:
            return line
    raise AssertionError("no uvicorn CMD directive found in Containerfile")


def test_uvicorn_access_log_is_disabled():
    """Without this flag every query string lands in the container log."""
    assert "--no-access-log" in _containerfile_cmd()


def test_nginx_access_log_has_no_query_string():
    """nginx' default format `combined` logs $request — the full request line."""
    conf = (REPO / "deploy" / "nginx-portable.conf").read_text()
    assert "log_format ili_noquery" in conf, "no query-free log format defined"
    assert "access_log" in conf and "ili_noquery" in conf.split("server {")[1]
    # $request would put the query back in; $uri is the path alone
    fmt = conf.split("log_format ili_noquery", 1)[1].split(";", 1)[0]
    assert "$request " not in fmt and "$request'" not in fmt
    assert "$uri" in fmt


def test_setup_scripts_do_not_override_the_log_format():
    """A second access_log directive in the generated config would win."""
    for name in ("nginx-setup.sh", "nginx-terminal-setup.sh"):
        script = REPO / "deploy" / name
        if script.exists():
            assert "access_log" not in script.read_text(), f"{name} writes its own access_log"


def test_app_never_logs_the_full_url():
    """Log calls must use request.url.path, never request.url or .query."""
    source = (REPO / "app" / "main.py").read_text()
    assert "request.url.query" not in source
    # `request.url` is only allowed when immediately followed by `.path`
    bare_url = re.findall(r"request\.url(?!\.path)\b", source)
    assert not bare_url, f"{len(bare_url)} log call(s) use the full request.url"
