from pathlib import Path
import tomllib
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


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
        self.assertIn("actions/checkout@v4", workflow)
        self.assertIn("actions/setup-python@v5", workflow)
        self.assertIn("python -m unittest -q", workflow)
        self.assertIn("python -m compileall -q src tests", workflow)

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
        self.assertIn("actions/workflows/ci.yml/badge.svg", readme)
        self.assertIn("Apache--2.0", readme)
        self.assertIn("v0.1.0-alpha.1", readme)


if __name__ == "__main__":
    unittest.main()
