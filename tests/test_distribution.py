import contextlib
import dataclasses
import hashlib
import io
import json
import tarfile
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import scripts.distribution as distribution
from scripts.distribution import (
    main as distribution_main,
    normalize_release_label,
    read_project_identity,
    release_label_for_version,
    validate_version_contract,
)


ROOT = Path(__file__).resolve().parents[1]
WHEEL_NAME = "token_runtime-0.1.0a2-py3-none-any.whl"
SDIST_NAME = "token_runtime-0.1.0a2.tar.gz"
RELEASE_LABEL = "v0.1.0-alpha.2"
VERSION = "0.1.0a2"


def require_task2_api(test: unittest.TestCase, name: str):
    api = getattr(distribution, name, None)
    test.assertIsNotNone(
        api,
        f"Task 2 API missing: scripts.distribution.{name}",
    )
    return api


def metadata_bytes(name: str = "token-runtime", version: str = VERSION) -> bytes:
    return (
        "Metadata-Version: 2.4\n"
        f"Name: {name}\n"
        f"Version: {version}\n"
        "\n"
    ).encode()


def write_wheel(
    path: Path,
    *,
    name: str = "token-runtime",
    version: str = VERSION,
    extra_members: dict[str, bytes] | None = None,
) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "token_runtime-0.1.0a2.dist-info/METADATA",
            metadata_bytes(name, version),
        )
        archive.writestr("token_runtime/__init__.py", b"")
        for member, content in (extra_members or {}).items():
            archive.writestr(member, content)


def write_sdist(
    path: Path,
    *,
    name: str = "token-runtime",
    version: str = VERSION,
    extra_members: dict[str, bytes] | None = None,
) -> None:
    with tarfile.open(path, "w:gz") as archive:
        members = {
            "token_runtime-0.1.0a2/PKG-INFO": metadata_bytes(name, version),
            "token_runtime-0.1.0a2/README.md": b"fixture\n",
            **(extra_members or {}),
        }
        for member, content in members.items():
            info = tarfile.TarInfo(member)
            info.size = len(content)
            info.mtime = 0
            archive.addfile(info, io.BytesIO(content))


def make_valid_dist(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    wheel = root / WHEEL_NAME
    sdist = root / SDIST_NAME
    write_wheel(wheel)
    write_sdist(sdist)
    return wheel, sdist


class DistributionVersionContractTests(unittest.TestCase):
    def _candidate(self, version: str = "0.1.0a2") -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "pyproject.toml").write_text(
            """[project]
name = "token-runtime"
version = "%s"
dependencies = []

[project.scripts]
token = "token_runtime.cli:main"
""" % version,
            encoding="utf-8",
        )
        return root

    def test_normalizes_alpha_release_label_to_pep440(self):
        self.assertEqual(
            normalize_release_label("v0.1.0-alpha.2"),
            "0.1.0a2",
        )

    def test_renders_pep440_alpha_version_to_release_label(self):
        self.assertEqual(
            release_label_for_version("0.1.0a2"),
            "v0.1.0-alpha.2",
        )

    def test_rejects_non_contract_release_labels_and_versions(self):
        for value in (
            "0.1.0-alpha.2",
            "v0.1.0-beta.2",
            "v0.1.0-alpha.2+local",
            "v0.1-alpha.2",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_release_label(value)

        for value in ("0.1.0b2", "0.1.0", "0.1.0a2+local", "v0.1.0a2"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    release_label_for_version(value)

    def test_mismatch_fails_closed_and_names_both_versions(self):
        candidate = self._candidate("0.1.0a1")
        manifest = {"release_version": "v0.1.0-alpha.2"}
        with self.assertRaises(ValueError) as ctx:
            validate_version_contract(candidate, manifest)
        message = str(ctx.exception)
        self.assertIn("v0.1.0-alpha.2", message)
        self.assertIn("0.1.0a1", message)
        self.assertIn("0.1.0a2", message)

    def test_matching_candidate_identity_passes(self):
        candidate = self._candidate()
        self.assertEqual(
            read_project_identity(candidate),
            ("token-runtime", "0.1.0a2"),
        )
        self.assertEqual(
            validate_version_contract(
                candidate,
                {"release_version": "v0.1.0-alpha.2"},
            ),
            ("token-runtime", "0.1.0a2"),
        )

    def test_canonical_package_metadata_matches_distribution_contract(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        self.assertEqual(project["name"], "token-runtime")
        self.assertEqual(project["version"], "0.1.0a2")
        self.assertEqual(project["dependencies"], [])
        self.assertEqual(project["scripts"]["token"], "token_runtime.cli:main")

    def test_public_release_manifest_is_optional_in_source_and_valid_when_generated(self):
        manifest_path = ROOT / "PUBLIC_RELEASE_MANIFEST.json"
        if not manifest_path.exists():
            self.assertFalse(manifest_path.exists())
            return
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["release_version"], RELEASE_LABEL)
        self.assertEqual(manifest["sanitizer_contract_version"], 1)
        self.assertEqual(
            validate_version_contract(ROOT, manifest),
            ("token-runtime", VERSION),
        )

    def test_contract_cli_missing_manifest_does_not_leak_absolute_candidate_path(self):
        candidate = self._candidate()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = distribution_main(["contract", "--candidate", str(candidate.resolve())])
        self.assertEqual(code, 1)
        self.assertNotIn(str(candidate.resolve()), stderr.getvalue())
        self.assertIn("release manifest", stderr.getvalue())

    def test_rejects_package_name_drift_and_invalid_release_version(self):
        candidate = self._candidate()
        pyproject = candidate / "pyproject.toml"
        pyproject.write_text(pyproject.read_text().replace('name = "token-runtime"', 'name = "other"'))
        with self.assertRaisesRegex(ValueError, "unexpected package name"):
            validate_version_contract(candidate, {"release_version": "v0.1.0-alpha.2"})

        candidate = self._candidate()
        for manifest in ({}, {"release_version": None}, {"release_version": 2}):
            with self.subTest(manifest=manifest):
                with self.assertRaisesRegex(ValueError, "invalid release_version"):
                    validate_version_contract(candidate, manifest)


class DistributionArtifactTests(unittest.TestCase):
    def test_artifact_record_is_frozen(self):
        record_type = require_task2_api(self, "ArtifactRecord")
        record = record_type(
            WHEEL_NAME,
            "a" * 64,
            123,
            "wheel",
            "token-runtime",
            VERSION,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            record.size = 0

    def test_inspection_returns_exact_artifacts_and_metadata(self):
        inspect = require_task2_api(self, "inspect_distributions")
        record_type = require_task2_api(self, "ArtifactRecord")
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            wheel, sdist = make_valid_dist(dist)

            records = inspect(dist, "token-runtime", VERSION)
            self.assertEqual(tuple(record.filename for record in records), (WHEEL_NAME, SDIST_NAME))
            self.assertEqual(tuple(record.kind for record in records), ("wheel", "sdist"))
            self.assertEqual(
                tuple(record.metadata_name for record in records),
                ("token-runtime", "token-runtime"),
            )
            self.assertEqual(tuple(record.metadata_version for record in records), (VERSION, VERSION))
            self.assertEqual(records[0].sha256, hashlib.sha256(wheel.read_bytes()).hexdigest())
            self.assertEqual(records[1].sha256, hashlib.sha256(sdist.read_bytes()).hexdigest())
            self.assertEqual(records[0].size, len(wheel.read_bytes()))
            self.assertIsInstance(records[0], record_type)

    def test_inspection_requires_exactly_the_wheel_and_sdist_filenames(self):
        inspect = require_task2_api(self, "inspect_distributions")
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            make_valid_dist(dist)
            (dist / "unexpected.txt").write_text("extra\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unexpected|exact|extra"):
                inspect(dist, "token-runtime", VERSION)

        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            make_valid_dist(dist)
            (dist / WHEEL_NAME).rename(dist / "token_runtime-0.1.0a2-any.whl")
            with self.assertRaisesRegex(ValueError, "filename|artifact|wheel"):
                inspect(dist, "token-runtime", VERSION)

    def test_inspection_rejects_archive_traversal_members(self):
        inspect = require_task2_api(self, "inspect_distributions")
        for archive_kind in ("wheel", "sdist"):
            with self.subTest(archive_kind=archive_kind), tempfile.TemporaryDirectory() as tmp:
                dist = Path(tmp)
                make_valid_dist(dist)
                if archive_kind == "wheel":
                    write_wheel(dist / WHEEL_NAME, extra_members={"../escape": b"bad"})
                else:
                    write_sdist(
                        dist / SDIST_NAME,
                        extra_members={"token_runtime-0.1.0a2/../../escape": b"bad"},
                    )
                with self.assertRaisesRegex(ValueError, "traversal|unsafe|member"):
                    inspect(dist, "token-runtime", VERSION)

    def test_inspection_rejects_ambiguous_duplicate_metadata(self):
        inspect = require_task2_api(self, "inspect_distributions")
        for archive_kind in ("wheel", "sdist"):
            with self.subTest(archive_kind=archive_kind), tempfile.TemporaryDirectory() as tmp:
                dist = Path(tmp)
                make_valid_dist(dist)
                if archive_kind == "wheel":
                    write_wheel(
                        dist / WHEEL_NAME,
                        extra_members={"duplicate.dist-info/METADATA": metadata_bytes()},
                    )
                else:
                    write_sdist(
                        dist / SDIST_NAME,
                        extra_members={"duplicate-root/PKG-INFO": metadata_bytes()},
                    )
                with self.assertRaisesRegex(ValueError, "METADATA|PKG-INFO|ambiguous|exactly one"):
                    inspect(dist, "token-runtime", VERSION)

    def test_inspection_rejects_wrong_metadata_identity(self):
        inspect = require_task2_api(self, "inspect_distributions")
        cases = (("wheel", "other-name", VERSION), ("sdist", "token-runtime", "0.1.0a1"))
        for archive_kind, name, version in cases:
            with self.subTest(archive_kind=archive_kind), tempfile.TemporaryDirectory() as tmp:
                dist = Path(tmp)
                make_valid_dist(dist)
                if archive_kind == "wheel":
                    write_wheel(dist / WHEEL_NAME, name=name, version=version)
                else:
                    write_sdist(dist / SDIST_NAME, name=name, version=version)
                with self.assertRaisesRegex(ValueError, "name|version|metadata|identity"):
                    inspect(dist, "token-runtime", VERSION)

    def test_build_distributions_uses_candidate_cwd_controlled_epoch_and_no_isolation(self):
        build = require_task2_api(self, "build_distributions")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate"
            candidate.mkdir()
            dist = root / "dist"

            def fake_run(command, **kwargs):
                make_valid_dist(dist)
                return mock.Mock(returncode=0)

            with mock.patch.object(distribution.subprocess, "run", side_effect=fake_run) as run:
                records = build(candidate, dist, 1788998400)

        self.assertEqual(tuple(record.filename for record in records), (WHEEL_NAME, SDIST_NAME))
        command = run.call_args.args[0]
        kwargs = run.call_args.kwargs
        self.assertEqual(command[:3], [distribution.sys.executable, "-m", "build"])
        self.assertIn("--wheel", command)
        self.assertIn("--sdist", command)
        self.assertIn("--no-isolation", command)
        self.assertIn("--outdir", command)
        self.assertEqual(Path(command[command.index("--outdir") + 1]), dist)
        self.assertEqual(Path(kwargs["cwd"]), candidate)
        self.assertTrue(kwargs["check"])
        self.assertEqual(kwargs["env"]["SOURCE_DATE_EPOCH"], "1788998400")
        self.assertEqual(kwargs["env"].get("SOURCE_DATE_EPOCH"), "1788998400")

    def test_build_distributions_resolves_relative_outdir_before_candidate_cwd(self):
        build = require_task2_api(self, "build_distributions")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate"
            caller = root / "caller"
            candidate.mkdir()
            caller.mkdir()
            relative_dist = Path("release") / "dist"

            def fake_run(command, **kwargs):
                outdir = Path(command[command.index("--outdir") + 1])
                if not outdir.is_absolute():
                    outdir = Path(kwargs["cwd"]) / outdir
                make_valid_dist(outdir)
                return mock.Mock(returncode=0)

            with contextlib.chdir(caller):
                with mock.patch.object(distribution.subprocess, "run", side_effect=fake_run) as run:
                    records = build(candidate, relative_dist, 1788998400)

        outdir = Path(run.call_args.args[0][run.call_args.args[0].index("--outdir") + 1])
        self.assertTrue(outdir.is_absolute())
        self.assertEqual(outdir, (caller / relative_dist).resolve())
        self.assertEqual(tuple(record.filename for record in records), (WHEEL_NAME, SDIST_NAME))

    def test_build_distributions_normalizes_sdist_to_controlled_epoch(self):
        build = require_task2_api(self, "build_distributions")
        epoch = 1788998400
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate"
            candidate.mkdir()
            dist = root / "dist"

            def fake_run(command, **kwargs):
                make_valid_dist(dist)
                return mock.Mock(returncode=0)

            with mock.patch.object(distribution.subprocess, "run", side_effect=fake_run):
                build(candidate, dist, epoch)

            raw = (dist / SDIST_NAME).read_bytes()
            self.assertEqual(int.from_bytes(raw[4:8], "little"), epoch)
            with tarfile.open(dist / SDIST_NAME, "r:gz") as archive:
                self.assertEqual({int(member.mtime) for member in archive.getmembers()}, {epoch})

    def test_build_distributions_requires_an_empty_output_directory(self):
        build = require_task2_api(self, "build_distributions")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate"
            candidate.mkdir()
            dist = root / "dist"
            dist.mkdir()
            (dist / "stale.whl").write_bytes(b"stale")
            with mock.patch.object(distribution.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "empty|output|dist"):
                    build(candidate, dist, 1788998400)
            run.assert_not_called()

    def test_build_candidate_composes_public_release_builder_and_version_validation(self):
        build_candidate = require_task2_api(self, "build_candidate")
        manifest = {
            "schema_version": 1,
            "sanitizer_contract_version": 1,
            "release_version": RELEASE_LABEL,
            "runtime_tree_sha256": "a" * 64,
            "public_payload_sha256": "b" * 64,
            "file_count": 1,
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            candidate = Path(tmp) / "candidate"
            source.mkdir()
            with (
                mock.patch.object(
                    distribution,
                    "build_public_release",
                    create=True,
                    return_value=manifest,
                ) as public_builder,
                mock.patch.object(distribution, "validate_version_contract") as validate,
            ):
                result = build_candidate(source, candidate, RELEASE_LABEL)

        self.assertEqual(result, manifest)
        public_builder.assert_called_once_with(source, candidate, RELEASE_LABEL)
        validate.assert_called_once_with(candidate, manifest)


class DistributionProvenanceTests(unittest.TestCase):
    def _manifest(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "sanitizer_contract_version": 1,
            "release_version": RELEASE_LABEL,
            "runtime_tree_sha256": "a" * 64,
            "public_payload_sha256": "b" * 64,
            "file_count": 2,
        }

    def _bundle(self, root: Path):
        inspect = require_task2_api(self, "inspect_distributions")
        write = require_task2_api(self, "write_release_bundle")
        bundle = root / "release"
        artifacts = make_valid_dist(bundle / "dist")
        records = inspect(bundle / "dist", "token-runtime", VERSION)
        provenance_path = write(
            bundle,
            self._manifest(),
            records,
            "a" * 64,
            "a" * 64,
            1788998400,
        )
        return bundle, artifacts, records, provenance_path

    def test_release_bundle_writer_api_is_declared(self):
        require_task2_api(self, "write_release_bundle")

    def test_release_bundle_is_deterministic_and_contains_complete_public_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle, _, records, provenance_path = self._bundle(Path(tmp))
            provenance_raw = provenance_path.read_text(encoding="utf-8")
            provenance = json.loads(provenance_raw)

            self.assertEqual(
                provenance_raw,
                json.dumps(provenance, indent=2, sort_keys=True) + "\n",
            )
            expected_sums = "".join(
                f"{record.sha256}  {record.filename}\n"
                for record in sorted(records, key=lambda item: item.filename)
            )
            sums = (bundle / "SHA256SUMS").read_text(encoding="utf-8")
            self.assertEqual(sums, expected_sums)
            self.assertRegex(sums, r"(?s)^(?:[0-9a-f]{64}  [^/\n]+\n){2}$")

        self.assertEqual(provenance["schema_version"], 1)
        self.assertEqual(provenance["distribution_name"], "token-runtime")
        self.assertEqual(provenance["package_version"], VERSION)
        self.assertEqual(provenance["release_label"], RELEASE_LABEL)
        self.assertEqual(provenance["normalized_version"], VERSION)
        self.assertEqual(provenance["sanitizer_contract_version"], 1)
        self.assertEqual(provenance["source_runtime_sha256"], "a" * 64)
        self.assertEqual(provenance["candidate_runtime_sha256"], "a" * 64)
        self.assertEqual(provenance["public_payload_sha256"], "b" * 64)
        rendered_manifest = json.dumps(self._manifest(), indent=2, sort_keys=True) + "\n"
        self.assertEqual(
            provenance["public_release_manifest_sha256"],
            hashlib.sha256(rendered_manifest.encode()).hexdigest(),
        )
        self.assertEqual(provenance["source_date_epoch"], 1788998400)
        self.assertEqual(
            provenance["artifacts"],
            [
                dataclasses.asdict(record)
                for record in sorted(records, key=lambda item: item.filename)
            ],
        )
        self.assertTrue(provenance["qualification_assertions"])
        self.assertTrue(all(provenance["qualification_assertions"].values()))

    def test_provenance_excludes_private_identity_time_path_and_credential_fields(self):
        forbidden = (
            "source_commit",
            "private_sha",
            "source_path",
            "candidate_path",
            "generated_at",
            "timestamp",
            "created_at",
            "build_time",
            "user",
            "email",
            "credential",
            "token",
            "authorization",
            "prompt",
            "infrastructure",
        )
        with tempfile.TemporaryDirectory() as tmp:
            _, _, _, provenance_path = self._bundle(Path(tmp))
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))

        def keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield key.lower()
                    yield from keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from keys(child)

        all_keys = tuple(keys(provenance))
        for term in forbidden:
            with self.subTest(term=term):
                self.assertFalse(any(term in key for key in all_keys), term)

    def test_release_bundle_rejects_unequal_source_and_candidate_runtime_digests(self):
        inspect = require_task2_api(self, "inspect_distributions")
        write = require_task2_api(self, "write_release_bundle")
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "release"
            make_valid_dist(bundle / "dist")
            records = inspect(bundle / "dist", "token-runtime", VERSION)
            with self.assertRaisesRegex(ValueError, "runtime|digest|equal"):
                write(
                    bundle,
                    self._manifest(),
                    records,
                    "a" * 64,
                    "c" * 64,
                    1788998400,
                )

    def test_verify_release_bundle_rejects_missing_additional_and_changed_files(self):
        verify = require_task2_api(self, "verify_release_bundle")
        mutations = ("missing", "additional", "changed")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                bundle, artifacts, _, _ = self._bundle(Path(tmp))
                wheel, _ = artifacts
                if mutation == "missing":
                    wheel.unlink()
                elif mutation == "additional":
                    (bundle / "unexpected.txt").write_text("extra\n", encoding="utf-8")
                else:
                    wheel.write_bytes(wheel.read_bytes() + b"changed")
                with self.assertRaisesRegex(ValueError, "missing|additional|unexpected|digest|changed|artifact"):
                    verify(bundle)

    def test_verify_release_bundle_rejects_checksum_and_metadata_disagreement(self):
        verify = require_task2_api(self, "verify_release_bundle")
        for mutation in ("checksum", "metadata"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                bundle, _, _, provenance_path = self._bundle(Path(tmp))
                if mutation == "checksum":
                    sums_path = bundle / "SHA256SUMS"
                    sums_path.write_text(
                        sums_path.read_text(encoding="utf-8").replace("a", "A", 1),
                        encoding="utf-8",
                    )
                else:
                    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                    provenance["artifacts"][0]["metadata_version"] = "0.1.0a1"
                    provenance_path.write_text(
                        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                with self.assertRaisesRegex(ValueError, "checksum|digest|metadata|version|provenance"):
                    verify(bundle)


def require_task3_api(test: unittest.TestCase, name: str):
    api = getattr(distribution, name, None)
    test.assertIsNotNone(api, f"Task 3 API missing: scripts.distribution.{name}")
    return api


class DistributionInstallTests(unittest.TestCase):
    def test_qualification_environment_is_isolated(self):
        helper = require_task3_api(self, "_qualification_env")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = helper(root)
        self.assertNotIn("PYTHONPATH", env)
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")
        self.assertTrue(Path(env["HOME"]).is_absolute())
        self.assertTrue(Path(env["PIP_CACHE_DIR"]).is_absolute())
        self.assertTrue(Path(env["HOME"]).is_relative_to(root))
        self.assertTrue(Path(env["PIP_CACHE_DIR"]).is_relative_to(root))

    def test_real_home_root_is_rejected(self):
        helper = require_task3_api(self, "_require_qualification_root")
        with self.assertRaisesRegex(ValueError, "home|temporary|qualification"):
            helper(Path.home())

    def test_pip_wheel_uses_local_no_deps_no_index_and_absolute_tools(self):
        qualify = require_task3_api(self, "qualify_pip_wheel")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wheel = root / WHEEL_NAME
            wheel.write_bytes(b"fixture")
            with (
                mock.patch.object(distribution, "_create_venv") as create,
                mock.patch.object(distribution, "_pip_install") as install,
                mock.patch.object(distribution, "installed_smoke") as smoke,
            ):
                create.side_effect = lambda venv: (venv / "bin" / "python", venv / "bin" / "pip", venv / "bin" / "token")
                qualify(wheel, VERSION, root / "qualify")
        command = install.call_args.args[1]
        self.assertIn("--no-deps", command)
        self.assertIn("--no-index", command)
        self.assertNotIn("-e", command)
        self.assertTrue(Path(install.call_args.args[0]).is_absolute())
        smoke.assert_called_once()

    def test_pip_sdist_uses_no_build_isolation_and_local_wheelhouse(self):
        qualify = require_task3_api(self, "qualify_pip_sdist")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sdist = root / SDIST_NAME
            sdist.write_bytes(b"fixture")
            wheelhouse = root / "wheelhouse"
            wheelhouse.mkdir()
            with (
                mock.patch.object(distribution, "_create_venv") as create,
                mock.patch.object(distribution, "_pip_install") as install,
                mock.patch.object(distribution, "installed_smoke") as smoke,
                mock.patch.dict(distribution.os.environ, {"TOKEN_DISTRIBUTION_BUILD_WHEELHOUSE": str(wheelhouse)}),
            ):
                create.side_effect = lambda venv: (venv / "bin" / "python", venv / "bin" / "pip", venv / "bin" / "token")
                qualify(sdist, VERSION, root / "qualify")
        commands = [call.args[1] for call in install.call_args_list]
        self.assertEqual(len(commands), 2)
        self.assertIn("--find-links", commands[0])
        self.assertIn("setuptools==84.0.0", commands[0])
        self.assertIn("wheel==0.46.1", commands[0])
        self.assertIn("--no-build-isolation", commands[1])
        self.assertIn("--no-deps", commands[1])
        self.assertIn("--no-index", commands[1])
        self.assertNotIn("-e", commands[1])
        smoke.assert_called_once()

    def test_uv_tool_uses_offline_no_cache_explicit_python_and_temp_dirs(self):
        qualify = require_task3_api(self, "qualify_uv_tool")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wheel = root / WHEEL_NAME
            wheel.write_bytes(b"fixture")
            python = Path("/usr/bin/python3")
            with (
                mock.patch.object(distribution.shutil, "which", return_value="/tmp/tools/uv"),
                mock.patch.object(distribution.subprocess, "run") as run,
                mock.patch.object(distribution, "installed_smoke") as smoke,
            ):
                qualify(wheel, VERSION, root / "qualify", python)
        command = run.call_args_list[0].args[0]
        env = run.call_args_list[0].kwargs["env"]
        self.assertEqual(command[0], "/tmp/tools/uv")
        self.assertIn("--offline", command)
        self.assertIn("--no-cache", command)
        self.assertIn("--python", command)
        self.assertIn(str(python), command)
        self.assertTrue(Path(env["UV_TOOL_DIR"]).is_relative_to(root / "qualify"))
        self.assertTrue(Path(env["UV_TOOL_BIN_DIR"]).is_relative_to(root / "qualify"))
        smoke.assert_called_once()

    def test_synthetic_prior_validates_built_wheel_metadata(self):
        build_prior = require_task3_api(self, "build_synthetic_previous")
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "prior"
            def fake_run(command, **kwargs):
                dist.mkdir(parents=True, exist_ok=True)
                wheel = dist / "token_runtime-0.1.0a1-py3-none-any.whl"
                with zipfile.ZipFile(wheel, "w") as archive:
                    archive.writestr("token_runtime-0.1.0a1.dist-info/METADATA", metadata_bytes(version="0.1.0a1"))
                return mock.Mock(returncode=0)
            with mock.patch.object(distribution.subprocess, "run", side_effect=fake_run):
                built = build_prior(dist, 1788998400)
        self.assertEqual(built.name, "token_runtime-0.1.0a1-py3-none-any.whl")

    def test_public_task3_apis_are_declared(self):
        for name in (
            "installed_smoke",
            "qualify_pip_wheel",
            "qualify_pip_sdist",
            "qualify_uv_tool",
            "build_synthetic_previous",
            "qualify_upgrade_rollback",
        ):
            with self.subTest(name=name):
                require_task3_api(self, name)


class DistributionUpgradeRollbackTests(unittest.TestCase):
    def test_upgrade_rollback_uses_same_prior_wheel_and_three_smokes(self):
        qualify = require_task3_api(self, "qualify_upgrade_rollback")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior = root / "token_runtime-0.1.0a1-py3-none-any.whl"
            current = root / WHEEL_NAME
            prior.write_bytes(b"prior")
            current.write_bytes(b"current")
            with (
                mock.patch.object(distribution, "_create_venv") as create,
                mock.patch.object(distribution, "_pip_install") as install,
                mock.patch.object(distribution, "installed_smoke") as smoke,
            ):
                create.side_effect = lambda venv: (venv / "bin" / "python", venv / "bin" / "pip", venv / "bin" / "token")
                qualify(prior, current, root / "qualify")
        self.assertEqual(smoke.call_count, 3)
        versions = [call.args[2] for call in smoke.call_args_list]
        self.assertEqual(versions, ["0.1.0a1", VERSION, "0.1.0a1"])
        commands = [call.args[1] for call in install.call_args_list]
        self.assertIn(str(prior), commands[0])
        self.assertIn(str(current), commands[1])
        self.assertIn(str(prior), commands[2])
        self.assertTrue(all("-e" not in command for command in commands))

    def test_upgrade_failure_is_stage_specific(self):
        qualify = require_task3_api(self, "qualify_upgrade_rollback")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior = root / "token_runtime-0.1.0a1-py3-none-any.whl"
            current = root / WHEEL_NAME
            prior.write_bytes(b"prior")
            current.write_bytes(b"current")
            with (
                mock.patch.object(distribution, "_create_venv") as create,
                mock.patch.object(distribution, "_pip_install", side_effect=[None, RuntimeError("boom")]),
                mock.patch.object(distribution, "installed_smoke"),
            ):
                create.side_effect = lambda venv: (venv / "bin" / "python", venv / "bin" / "pip", venv / "bin" / "token")
                with self.assertRaisesRegex(ValueError, "upgrade"):
                    qualify(prior, current, root / "qualify")



class DistributionWorkflowTests(unittest.TestCase):
    def _read(self, relative: str) -> str:
        path = ROOT / relative
        self.assertTrue(path.is_file(), f"missing workflow/document: {relative}")
        return path.read_text(encoding="utf-8")

    def test_qualification_workflow_is_read_only_deterministic_and_no_oidc(self):
        text = self._read(".github/workflows/distribution.yml")
        self.assertIn("contents: read", text)
        self.assertNotIn("id-token:", text)
        self.assertNotIn("environment:", text)
        self.assertNotIn("pypa/gh-action-pypi-publish", text)
        self.assertNotIn("secrets.", text)
        self.assertIn("SOURCE_DATE_EPOCH: 1788998400", text)
        self.assertIn("actions/checkout@11d5960a326750d5838078e36cf38b85af677262", text)
        self.assertIn("actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065", text)
        self.assertIn("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02", text)
        self.assertGreaterEqual(text.count("scripts/distribution.py build"), 2)
        self.assertIn("cmp ", text)
        self.assertIn("scripts/distribution.py prior-fixture", text)
        self.assertIn("scripts/distribution.py qualify", text)
        self.assertIn("scripts/distribution.py verify", text)
        self.assertIn("scripts/public_audit.py", text)
        self.assertIn("token-runtime-v0.1.0-alpha.2-qualified", text)
        self.assertIn("--bundle /tmp/token-dist-release-a", text)
        self.assertIn("--bundle /tmp/token-dist-release-b", text)
        self.assertNotIn("--bundle release", text)
        self.assertIn("path: /tmp/token-dist-release-a/", text)

    def test_publish_workflow_defaults_to_dry_run_and_only_publish_job_has_oidc(self):
        text = self._read(".github/workflows/publish-pypi.yml")
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("workflow_call:", text)
        self.assertIn("qualification_run_id:", text)
        self.assertIn("publish:", text)
        self.assertIn("default: false", text)
        self.assertIn("actions/download-artifact@fa0a91b85d4f404e444e00e005971372dc801d16", text)
        self.assertIn("pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33", text)
        self.assertEqual(text.count("id-token: write"), 1)
        self.assertIn("actions: read", text)
        self.assertIn("contents: read", text)
        self.assertIn("name: pypi", text)
        self.assertIn("url: https://pypi.org/p/token-runtime", text)
        self.assertIn("packages-dir: release/dist", text)
        self.assertNotIn("username:", text.lower())
        self.assertNotIn("password:", text.lower())
        self.assertNotIn("api-token:", text.lower())
        self.assertNotIn("secrets.", text)
        self.assertNotIn("attestations: false", text)
        verify_text, publish_text = text.split(chr(10) + "  publish:" + chr(10), 1)
        self.assertNotIn("id-token: write", verify_text)
        self.assertNotIn("actions/checkout@", publish_text)
        self.assertNotIn("scripts/distribution.py build", publish_text)
        self.assertIn("github.event.inputs.publish == 'true'", publish_text)
        self.assertIn("refs/tags/", publish_text)
        self.assertIn(".path", verify_text)
        self.assertIn(".github/workflows/distribution.yml", verify_text)
        self.assertIn("source_runtime_sha256", verify_text)
        self.assertIn("tree_digest", verify_text)

    def test_ci_keeps_python_matrix_and_runs_distribution_contract(self):
        text = self._read(".github/workflows/ci.yml")
        self.assertIn('python-version: ["3.12", "3.13"]', text)
        self.assertNotIn("id-token: write", text)
        self.assertNotIn("pypa/gh-action-pypi-publish", text)
        self.assertIn("tests.test_distribution", text)

    def test_release_process_documents_local_qualification_and_oidc_boundary(self):
        text = self._read("docs/RELEASE-PROCESS.md")
        for required in (
            "python -m pip install token-runtime",
            "uv tool install token-runtime",
            "SOURCE_DATE_EPOCH=1788998400",
            "TOKEN_DISTRIBUTION_PROVENANCE.json",
            "Trusted Publishing",
            "publish=false",
            "pypi",
            "attestations",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
