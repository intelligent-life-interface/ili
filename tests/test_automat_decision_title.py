"""F-15: decision card titles must not be raw free text chopped mid-word.

The 'eigene Antwort'-input in html/js/project-decisions.js accepts arbitrary
length free text (pasted voice transcripts, rambling replies). _mark_answered()
used to build the title as f"...{choice[:70]}..." — a blind slice that could
land mid-word and kept embedded newlines/double spaces. Run with
`python3 -m unittest tests.test_automat_decision_title` or `pytest tests/`.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.automat import _mark_answered, _summarize_choice  # noqa: E402


class SummarizeChoiceTests(unittest.TestCase):
    def test_short_choice_unchanged(self):
        self.assertEqual(_summarize_choice("Ja, so machen", 70), "Ja, so machen")

    def test_whitespace_collapsed(self):
        self.assertEqual(_summarize_choice("Ja\n\n  so   machen", 70), "Ja so machen")

    def test_long_choice_cut_on_word_boundary(self):
        choice = "Das ist eine sehr lange freie Antwort mit vielen Woertern die ueber das Limit hinausgeht"
        result = _summarize_choice(choice, 30)
        self.assertLessEqual(len(result), 31)  # +1 fuer die Ellipse
        self.assertTrue(result.endswith("…"))
        # Der sichtbare Teil muss an einem Wortende aufhoeren, nicht mitten im Wort
        visible = result[:-1].rstrip()
        self.assertTrue(choice.startswith(visible))
        self.assertTrue(choice[len(visible):len(visible) + 1] in (" ", ""))

    def test_single_long_word_still_bounded(self):
        choice = "x" * 100
        result = _summarize_choice(choice, 30)
        self.assertEqual(result, "x" * 30 + "…")


class MarkAnsweredTitleTests(unittest.TestCase):
    def test_title_from_messy_free_text_is_clean(self):
        card = {"id": "c1", "title": "🟡 ENTSCHEIDUNG: Testfrage?"}
        choice = "Ja klar,\n\n  das   soll so sein weil wir das letzte Mal schon besprochen hatten dass es passt"
        _mark_answered(card, choice, is_delete=False)
        prefix = card["title"].split(" — ")[0]
        self.assertTrue(prefix.startswith("✅ "))
        self.assertNotIn("\n", card["title"])
        self.assertNotIn("  ", card["title"])

    def test_delete_title_also_cleaned(self):
        card = {"id": "c1", "title": "🟡 ENTSCHEIDUNG: Testfrage?"}
        choice = "Rauschen,\n\n  das   ist irrelevant und kann weg weil es sich erledigt hat inzwischen"
        _mark_answered(card, choice, is_delete=True)
        self.assertTrue(card["title"].startswith("🗑️ "))
        self.assertNotIn("\n", card["title"])
        self.assertNotIn("  ", card["title"])

    def test_already_answered_card_untouched(self):
        card = {"id": "c1", "title": "✅ bereits beantwortet — 🟡 ENTSCHEIDUNG: X?"}
        _mark_answered(card, "neue Antwort", is_delete=False)
        self.assertEqual(card["title"], "✅ bereits beantwortet — 🟡 ENTSCHEIDUNG: X?")


if __name__ == "__main__":
    unittest.main()
