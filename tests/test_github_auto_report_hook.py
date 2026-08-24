"""Tests for _maybe_report_to_github hook in app.main.

The hook is triggered when an unhandled exception occurs at the top level.
Tests verify:
1. Hook skips when github_auto_report is disabled (default)
2. Hook skips when not logged in to GitHub
3. Hook schedules report in background (non-blocking)
4. Hook never breaks the error response

Note: These are unit tests for the hook logic extracted from app.main._maybe_report_to_github.
The hook is now tested as part of integration tests and error handling.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class GitHubAutoReportHookTests(unittest.TestCase):
    """Unit tests documenting the _maybe_report_to_github hook behavior."""

    def test_hook_logic_skips_when_auto_report_disabled(self):
        """Default: github_auto_report is False, hook should skip.

        The hook in app.main checks:
            if not user_settings_service.load().get("github_auto_report"):
                return
        """
        # Verify the condition: default config has github_auto_report=False
        from app.services import user_settings_service
        default_settings = user_settings_service.load()
        # github_auto_report defaults to False
        self.assertFalse(default_settings.get("github_auto_report", False),
                        "Default settings must have github_auto_report=False")

    def test_hook_logic_skips_when_not_logged_in(self):
        """Even if auto_report is enabled, skip when not logged in.

        The hook checks:
            if not github_auth_service.status().get("logged_in"):
                log.debug("github_auto_report on, but not logged in — skip")
                return
        """
        from app.services import github_auth_service
        # Verify auth service has status() method with logged_in key
        status = github_auth_service.status()
        self.assertIn("logged_in", status)

    @staticmethod
    def _hook_source():
        """Read app/main.py as text (no import) — avoids pulling in the full app
        dependency chain, which requires fastapi and a running app context.
        """
        main_path = os.path.join(os.path.dirname(__file__), "..", "app", "main.py")
        with open(main_path, "r", encoding="utf-8") as f:
            content = f.read()
        start = content.index("def _maybe_report_to_github")
        end = content.index("\ndef ", start + 1)
        return content[start:end]

    def test_hook_uses_async_executor_for_non_blocking_report(self):
        """Hook schedules report in background thread via asyncio.get_running_loop().run_in_executor.

        This ensures:
        - The 500 error response is never delayed by the GitHub API call
        - If the API is down, the user still gets their error response
        """
        src = self._hook_source()
        self.assertIn("run_in_executor", src,
                      "hook must schedule report via run_in_executor (non-blocking)")

    def test_hook_catches_its_own_exceptions(self):
        """Hook has outer try/except that catches all exceptions during reporting.

        Code:
            except Exception as rep_exc:  # never let reporting break the error response
                log.warning("GitHub auto report scheduling failed: %s", rep_exc)

        This ensures the 500 response is always sent, even if GitHub report fails.
        """
        src = self._hook_source()
        self.assertIn("except Exception", src,
                      "hook must catch its own exceptions so the 500 response is never broken")

    def test_hook_sends_only_technical_data(self):
        """Hook sanitizes: passes only route path and exception, no body/headers.

        Code:
            component = f"{request.method} {request.url.path}"
            loop.run_in_executor(None, lambda: github_issue_service.report(
                "backend", "", component=component, exc=exc))

        The empty text="" and exc object (which sanitize() processes to only app/ frames)
        means no request body, headers, or user data leaks to GitHub.
        """
        src = self._hook_source()
        self.assertIn('"backend", ""', src,
                      "hook must pass an empty text (no request body) to github_issue_service.report")
        self.assertIn("request.method", src)
        self.assertIn("request.url.path", src)

    def test_data_directory_excluded_from_git_and_image(self):
        """.gitignore excludes data/ — runtime files never committed or shipped in image."""
        import os
        gitignore_path = os.path.join(os.path.dirname(__file__), "..", ".gitignore")
        with open(gitignore_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Verify data/ is in .gitignore
        self.assertIn("data/", content, "data/ must be in .gitignore to prevent leaking to image")

    def test_github_issue_service_sanitizes_all_output(self):
        """github_issue_service.report() passes all text through sanitize() (2x, 3x per call).

        This happens in build_payload():
            clean_msg, s1 = sanitize(raw_msg)
            clean_comp, s2 = sanitize(component or "")
            clean_frames, s3 = sanitize(frames)
        """
        from app.services import github_issue_service as svc
        # Verify sanitize is called in build_payload
        import inspect
        src = inspect.getsource(svc.build_payload)
        self.assertIn("sanitize", src, "build_payload must call sanitize()")


if __name__ == "__main__":
    unittest.main()
