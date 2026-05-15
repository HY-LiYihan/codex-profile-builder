from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import codex_profile_builder as profile_builder


class CodexProfileBuilderTests(unittest.TestCase):
    def test_redact_secret_patterns(self):
        stats = profile_builder.RedactionStats()
        text = "token=abc1234567890 sk-abc1234567890abcdef bearer abcdefghijklmnopqrstuvwxyz"
        redacted = profile_builder.redact(text, stats)
        self.assertNotIn("sk-abc", redacted)
        self.assertNotIn("token=abc", redacted)
        self.assertNotIn("bearer abc", redacted.lower())
        self.assertGreaterEqual(stats.hits, 3)

    def test_replace_managed_block_adds_new_block(self):
        block = profile_builder.START_MARKER + "\nhello\n" + profile_builder.END_MARKER + "\n"
        result = profile_builder.replace_managed_block("Existing\n", block)
        self.assertIn("Existing", result)
        self.assertIn("hello", result)

    def test_replace_managed_block_replaces_existing_block(self):
        old = f"a\n{profile_builder.START_MARKER}\nold\n{profile_builder.END_MARKER}\nz\n"
        block = profile_builder.START_MARKER + "\nnew\n" + profile_builder.END_MARKER + "\n"
        result = profile_builder.replace_managed_block(old, block)
        self.assertIn("new", result)
        self.assertNotIn("old", result)
        self.assertTrue(result.startswith("a\n"))

    def test_auto_context_detection(self):
        self.assertTrue(profile_builder.is_auto_context_message("# AGENTS.md instructions for /tmp/project"))
        self.assertTrue(profile_builder.is_auto_context_message("<environment_context>\n"))
        self.assertFalse(profile_builder.is_auto_context_message("请帮我研究 AGENTS.md 记忆方案"))


if __name__ == "__main__":
    unittest.main()
