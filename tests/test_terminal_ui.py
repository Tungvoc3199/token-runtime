import io
from pathlib import Path
import tomllib
import unittest

from scripts.distribution import release_label_for_version
from token_runtime.cli import main
from token_runtime.terminal_ui import render_welcome


class TtyBuffer(io.StringIO):
    def isatty(self):
        return True


class TerminalUiTests(unittest.TestCase):
    def test_token_without_subcommand_renders_plain_welcome(self):
        out = io.StringIO()
        code = main([], stdout=out)
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("TOKEN", text)
        self.assertIn("Adaptive Context Runtime", text)
        root = Path(__file__).resolve().parents[1]
        project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
        self.assertIn(release_label_for_version(project["version"]), text)
        self.assertIn("Reduce context when safe", text)
        self.assertIn("token doctor", text)
        self.assertNotIn("\x1b[", text)

    def test_welcome_compacts_for_narrow_terminal(self):
        out = io.StringIO()
        render_welcome(out, version="0.1.0a1", width=48, color=False)
        text = out.getvalue()
        self.assertIn("TOKEN", text)
        self.assertIn("v0.1.0-alpha.1", text)
        self.assertLessEqual(max(map(len, text.splitlines())), 48)

    def test_no_color_disables_ansi_on_tty(self):
        out = TtyBuffer()
        render_welcome(out, version="0.1.0a1", width=80, color=None, env={"NO_COLOR": "1"})
        self.assertNotIn("\x1b[", out.getvalue())


if __name__ == "__main__":
    unittest.main()
