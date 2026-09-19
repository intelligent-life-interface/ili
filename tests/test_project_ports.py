"""One reserved port per board — run with
`python3 -m unittest tests.test_project_ports` or `pytest tests/`.

A project container can take a port, not reserve one: by the time it runs, another
project may hold the number. ili therefore assigns a fixed port per board and hands
it to the AI in the generated guide. These tests pin the properties that make the
assignment trustworthy — stable, collision-free, and inside the range the sandbox
gateway actually forwards.
"""
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class PortAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from app.services import project_ports_service as svc
        self.svc = importlib.reload(svc)
        self.svc.PORTS_FILE = Path(self.tmp.name) / "project_ports.json"
        os.environ.pop("SANDBOX_PORT_FROM", None)
        os.environ.pop("SANDBOX_PORT_TO", None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_assignment_is_stable(self):
        first = self.svc.assign("alpha")
        again = self.svc.assign("alpha")
        self.assertTrue(first["created"])
        self.assertFalse(again["created"])
        self.assertEqual(first["port"], again["port"])

    def test_two_boards_never_share_a_port(self):
        a = self.svc.assign("alpha")["port"]
        b = self.svc.assign("beta")["port"]
        self.assertNotEqual(a, b)

    def test_ports_stay_inside_the_range(self):
        lo, hi = self.svc.port_range()
        for i in range(5):
            port = self.svc.assign(f"board{i}")["port"]
            self.assertGreaterEqual(port, lo)
            self.assertLessEqual(port, hi)

    def test_released_port_is_reused(self):
        a = self.svc.assign("alpha")["port"]
        self.svc.release("alpha")
        self.assertIsNone(self.svc.get("alpha"))
        self.assertEqual(self.svc.assign("gamma")["port"], a)

    def test_full_range_reports_instead_of_overflowing(self):
        os.environ["SANDBOX_PORT_FROM"] = "9000"
        os.environ["SANDBOX_PORT_TO"] = "9001"
        self.svc.assign("one")
        self.svc.assign("two")
        third = self.svc.assign("three")
        self.assertFalse(third["ok"])
        self.assertEqual(third["reason"], "range-full")

    def test_empty_board_is_rejected(self):
        self.assertFalse(self.svc.assign("  ")["ok"])

    def test_corrupt_file_does_not_break_the_api(self):
        self.svc.PORTS_FILE.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.svc.status()["assignments"], [])
        self.assertTrue(self.svc.assign("alpha")["ok"])

    def test_status_counts_free_ports(self):
        lo, hi = self.svc.port_range()
        self.svc.assign("alpha")
        st = self.svc.status()
        self.assertEqual(st["total"], hi - lo + 1)
        self.assertEqual(st["free_count"], st["total"] - 1)
        self.assertNotIn(st["assignments"][0]["port"], st["free"])

    def test_file_is_written_atomically(self):
        self.svc.assign("alpha")
        data = json.loads(self.svc.PORTS_FILE.read_text(encoding="utf-8"))
        self.assertIn("alpha", data["ports"])
        self.assertFalse(self.svc.PORTS_FILE.with_suffix(".tmp").exists())


class GuideTests(unittest.TestCase):
    """The AI must be told the number instead of guessing one."""

    def test_guide_mentions_reserved_ports(self):
        src = (ROOT / "app" / "services" / "docker_service.py").read_text(encoding="utf-8")
        self.assertIn("Reserved ports", src)
        self.assertIn("project_ports_service", src)


class RoutingTests(unittest.TestCase):
    """New API paths are useless if nginx swallows them (this happened four times)."""

    def test_ports_route_is_in_the_nginx_allowlist(self):
        conf = (ROOT / "html" / "_api-locations.conf").read_text(encoding="utf-8")
        self.assertIn("api/docker/(status|config|test|ports|mcp/status|mcp/setup|mcp/remove)", conf)


class BoardCreationWithPortsTests(unittest.TestCase):
    """Port assignment must be integrated into board creation and deletion."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from app.services import project_ports_service as svc
        self.svc = importlib.reload(svc)
        self.svc.PORTS_FILE = Path(self.tmp.name) / "project_ports.json"
        os.environ.pop("SANDBOX_PORT_FROM", None)
        os.environ.pop("SANDBOX_PORT_TO", None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_board_assigns_port(self):
        """create_board() should call assign() and include port in response."""
        import unittest.mock as mock
        from app.services import board_creation_service

        # Reload to pick up our patched PORTS_FILE
        importlib.reload(board_creation_service)
        board_creation_service.project_ports_service = self.svc

        def mock_update(mutator):
            manifest = {"boards": []}
            mutator(manifest)

        with mock.patch.object(board_creation_service._boards, 'create'):
            with mock.patch.object(board_creation_service._manifest, 'update', side_effect=mock_update):
                with mock.patch('project_creator._create_project_folder'):
                    result = board_creation_service.create_board({
                        "id": "test-board",
                        "name": "Test Board",
                        "fast": True  # Skip Ollama calls
                    })

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["id"], "test-board")
        self.assertIn("port", result)  # Port should be in response
        # Verify port was actually assigned
        port = self.svc.get("test-board")
        self.assertIsNotNone(port)

    def test_create_board_immediate_assigns_port(self):
        """create_board_immediate() should assign a port and include it in response."""
        import unittest.mock as mock
        from app.services import board_creation_service

        importlib.reload(board_creation_service)
        board_creation_service.project_ports_service = self.svc

        with mock.patch.object(board_creation_service._boards, 'create'):
            with mock.patch.object(board_creation_service._boards, 'exists', return_value=False):
                with mock.patch.object(board_creation_service._manifest, 'update'):
                    with mock.patch('project_creator._ensure_project_session'):
                        result, bg_args = board_creation_service.create_board_immediate({
                            "id": "immediate-test",
                            "name": "Immediate Test"
                        })

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["id"], "immediate-test")
        self.assertIn("port", result)  # Port should be in response
        # Verify port was assigned
        port = self.svc.get("immediate-test")
        self.assertIsNotNone(port)

    def test_delete_board_releases_port(self):
        """delete_board() should release the board's port."""
        import unittest.mock as mock
        from app.services import board_service

        importlib.reload(board_service)
        board_service.project_ports_service = self.svc

        # First, manually assign a port
        self.svc.assign("to-delete")
        port_before = self.svc.get("to-delete")
        self.assertIsNotNone(port_before)

        # Now delete the board (mock the manifest update properly)
        def mock_update(mutator):
            # Simulate the manifest update
            manifest = {"boards": []}
            mutator(manifest)

        with mock.patch.object(board_service._boards, 'delete', return_value=True):
            with mock.patch.object(board_service._manifest, 'update', side_effect=mock_update):
                result = board_service.delete_board("to-delete")

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["port_released"])  # Port should be released
        # Verify port was actually released
        port_after = self.svc.get("to-delete")
        self.assertIsNone(port_after)

    def test_full_port_range_still_creates_board(self):
        """When port range is full, board creation should still succeed (port_error in response)."""
        import unittest.mock as mock
        from app.services import board_creation_service

        # Set a very small port range
        os.environ["SANDBOX_PORT_FROM"] = "9000"
        os.environ["SANDBOX_PORT_TO"] = "9001"
        importlib.reload(board_creation_service)
        board_creation_service.project_ports_service = self.svc

        # Fill the range
        self.svc.assign("full1")
        self.svc.assign("full2")

        # Now try to create a third board
        def mock_update(mutator):
            manifest = {"boards": []}
            mutator(manifest)

        with mock.patch.object(board_creation_service._boards, 'create'):
            with mock.patch.object(board_creation_service._manifest, 'update', side_effect=mock_update):
                with mock.patch('project_creator._create_project_folder'):
                    with mock.patch('project_creator._unique_board_id', return_value='full3'):
                        result = board_creation_service.create_board({
                            "name": "Third Board",
                            "id": "full3",
                            "fast": True
                        })

        self.assertEqual(result["status"], "ok")  # Board should still be created
        self.assertEqual(result["id"], "full3")
        # Port should not be assigned (range full)
        self.assertIn("port_error", result)
        self.assertEqual(result["port_error"], "range-full")
        # Verify no port was assigned
        port = self.svc.get("full3")
        self.assertIsNone(port)
