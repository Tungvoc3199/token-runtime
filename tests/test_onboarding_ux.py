import io
import json
import tempfile
import tomllib
import unittest
from pathlib import Path

from token_runtime.cli import main


class OnboardingUxTests(unittest.TestCase):
    def test_quickstart_uses_pypi_and_uv_install_paths(self):
        readme = Path(__file__).resolve().parents[1] / "README.md"
        text = readme.read_text(encoding="utf-8")
        quickstart = text.split("## Quickstart", 1)[1].split("## Safety-first", 1)[0]

        project = tomllib.loads((readme.parent / "pyproject.toml").read_text())["project"]
        version = project["version"]
        self.assertIn(f"pip install token-runtime=={version}", quickstart)
        self.assertIn(f"uv tool install token-runtime=={version}", quickstart)
        self.assertNotIn("pip install . --no-build-isolation", quickstart)

    def test_doctor_missing_config_returns_bootstrap_guidance(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "config.json"
            out = io.StringIO()
            code = main(["doctor", "--config", str(missing)], stdout=out)
            payload = json.loads(out.getvalue())

            self.assertEqual(code, 1)
            self.assertFalse(payload["config_ok"])
            self.assertFalse(payload["state_ok"])
            self.assertFalse(payload["gateway_reachable"])
            self.assertFalse(payload["upstream_reachable"])
            self.assertIn("token install --upstream", payload["next_step"])


if __name__ == "__main__":
    unittest.main()
