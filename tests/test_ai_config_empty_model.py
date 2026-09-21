"""An empty model id must never reach the Claude CLI.

Field report 19.09.2026: `ai_config.json` held "" for every model field, which
travelled through `.get(key, default)` (the default only applies to a *missing*
key) all the way into `claude -p --model ""`. The CLI answered
`unrecognized_model`, the bridge turned that into a 500, and project creation
produced a red card blaming the login — which was fine.

Four independent places are nailed down here, because any one of them alone
would have prevented the outage.
"""
import json
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]


class LoadDropsEmptyValues(unittest.TestCase):
    """A stored "" must lose against the default, not win over it."""

    def _load_with(self, stored: dict) -> dict:
        import config_handler
        with mock.patch.object(type(config_handler.AI_CONFIG_FILE), "read_text",
                               return_value=json.dumps(stored)):
            return config_handler._load_ai_config()

    def test_empty_string_falls_back_to_default(self):
        import config_handler
        cfg = self._load_with({"project_ideas_model": ""})
        self.assertEqual(cfg["project_ideas_model"],
                         config_handler._AI_CONFIG_DEFAULTS["project_ideas_model"])

    def test_real_value_still_wins(self):
        cfg = self._load_with({"project_ideas_model": "claude-haiku-4-5"})
        self.assertEqual(cfg["project_ideas_model"], "claude-haiku-4-5")

    def test_no_model_field_is_ever_blank(self):
        cfg = self._load_with({k: "" for k in ("project_ideas_model", "chat_model",
                                               "bug_model", "ki_advisor_model")})
        blank = [k for k, v in cfg.items() if k.endswith("_model") and not str(v).strip()]
        self.assertEqual(blank, [], f"blank model ids survived: {blank}")


class SaveRefusesEmptyModels(unittest.TestCase):
    """One click on Save with unloaded lists must not wipe the configuration."""

    def test_empty_models_are_not_persisted(self):
        import config_handler
        written = {}
        with mock.patch.object(config_handler, "write_json_atomic",
                               side_effect=lambda p, d: written.update(d)), \
             mock.patch.object(type(config_handler.AI_CONFIG_FILE), "read_text",
                               return_value=json.dumps({"project_ideas_model": "claude-sonnet-5"})):
            config_handler._save_ai_config({"project_ideas_model": "", "chat_model": ""})
        self.assertEqual(written.get("project_ideas_model"), "claude-sonnet-5",
                         "an empty POST overwrote a good model id")


class BridgeTreatsBlankAsMissing(unittest.TestCase):
    def test_bridge_falls_back_on_blank_model(self):
        src = (REPO / "deploy" / "terminal" / "claude_cli_bridge.py").read_text()
        self.assertNotIn('model = payload.get("model", "claude-sonnet-4-6")', src,
                         "`.get` with a default returns the stored empty string")
        self.assertRegex(src, r'model = \(payload\.get\("model"\) or ""\)\.strip\(\) or ')


class FrontendSkipsEmptySelect(unittest.TestCase):
    def test_settings_page_does_not_post_empty_values(self):
        src = (REPO / "html" / "ai-settings.html").read_text()
        self.assertNotIn("if (sel) payload[fn.key] = sel.value;", src)
        self.assertIn("if (sel && sel.value) payload[fn.key] = sel.value;", src)


class FailureCardTellsTheTruth(unittest.TestCase):
    """The card must show the real error and must not look like a task."""

    def test_card_carries_the_error_and_is_not_for_the_automation(self):
        import importlib
        mod = importlib.import_module("app.services.board_creation_service")
        card = mod._ki_failure_card(True, ['Tags: HTTP 500: claude exit 1: unrecognized_model {"model":""}'])
        self.assertIn("unrecognized_model", card["desc"])
        self.assertEqual(card["desc"], card["description"])  # both views read one of them
        self.assertEqual(card.get("owner"), "mensch")
        self.assertTrue(card.get("no_auto"))

    def test_card_without_errors_still_works(self):
        import importlib
        mod = importlib.import_module("app.services.board_creation_service")
        card = mod._ki_failure_card(False, [])
        self.assertIn("nicht erreichbar", card["desc"])


class BridgeErrorBodyIsKept(unittest.TestCase):
    def test_http_error_body_is_read(self):
        src = (REPO / "app" / "services" / "claude_client.py").read_text()
        self.assertIn("urllib.error.HTTPError", src)
        self.assertRegex(src, r"e\.read\(\)")


class DockerGuideStaysHonest(unittest.TestCase):
    def test_no_empty_docker_host_in_the_generated_guide(self):
        src = (REPO / "app" / "services" / "docker_service.py").read_text()
        self.assertIn('if st.get("docker_host") else "."', src)

    def test_guide_script_marks_a_stale_file(self):
        src = (REPO / "deploy" / "terminal" / "ili-docker-guide.sh").read_text()
        self.assertIn("STALE_MARK", src)
        self.assertNotIn('leaving ${TARGET} as is"\n    exit 0', src)


class FailureCardIsNoTaskForTheAutomat(unittest.TestCase):
    """The kifail_ card sets no_auto; the automation must actually honour it."""

    def test_no_auto_card_is_not_actionable(self):
        import sys
        sys.path.insert(0, str(REPO / "automat"))
        import automat_lib
        board = {"columns": [{"id": "backlog", "title": "Backlog", "cards": [
            {"id": "kifail_x", "title": "KI-Vorbereitung fehlgeschlagen", "no_auto": True},
            {"id": "real_1", "title": "Echte Aufgabe"},
        ]}]}
        ids = [c["id"] for _, c in automat_lib.actionable_cards(board)]
        self.assertEqual(ids, ["real_1"])


if __name__ == "__main__":
    unittest.main()
