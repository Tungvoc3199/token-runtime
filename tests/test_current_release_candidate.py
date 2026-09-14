from pathlib import Path
import tomllib
import unittest

from scripts.distribution import release_label_for_version


ROOT = Path(__file__).resolve().parents[1]


class CurrentReleaseCandidateContractTests(unittest.TestCase):
    def test_current_release_identity_is_consistent_across_public_surface(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        version = project["version"]
        label = release_label_for_version(version)
        release_doc = f"docs/releases/{label}.md"

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"releases/tag/{label}", readme)
        self.assertIn(f"[{label} release notes]({release_doc})", readme)

        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## {label.removeprefix('v')}", changelog)

        policy = tomllib.loads((ROOT / "public-release.toml").read_text())
        self.assertIn(release_doc, policy["files"]["public"])
        self.assertTrue((ROOT / release_doc).is_file())


if __name__ == "__main__":
    unittest.main()
