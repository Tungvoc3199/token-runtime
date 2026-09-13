import tomllib
import unittest
from pathlib import Path

from token_runtime.compatibility import CompatibilityState
from token_runtime.anthropic_conformance import build_anthropic_conformance
from token_runtime.codex_recertification import build_codex_01540_recertification
from token_runtime.gemini_conformance import build_gemini_conformance


ROOT = Path(__file__).resolve().parents[1]
COMPAT_PATH = ROOT / "docs" / "COMPATIBILITY.md"


class DocsGrowthContractTests(unittest.TestCase):
    def test_public_compatibility_doc_is_exported_and_discoverable(self):
        self.assertTrue(COMPAT_PATH.is_file())
        release = tomllib.loads((ROOT / "public-release.toml").read_text())
        self.assertIn("docs/COMPATIBILITY.md", release["files"]["public"])
        self.assertIn("docs/COMPATIBILITY.md", (ROOT / "llms.txt").read_text())
        self.assertIn("docs/COMPATIBILITY.md", (ROOT / "README.md").read_text())

    def test_compatibility_doc_matches_canonical_certification_states(self):
        text = COMPAT_PATH.read_text()
        codex = build_codex_01540_recertification()
        anthropic = build_anthropic_conformance()
        gemini = build_gemini_conformance()
        self.assertEqual(codex.record.state, CompatibilityState.CERTIFIED)
        self.assertEqual(anthropic.record.state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertEqual(gemini.record.state, CompatibilityState.PASSTHROUGH_ONLY)
        self.assertIn("Codex CLI 0.154.0", text)
        self.assertIn("CERTIFIED", text)
        self.assertIn("Anthropic Messages", text)
        self.assertIn("Gemini GenerateContent", text)
        self.assertGreaterEqual(text.count("PASSTHROUGH_ONLY"), 2)
        self.assertIn("not wired into the production gateway", text)

    def test_readme_no_longer_labels_native_adapters_not_implemented(self):
        readme = (ROOT / "README.md").read_text()
        self.assertNotIn("Anthropic native wire protocol | ⏳ Not implemented", readme)
        self.assertNotIn("Gemini native wire protocol | ⏳ Not implemented", readme)
        self.assertIn("offline conformance", readme)
        self.assertIn("PASSTHROUGH_ONLY", readme)

    def test_unreleased_changelog_names_current_growth_surface(self):
        changelog = (ROOT / "CHANGELOG.md").read_text()
        for phrase in (
            "Codex CLI 0.154.0",
            "Anthropic Messages",
            "Gemini GenerateContent",
            "compatibility certification",
        ):
            self.assertIn(phrase, changelog)


if __name__ == "__main__":
    unittest.main()
