"""Every FastAPI route under /api/ must be proxied by html/_api-locations.conf.

nginx answers anything the allowlist regex misses with index.html (HTTP 200,
text/html) — invisible until a page fails to parse HTML as JSON. This is the
fourth occurrence of the gap (api/claude-login-url, api/github, api/attachments,
api/docker on 2026-09-07), so the route list and the nginx config are checked
against each other here. New /api/ prefixes go into the regex in _api-locations.conf.
"""
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONF = ROOT / "html" / "_api-locations.conf"

# Pre-existing gaps documented in the 0.1.15 live-test findings — fix + remove here.
KNOWN_GAPS = set()
# Deliberately compose-internal (terminal/automat call http://api:8798 directly);
# they hand out DOCKER_HOST/cert paths and must not be reachable through the web container.
INTERNAL_ONLY = {
    "/api/docker/env",
    "/api/docker/claude-md",
}


def _nginx_matchers():
    conf = CONF.read_text()
    regexes = [re.compile(m) for m in re.findall(r"location ~ (\^\S+) \{", conf)]
    prefixes = re.findall(r"location \^~ (\S+) \{", conf) + re.findall(r"location (/[^\s{]+) \{", conf)
    return regexes, prefixes


def _api_paths():
    os.environ.setdefault("DASHBOARD_DIR", "/tmp/ili-test-dashboard")
    os.environ.setdefault("AUTOMAT_STATE_DIR", "/tmp/ili-test-state")
    from app.main import app
    return sorted(p for p in app.openapi()["paths"] if p.startswith("/api/"))


class NginxApiRoutesTest(unittest.TestCase):
    def test_every_api_route_is_proxied(self):
        regexes, prefixes = _nginx_matchers()
        self.assertTrue(regexes, "no `location ~` regex found in _api-locations.conf")

        def routed(path):
            probe = re.sub(r"\{[^}]+\}", "x", path)
            return any(r.match(probe) for r in regexes) or any(probe.startswith(p) for p in prefixes)

        paths = _api_paths()
        self.assertGreater(len(paths), 10, "openapi lists suspiciously few /api routes")
        gaps = [p for p in paths if not routed(p)]
        new_gaps = [p for p in gaps if p not in INTERNAL_ONLY
                    and not any(p == k or p.startswith(k + "/") for k in KNOWN_GAPS)]
        self.assertEqual(new_gaps, [], f"/api routes nginx does not proxy (add prefix to _api-locations.conf): {new_gaps}")
        # docker section (2026-09-07): browser endpoints routed, internal ones not
        for path in ("/api/docker/status", "/api/docker/config", "/api/docker/test"):
            self.assertTrue(routed(path), path)
        for path in INTERNAL_ONLY:
            self.assertFalse(routed(path), f"{path} must stay compose-internal")

    def test_known_gaps_still_exist(self):
        """Once a known gap is fixed, drop it from KNOWN_GAPS so the list stays honest."""
        regexes, prefixes = _nginx_matchers()
        for k in KNOWN_GAPS:
            self.assertFalse(any(r.match(k + "/x") for r in regexes) or any(k.startswith(p) for p in prefixes),
                             f"{k} is routed now — remove it from KNOWN_GAPS")
