from pathlib import Path
import tomllib
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
CHECKOUT_SHA = "11d5960a326750d5838078e36cf38b85af677262"
SETUP_PYTHON_SHA = "a26af69be951a213d495a4c3e4e4022e16d87065"


class PublicReadyContractTests(unittest.TestCase):
    def test_brand_assets_are_valid_svg(self):
        for rel in (
            "docs/assets/token-logo.svg",
            "docs/assets/token-mark.svg",
            "docs/assets/token-hero.svg",
        ):
            path = ROOT / rel
            self.assertTrue(path.is_file(), rel)
            self.assertTrue(ET.parse(path).getroot().tag.endswith("svg"), rel)

    def test_ci_runs_real_python_checks(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn(f"actions/checkout@{CHECKOUT_SHA}", workflow)
        self.assertIn(f"actions/setup-python@{SETUP_PYTHON_SHA}", workflow)
        self.assertIn("ruff check src tests scripts benchmarks", workflow)
        self.assertIn("coverage report --fail-under=80", workflow)
        self.assertIn("python -m compileall -q src tests scripts benchmarks", workflow)
        self.assertIn("python scripts/public_audit.py --source-tree .", workflow)

    def test_release_metadata_and_license(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        self.assertEqual(project["version"], "0.1.0a1")
        self.assertEqual(project["license"]["text"], "Apache-2.0")
        license_text = (ROOT / "LICENSE").read_text()
        self.assertIn("Apache License", license_text)
        self.assertIn("Version 2.0, January 2004", license_text)

    def test_readme_uses_brand_ci_and_release_surface(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("docs/assets/token-logo.svg", readme)
        self.assertIn("docs/assets/token-hero.svg", readme)
        self.assertIn("actions/workflows/ci.yml/badge.svg?branch=main", readme)
        self.assertIn("Apache--2.0", readme)
        self.assertIn("v0.1.0-alpha.1", readme)
        self.assertIn("docs/CLAIMS.md", readme)
        self.assertIn("docs/RELEASE-PROCESS.md", readme)
        self.assertNotIn("docs/ALPHA-STATUS.md", readme)
        self.assertNotIn("docs/specs/TOKEN-V1.md", readme)
        self.assertNotIn("docs/superpowers/", readme)


if __name__ == "__main__":
    unittest.main()
