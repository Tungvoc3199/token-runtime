import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.public_audit import audit_public_tree
from scripts.public_release import build_public_release, classify_files, tree_digest


REPO = Path(__file__).resolve().parents[1]


def init_fixture(extra_file: str | None = None) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "README.md").write_text("public fixture\n", encoding="utf-8")
    (root / "public-release.toml").write_text(
        'schema_version = 1\n[files]\npublic = ["README.md", "public-release.toml"]\nprivate = []\n',
        encoding="utf-8",
    )
    if extra_file:
        (root / extra_file).write_text("unclassified\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    return root


class PublicReleasePipelineTests(unittest.TestCase):
    def test_unclassified_tracked_file_blocks_export(self):
        repo = init_fixture("UNCLASSIFIED.md")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "unclassified"):
                build_public_release(repo, Path(tmp) / "out", "v0.test")

    def test_runtime_tree_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "public"
            manifest = build_public_release(REPO, destination, "v0.test")
            source_digest = tree_digest(REPO / "src" / "token_runtime")
            public_digest = tree_digest(destination / "src" / "token_runtime")
            self.assertEqual(manifest["runtime_tree_sha256"], source_digest)
            self.assertEqual(source_digest, public_digest)

    def test_two_exports_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "a"
            second = Path(tmp) / "b"
            build_public_release(REPO, first, "v0.test")
            build_public_release(REPO, second, "v0.test")
            snapshot_a = {
                p.relative_to(first).as_posix(): p.read_bytes()
                for p in sorted(first.rglob("*"))
                if p.is_file()
            }
            snapshot_b = {
                p.relative_to(second).as_posix(): p.read_bytes()
                for p in sorted(second.rglob("*"))
                if p.is_file()
            }
            self.assertEqual(snapshot_a, snapshot_b)

    def test_manifest_is_public_safe_and_versioned(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "public"
            build_public_release(REPO, destination, "v0.test")
            manifest = json.loads(
                (destination / "PUBLIC_RELEASE_MANIFEST.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["schema_version"], 1)
            self.assertIn("sanitizer_contract_version", manifest)
            self.assertEqual(manifest["sanitizer_contract_version"], 1)
            self.assertEqual(manifest["release_version"], "v0.test")
            self.assertRegex(manifest["runtime_tree_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(manifest["public_payload_sha256"], r"^[0-9a-f]{64}$")
            self.assertNotIn("source_commit", manifest)
            self.assertNotIn("generated_at", manifest)
            self.assertNotIn("source_path", manifest)

    def test_audit_reports_secret_and_private_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "leak.txt").write_text(
                ("Bearer " + "abcdefghijklmnop\n" + "/" + "home/private-user/project\n"),
                encoding="utf-8",
            )
            findings = audit_public_tree(root)
            joined = "\n".join(findings)
            self.assertIn("bearer-token", joined)
            self.assertIn("posix-home-path", joined)

    def test_generated_manifest_is_public_in_source_tree_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "public"
            build_public_release(REPO, destination, "v0.test")
            subprocess.run(["git", "init", "-q"], cwd=destination, check=True)
            subprocess.run(["git", "add", "."], cwd=destination, check=True)
            public, _ = classify_files(destination)
            self.assertIn("PUBLIC_RELEASE_MANIFEST.json", public)

    def test_release_and_audit_cli_support_direct_invocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "public"
            build = subprocess.run(
                [
                    sys.executable,
                    str(REPO / "scripts" / "public_release.py"),
                    "--source",
                    str(REPO),
                    "--destination",
                    str(destination),
                    "--version",
                    "v0.test",
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            audit = subprocess.run(
                [sys.executable, str(REPO / "scripts" / "public_audit.py"), str(destination)],
                cwd=REPO,
                capture_output=True,
                text=True,
            )
            self.assertEqual(audit.returncode, 0, audit.stderr)


if __name__ == "__main__":
    unittest.main()
