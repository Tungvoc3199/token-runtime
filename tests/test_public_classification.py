import tomllib
import unittest
from pathlib import Path

from scripts.public_release import classify_files


ROOT = Path(__file__).resolve().parents[1]


class PublicClassificationTests(unittest.TestCase):
    def test_llm_change_playbook_is_public(self):
        path = "docs/LLM-CHANGE-PLAYBOOK.md"
        policy = tomllib.loads((ROOT / "public-release.toml").read_text())
        self.assertIn(path, policy["files"]["public"])

    def test_internal_public_ready_design_stays_private(self):
        path = "docs/specs/TOKEN-PUBLIC-READY-1.md"
        public, _ = classify_files(ROOT)
        policy = tomllib.loads((ROOT / "public-release.toml").read_text())
        private_patterns = policy["files"]["private"]
        self.assertNotIn(path, public)
        self.assertIn(path, private_patterns)


if __name__ == "__main__":
    unittest.main()
