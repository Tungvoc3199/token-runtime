import tomllib
import unittest
from pathlib import Path

REQUIRED_PUBLIC_FILES = [
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "AGENTS.md",
    "llms.txt",
    "CHANGELOG.md",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
]


class OssSurfaceTests(unittest.TestCase):
    def test_required_public_files_exist(self):
        for path in REQUIRED_PUBLIC_FILES:
            self.assertTrue(Path(path).is_file(), path)

    def test_pyproject_public_metadata_is_complete(self):
        data = tomllib.loads(Path("pyproject.toml").read_text())
        project = data["project"]
        self.assertEqual(project["name"], "token-runtime")
        self.assertEqual(project["dependencies"], [])
        self.assertEqual(
            project["urls"]["Repository"],
            "https://github.com/Tungvoc3199/token-runtime",
        )
        self.assertEqual(project["requires-python"], ">=3.12")


def _project_data():
    return tomllib.loads(Path("pyproject.toml").read_text())


def _ci_text():
    return Path(".github/workflows/ci.yml").read_text()


class QualityToolingContractTests(unittest.TestCase):
    def test_ci_actions_are_sha_pinned_and_quality_gated(self):
        ci = _ci_text()
        self.assertIn(
            "actions/checkout@11d5960a326750d5838078e36cf38b85af677262", ci
        )
        self.assertIn(
            "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065", ci
        )
        for command in (
            "ruff check",
            "coverage report --fail-under=80",
            "public_audit.py --source-tree .",
        ):
            self.assertIn(command, ci)

    def test_dev_dependencies_do_not_change_runtime_dependencies(self):
        data = _project_data()["project"]
        self.assertEqual(data["dependencies"], [])
        dev = data["optional-dependencies"]["dev"]
        self.assertTrue(any(item.startswith("ruff") for item in dev))
        self.assertTrue(any(item.startswith("coverage") for item in dev))
        self.assertTrue(any(item.startswith("pre-commit") for item in dev))


class ContributorDocsContractTests(unittest.TestCase):
    def test_contributing_documents_dev_install_and_quality_gates(self):
        text = Path("CONTRIBUTING.md").read_text()
        for command in (
            "pip install -e '.[dev]'",
            "ruff check src tests scripts benchmarks",
            "coverage report --fail-under=80",
            "public_audit.py --source-tree .",
        ):
            self.assertIn(command, text)

if __name__ == "__main__":
    unittest.main()
