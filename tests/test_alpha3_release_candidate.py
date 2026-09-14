from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
RELEASE_LABEL = "v0.1.0-alpha.3"
PACKAGE_VERSION = "0.1.0a3"
PRIOR_VERSION = "0.1.0a2"
PRIOR_WHEEL = "token_runtime-0.1.0a2-py3-none-any.whl"
PRIOR_SHA256 = "9af7e100ae62a7bb33217bc201aeffbe345f071068b1879a8e06a2bd8a507bac"


class Alpha3ReleaseCandidateContractTests(unittest.TestCase):
    def test_alpha3_identity_is_aligned(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        self.assertEqual(project["version"], PACKAGE_VERSION)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"releases/tag/{RELEASE_LABEL}", readme)
        self.assertIn(f"token-runtime=={PACKAGE_VERSION}", readme)

        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## 0.1.0-alpha.3", changelog)
    def test_alpha3_distribution_workflows_are_release_aligned(self):
        distribution = (ROOT / ".github/workflows/distribution.yml").read_text()
        publish = (ROOT / ".github/workflows/publish-pypi.yml").read_text()

        for text in (distribution, publish):
            self.assertIn(RELEASE_LABEL, text)
            self.assertIn(PACKAGE_VERSION, text)
        self.assertIn("wheel==0.46.3", distribution)
        self.assertNotIn("wheel==0.46.1", distribution)

        self.assertIn(PRIOR_WHEEL, distribution)
        self.assertIn(PRIOR_SHA256, distribution)
        self.assertIn("0.1.0a2 -> 0.1.0a3 -> 0.1.0a2", (ROOT / "docs/RELEASE-PROCESS.md").read_text())

    def test_alpha3_release_notes_are_public_and_claim_bounded(self):
        notes_path = ROOT / "docs/releases/v0.1.0-alpha.3.md"
        self.assertTrue(notes_path.is_file())
        notes = notes_path.read_text(encoding="utf-8")
        for phrase in (
            "OpenAI Agents API",
            "PASSTHROUGH_ONLY",
            "onboarding",
            "0.1.0a2 -> 0.1.0a3 -> 0.1.0a2",
        ):
            self.assertIn(phrase, notes)
        policy = tomllib.loads((ROOT / "public-release.toml").read_text())
        self.assertIn("docs/releases/v0.1.0-alpha.3.md", policy["files"]["public"])


if __name__ == "__main__":
    unittest.main()
