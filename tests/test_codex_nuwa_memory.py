from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import codex_nuwa_memory as nuwa


class CodexNuwaMemoryTests(unittest.TestCase):
    def test_redact_secret_patterns(self):
        stats = nuwa.RedactionStats()
        text = "token=abc1234567890 sk-abc1234567890abcdef bearer abcdefghijklmnopqrstuvwxyz"
        redacted = nuwa.redact(text, stats)
        self.assertNotIn("sk-abc", redacted)
        self.assertNotIn("token=abc", redacted)
        self.assertNotIn("bearer abc", redacted.lower())
        self.assertGreaterEqual(stats.hits, 3)

    def test_replace_managed_block_adds_new_block(self):
        block = nuwa.START_MARKER + "\nhello\n" + nuwa.END_MARKER + "\n"
        result = nuwa.replace_managed_block("Existing\n", block)
        self.assertIn("Existing", result)
        self.assertIn("hello", result)

    def test_replace_managed_block_replaces_existing_block(self):
        old = f"a\n{nuwa.START_MARKER}\nold\n{nuwa.END_MARKER}\nz\n"
        block = nuwa.START_MARKER + "\nnew\n" + nuwa.END_MARKER + "\n"
        result = nuwa.replace_managed_block(old, block)
        self.assertIn("new", result)
        self.assertNotIn("old", result)
        self.assertTrue(result.startswith("a\n"))


if __name__ == "__main__":
    unittest.main()
