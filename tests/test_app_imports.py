"""Smoke tests: the app must be importable in a release image without home-stack
extras — run with `python3 -m unittest tests.test_app_imports` or `pytest tests/`.

Regression for v0.1.11: `budget_service` hard-imported `claude_limits_service`
(home-stack-only InfluxDB reader, removed by the release cleanup) and the
container crash-looped on start.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class AppImportTests(unittest.TestCase):

    def test_app_main_imports(self):
        """app.main registers all routers at import time — this catches any missing module."""
        import app.main  # noqa: F401
        self.assertTrue(hasattr(app.main, "app"))

    def test_budget_service_without_claude_limits_service(self):
        """No claude_limits_service ⇒ usage query yields None (estimate path), no exception."""
        from app.services import budget_service
        with mock.patch.object(budget_service, "claude_limits_service", None):
            self.assertIsNone(budget_service._query_influx_usage())


if __name__ == "__main__":
    unittest.main()
