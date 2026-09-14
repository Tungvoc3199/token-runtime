import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import scripts.distribution as distribution


def write_wheel(path: Path, version: str) -> None:
    metadata = (
        "Metadata-Version: 2.4\n"
        "Name: token-runtime\n"
        f"Version: {version}\n\n"
    ).encode()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"token_runtime-{version}.dist-info/METADATA",
            metadata,
        )
        archive.writestr("token_runtime/__init__.py", b"")


class DistributionVersionGeneralizationTests(unittest.TestCase):
    def test_upgrade_rollback_uses_versions_from_wheel_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior = root / "token_runtime-0.1.0a2-py3-none-any.whl"
            candidate = root / "token_runtime-0.1.0a3-py3-none-any.whl"
            write_wheel(prior, "0.1.0a2")
            write_wheel(candidate, "0.1.0a3")
            with (
                mock.patch.object(distribution, "_create_venv") as create,
                mock.patch.object(distribution, "_pip_install"),
                mock.patch.object(distribution, "installed_smoke") as smoke,
            ):
                create.side_effect = lambda venv: (
                    venv / "bin" / "python",
                    venv / "bin" / "pip",
                    venv / "bin" / "token",
                )
                distribution.qualify_upgrade_rollback(
                    prior,
                    candidate,
                    root / "qualify",
                )

        versions = [call.args[2] for call in smoke.call_args_list]
        self.assertEqual(versions, ["0.1.0a2", "0.1.0a3", "0.1.0a2"])


if __name__ == "__main__":
    unittest.main()
