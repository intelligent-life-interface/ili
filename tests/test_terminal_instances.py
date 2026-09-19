"""Five terminals per project — run with
`python3 -m unittest tests.test_terminal_instances` or `pytest tests/`.

A project has four Claude terminals and one plain shell (asked for on 2026-09-18).
The instance number travels from the URL through ttyd into a tmux session name, so
three properties must not drift:

  * instance 1 keeps the historic session name `proj-<slug>` — older sessions, the
    heal endpoint and the automat all address exactly that one
  * the number is an allow-list, never a filtered string: it ends up in a session
    name built from user input
  * instance 5 starts no Claude, otherwise "one plain terminal" would be a fifth
    assistant
"""
import os
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


class TermWrapperTests(unittest.TestCase):
    """deploy/terminal/ili-term.sh — session names and the Claude decision."""

    def setUp(self):
        self.sh = read("deploy", "terminal", "ili-term.sh")

    def test_instance_is_an_allow_list(self):
        self.assertIn("1|2|3|4|5)", self.sh)

    def test_instance_one_keeps_the_historic_name(self):
        self.assertIn('1) SESSION_PREFIX="proj"', self.sh)

    def test_shell_instance_has_its_own_prefix(self):
        # A prefix, not a suffix: board ids may themselves end in -<digit>.
        self.assertIn('5) SESSION_PREFIX="shell"', self.sh)
        self.assertIn('SESSION="${SESSION_PREFIX}-${SLUG:-home}"', self.sh)

    def test_shell_instance_starts_no_claude(self):
        self.assertIn('5) SESSION_PREFIX="shell" ; RUN_CLAUDE=0', self.sh)
        self.assertIn('if [[ "$RUN_CLAUDE" -eq 0 ]]; then', self.sh)


class SessionNameTests(unittest.TestCase):
    """app/services/bot_status_service.py — the same mapping on the server side."""

    def test_mapping_matches_the_wrapper(self):
        import sys
        sys.path.insert(0, os.path.abspath(ROOT))
        from app.services.bot_status_service import session_name
        self.assertEqual(session_name("demo", 1), "proj-demo")
        self.assertEqual(session_name("demo", 3), "proj3-demo")
        self.assertEqual(session_name("demo", 5), "shell-demo")
        # Anything outside 1-5 falls back to the historic session.
        self.assertEqual(session_name("demo", 9), "proj-demo")

    def test_board_id_ending_in_a_digit_stays_unambiguous(self):
        import sys
        sys.path.insert(0, os.path.abspath(ROOT))
        from app.services.bot_status_service import session_name, _link_for
        name = session_name("ili-release-0-1-20", 2)
        self.assertEqual(name, "proj2-ili-release-0-1-20")
        kind, slug, _link = _link_for(name)
        self.assertEqual(slug, "ili-release-0-1-20")
        self.assertEqual(kind, "Projekt 2")


class FrontendTests(unittest.TestCase):
    """The tab strip exists on both the desktop and the phone."""

    def test_desktop_url_carries_the_instance(self):
        js = read("html", "js", "project-chat-terminal.js")
        self.assertIn("'&arg=' + n", js)
        self.assertIn("function ptSwitchTerminal(", js)

    def test_desktop_has_five_tabs(self):
        html = read("html", "project.html")
        for n in range(1, 6):
            self.assertIn('data-instance="%d"' % n, html)

    def test_mobile_has_five_tabs_and_may_use_the_clipboard(self):
        html = read("html", "m", "index.html")
        for n in range(1, 6):
            self.assertIn('data-instance="%d"' % n, html)
        self.assertIn('id="m-term" class="term-frame"', html)
        self.assertIn('allow="clipboard-read; clipboard-write"', html)

    def test_mobile_paste_button_degrades(self):
        js = read("html", "m", "m.js")
        self.assertIn("navigator.clipboard.readText", js)
        self.assertIn("btn.style.display = 'none'", js)
