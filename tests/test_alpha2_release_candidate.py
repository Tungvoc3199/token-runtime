from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
RELEASE_LABEL = "v0.1.0-alpha.2"
PACKAGE_VERSION = "0.1.0a2"
RELEASE_NOTES = ROOT / "docs" / "releases" / f"{RELEASE_LABEL}.md"


class Alpha2ReleaseCandidateContractTests(unittest.TestCase):
    def test_release_identity_is_consistent_across_public_source_surface(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        self.assertEqual(project["version"], PACKAGE_VERSION)

        readme = (ROOT / "README.md").read_text()
        self.assertIn(f"releases/tag/{RELEASE_LABEL}", readme)
        self.assertIn(
            f"[{RELEASE_LABEL} release notes](docs/releases/{RELEASE_LABEL}.md)",
            readme,
        )

        changelog = (ROOT / "CHANGELOG.md").read_text()
        self.assertIn(f"## {RELEASE_LABEL.removeprefix('v')}", changelog)

        policy = tomllib.loads((ROOT / "public-release.toml").read_text())
        self.assertIn(f"docs/releases/{RELEASE_LABEL}.md", policy["files"]["public"])
        self.assertTrue(RELEASE_NOTES.is_file())

    def test_release_notes_preserve_alpha_claim_boundaries(self):
        self.assertTrue(RELEASE_NOTES.is_file())
        notes = RELEASE_NOTES.read_text()
        for phrase in (
            "PASSTHROUGH_ONLY",
            "no live Anthropic API call",
            "not production gateway-wired",
            "0.1.0a2",
        ):
            self.assertIn(phrase, notes)
        for prohibited in (
            "guarantees no quality regression",
            "guarantees currency savings",
            "native Anthropic production routing is enabled",
            "native Gemini production routing is enabled",
        ):
            self.assertNotIn(prohibited, notes)


if __name__ == "__main__":
    unittest.main()
