from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import sys
import tarfile
import tomllib
import zipfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

if __package__:
    from .public_release import build_public_release, tree_digest
else:
    from public_release import build_public_release, tree_digest

_RELEASE_LABEL_RE = re.compile(r"v([0-9]+)\.([0-9]+)\.([0-9]+)-alpha\.([0-9]+)")
_PEP440_ALPHA_RE = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)a([0-9]+)")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_PACKAGE_NAME = "token-runtime"
_SANITIZER_CONTRACT_VERSION = 1
_BUILD_WHEEL_REQUIREMENT = "wheel==0.46.3"

@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    filename: str
    sha256: str
    size: int
    kind: str
    metadata_name: str
    metadata_version: str

def normalize_release_label(label: str) -> str:
    match = _RELEASE_LABEL_RE.fullmatch(label)
    if match is None:
        raise ValueError(f"unsupported release label: {label}")
    major, minor, patch, alpha = match.groups()
    return f"{major}.{minor}.{patch}a{alpha}"

def release_label_for_version(version: str) -> str:
    match = _PEP440_ALPHA_RE.fullmatch(version)
    if match is None:
        raise ValueError(f"unsupported package version: {version}")
    major, minor, patch, alpha = match.groups()
    return f"v{major}.{minor}.{patch}-alpha.{alpha}"

def read_project_identity(candidate: Path) -> tuple[str, str]:
    try:
        data = tomllib.loads((Path(candidate) / "pyproject.toml").read_text(encoding="utf-8"))
        project = data["project"]
        name = project["name"]
        version = project["version"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        raise ValueError("invalid project metadata") from None
    if not isinstance(name, str) or not isinstance(version, str):
        raise ValueError("invalid project metadata")
    return name, version

def validate_version_contract(candidate: Path, manifest: Mapping[str, object]) -> tuple[str, str]:
    name, package_version = read_project_identity(candidate)
    if name != _PACKAGE_NAME:
        raise ValueError(f"unexpected package name: {name}")
    release_label = manifest.get("release_version")
    if not isinstance(release_label, str):
        raise ValueError("release manifest has invalid release_version")
    normalized = normalize_release_label(release_label)
    if normalized != package_version:
        raise ValueError("release/package version mismatch: " f"release={release_label} normalized={normalized} package={package_version}")
    return name, package_version

def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _expected_artifact_names(name: str, version: str) -> tuple[str, str]:
    normalized_name = name.replace("-", "_")
    return f"{normalized_name}-{version}-py3-none-any.whl", f"{normalized_name}-{version}.tar.gz"

def _validate_archive_member(name: str) -> None:
    member = PurePosixPath(name)
    if member.is_absolute() or ".." in member.parts:
        raise ValueError("unsafe archive member traversal")

def _metadata_identity(raw: bytes, kind: str) -> tuple[str, str]:
    try:
        parsed = BytesParser().parsebytes(raw)
        name = parsed["Name"]
        version = parsed["Version"]
    except Exception:
        raise ValueError(f"invalid {kind} metadata") from None
    if not isinstance(name, str) or not isinstance(version, str):
        raise ValueError(f"invalid {kind} metadata identity")
    return name, version

def _inspect_wheel(path: Path) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            for name in names:
                _validate_archive_member(name)
            metadata = [name for name in names if PurePosixPath(name).name == "METADATA" and PurePosixPath(name).parent.name.endswith(".dist-info")]
            if len(metadata) != 1:
                raise ValueError("wheel must contain exactly one METADATA")
            return _metadata_identity(archive.read(metadata[0]), "wheel")
    except (OSError, zipfile.BadZipFile, KeyError):
        raise ValueError("invalid wheel artifact") from None

def _inspect_sdist(path: Path) -> tuple[str, str]:
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            for member in members:
                _validate_archive_member(member.name)
            metadata = [
                member
                for member in members
                if PurePosixPath(member.name).name == "PKG-INFO"
                and len(PurePosixPath(member.name).parts) == 2
                and member.isfile()
            ]
            if len(metadata) != 1:
                raise ValueError("sdist must contain exactly one PKG-INFO")
            extracted = archive.extractfile(metadata[0])
            if extracted is None:
                raise ValueError("invalid sdist PKG-INFO")
            return _metadata_identity(extracted.read(), "sdist")
    except (OSError, tarfile.TarError):
        raise ValueError("invalid sdist artifact") from None

def inspect_distributions(dist: Path, expected_name: str, expected_version: str) -> tuple[ArtifactRecord, ArtifactRecord]:
    dist = Path(dist)
    wheel_name, sdist_name = _expected_artifact_names(expected_name, expected_version)
    try:
        actual = tuple(sorted(item.name for item in dist.iterdir()))
    except OSError:
        raise ValueError("distribution output unavailable") from None
    if actual != tuple(sorted((wheel_name, sdist_name))):
        raise ValueError("distribution artifacts do not match exact expected filenames")
    wheel = dist / wheel_name
    sdist = dist / sdist_name
    if not wheel.is_file() or not sdist.is_file():
        raise ValueError("distribution artifact is not a regular file")
    wheel_identity = _inspect_wheel(wheel)
    sdist_identity = _inspect_sdist(sdist)
    for kind, identity in (("wheel", wheel_identity), ("sdist", sdist_identity)):
        if identity != (expected_name, expected_version):
            raise ValueError(f"{kind} metadata identity mismatch: name={identity[0]} version={identity[1]}")
    return (
        ArtifactRecord(wheel.name, _sha256_file(wheel), wheel.stat().st_size, "wheel", wheel_identity[0], wheel_identity[1]),
        ArtifactRecord(sdist.name, _sha256_file(sdist), sdist.stat().st_size, "sdist", sdist_identity[0], sdist_identity[1]),
    )

def build_candidate(source: Path, candidate: Path, release_label: str) -> Mapping[str, object]:
    manifest = build_public_release(Path(source), Path(candidate), release_label)
    validate_version_contract(Path(candidate), manifest)
    return manifest

def _normalize_candidate_mtimes(candidate: Path, source_date_epoch: int) -> None:
    for path in sorted(Path(candidate).rglob("*")):
        if path.is_file() or path.is_dir():
            os.utime(path, (source_date_epoch, source_date_epoch), follow_symlinks=False)

def _normalize_sdist_archive(path: Path, source_date_epoch: int) -> None:
    entries = []
    try:
        with tarfile.open(path, "r:gz") as source:
            for member in source.getmembers():
                _validate_archive_member(member.name)
                normalized = copy.copy(member)
                normalized.mtime = source_date_epoch
                normalized.uid = 0
                normalized.gid = 0
                normalized.uname = ""
                normalized.gname = ""
                normalized.pax_headers = {}
                payload = None
                if member.isfile():
                    extracted = source.extractfile(member)
                    if extracted is None:
                        raise ValueError("invalid sdist member payload")
                    payload = extracted.read()
                entries.append((normalized, payload))
    except (OSError, tarfile.TarError):
        raise ValueError("invalid sdist artifact") from None

    temp_path = path.with_name(path.name + ".tmp")
    try:
        with temp_path.open("wb") as raw:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw,
                mtime=source_date_epoch,
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed,
                    mode="w",
                    format=tarfile.PAX_FORMAT,
                ) as target:
                    for member, payload in entries:
                        target.addfile(
                            member,
                            io.BytesIO(payload) if payload is not None else None,
                        )
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def build_distributions(candidate: Path, dist: Path, source_date_epoch: int) -> tuple[ArtifactRecord, ArtifactRecord]:
    if isinstance(source_date_epoch, bool) or not isinstance(source_date_epoch, int):
        raise ValueError("source date epoch must be an integer")
    candidate = Path(candidate).resolve()
    dist = Path(dist).resolve()
    if dist.exists():
        if not dist.is_dir() or any(dist.iterdir()):
            raise ValueError("distribution output directory must be empty")
    else:
        dist.mkdir(parents=True)
    _normalize_candidate_mtimes(candidate, source_date_epoch)
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = str(source_date_epoch)
    subprocess.run([sys.executable, "-m", "build", "--wheel", "--sdist", "--no-isolation", "--outdir", str(dist)], cwd=candidate, env=env, check=True)
    if (candidate / "pyproject.toml").is_file():
        expected_name, expected_version = read_project_identity(candidate)
    else:
        names = sorted(item.name for item in dist.iterdir())
        wheel_prefix = _PACKAGE_NAME.replace("-", "_") + "-"
        wheel_suffix = "-py3-none-any.whl"
        wheel_names = [name for name in names if name.startswith(wheel_prefix) and name.endswith(wheel_suffix)]
        if len(wheel_names) != 1:
            raise ValueError("distribution artifact version cannot be determined")
        expected_name = _PACKAGE_NAME
        expected_version = wheel_names[0][len(wheel_prefix):-len(wheel_suffix)]
    _, sdist_name = _expected_artifact_names(expected_name, expected_version)
    _normalize_sdist_archive(dist / sdist_name, source_date_epoch)
    return inspect_distributions(dist, expected_name, expected_version)

def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"invalid {field} digest")
    return value

def _manifest_digest(manifest: Mapping[str, object]) -> str:
    rendered = json.dumps(dict(manifest), indent=2, sort_keys=True) + "\n"
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()

def _artifact_dicts(artifacts: tuple[ArtifactRecord, ArtifactRecord]) -> list[dict[str, object]]:
    return [asdict(record) for record in sorted(artifacts, key=lambda item: item.filename)]

def write_release_bundle(bundle: Path, manifest: Mapping[str, object], artifacts: tuple[ArtifactRecord, ArtifactRecord], source_runtime_sha256: str, candidate_runtime_sha256: str, source_date_epoch: int) -> Path:
    bundle = Path(bundle)
    if source_runtime_sha256 != candidate_runtime_sha256:
        raise ValueError("source and candidate runtime digests must be equal")
    _require_sha256(source_runtime_sha256, "source runtime")
    _require_sha256(candidate_runtime_sha256, "candidate runtime")
    if isinstance(source_date_epoch, bool) or not isinstance(source_date_epoch, int):
        raise ValueError("source date epoch must be an integer")
    if manifest.get("sanitizer_contract_version") != _SANITIZER_CONTRACT_VERSION:
        raise ValueError("unsupported sanitizer contract version")
    release_label = manifest.get("release_version")
    if not isinstance(release_label, str):
        raise ValueError("release manifest has invalid release_version")
    normalized_version = normalize_release_label(release_label)
    runtime_digest = _require_sha256(manifest.get("runtime_tree_sha256"), "manifest runtime")
    if runtime_digest != candidate_runtime_sha256:
        raise ValueError("manifest and candidate runtime digest mismatch")
    public_payload_sha256 = _require_sha256(manifest.get("public_payload_sha256"), "public payload")
    ordered = tuple(sorted(artifacts, key=lambda item: item.filename))
    if len(ordered) != 2 or {item.kind for item in ordered} != {"wheel", "sdist"}:
        raise ValueError("release bundle requires exactly one wheel and one sdist")
    if {item.metadata_name for item in ordered} != {_PACKAGE_NAME} or {item.metadata_version for item in ordered} != {normalized_version}:
        raise ValueError("artifact metadata does not match release identity")
    dist = bundle / "dist"
    if not dist.is_dir():
        raise ValueError("release bundle distribution directory unavailable")
    inspected = inspect_distributions(dist, _PACKAGE_NAME, normalized_version)
    if {item.filename: item for item in inspected} != {item.filename: item for item in ordered}:
        raise ValueError("artifact records do not match distribution files")
    sums = "".join(f"{record.sha256}  {record.filename}\n" for record in sorted(ordered, key=lambda item: item.filename))
    (bundle / "SHA256SUMS").write_text(sums, encoding="utf-8")
    provenance = {
        "schema_version": 1,
        "distribution_name": _PACKAGE_NAME,
        "package_version": normalized_version,
        "release_label": release_label,
        "normalized_version": normalized_version,
        "sanitizer_contract_version": _SANITIZER_CONTRACT_VERSION,
        "source_runtime_sha256": source_runtime_sha256,
        "candidate_runtime_sha256": candidate_runtime_sha256,
        "public_payload_sha256": public_payload_sha256,
        "public_release_manifest_sha256": _manifest_digest(manifest),
        "source_date_epoch": source_date_epoch,
        "artifacts": _artifact_dicts(ordered),
        "qualification_assertions": {"artifact_count_exact": True, "artifact_metadata_verified": True, "runtime_digests_equal": True, "sanitizer_contract_supported": True, "version_contract_verified": True},
    }
    provenance_path = bundle / "TOKEN_DISTRIBUTION_PROVENANCE.json"
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return provenance_path

def _read_provenance(bundle: Path) -> dict[str, object]:
    try:
        value = json.loads((bundle / "TOKEN_DISTRIBUTION_PROVENANCE.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("release provenance unavailable or invalid") from None
    if not isinstance(value, dict):
        raise ValueError("release provenance must be an object")
    return value

def verify_release_bundle(bundle: Path) -> Mapping[str, object]:
    bundle = Path(bundle)
    try:
        root_names = tuple(sorted(item.name for item in bundle.iterdir()))
    except OSError:
        raise ValueError("release bundle unavailable") from None
    if root_names != tuple(sorted(("SHA256SUMS", "TOKEN_DISTRIBUTION_PROVENANCE.json", "dist"))):
        raise ValueError("missing or unexpected release bundle files")
    provenance = _read_provenance(bundle)
    if provenance.get("schema_version") != 1:
        raise ValueError("unsupported release provenance schema")
    if provenance.get("distribution_name") != _PACKAGE_NAME:
        raise ValueError("release provenance distribution name mismatch")
    version = provenance.get("package_version")
    release_label = provenance.get("release_label")
    if not isinstance(version, str) or not isinstance(release_label, str):
        raise ValueError("release provenance version metadata invalid")
    if normalize_release_label(release_label) != version or provenance.get("normalized_version") != version:
        raise ValueError("release provenance version mismatch")
    if provenance.get("sanitizer_contract_version") != _SANITIZER_CONTRACT_VERSION:
        raise ValueError("release provenance sanitizer contract mismatch")
    source_runtime = _require_sha256(provenance.get("source_runtime_sha256"), "source runtime")
    candidate_runtime = _require_sha256(provenance.get("candidate_runtime_sha256"), "candidate runtime")
    if source_runtime != candidate_runtime:
        raise ValueError("release provenance runtime digest mismatch")
    _require_sha256(provenance.get("public_payload_sha256"), "public payload")
    _require_sha256(provenance.get("public_release_manifest_sha256"), "public release manifest")
    artifacts = inspect_distributions(bundle / "dist", _PACKAGE_NAME, version)
    if provenance.get("artifacts") != _artifact_dicts(artifacts):
        raise ValueError("artifact metadata or digest disagrees with provenance")
    expected_sums = "".join(f"{record.sha256}  {record.filename}\n" for record in sorted(artifacts, key=lambda item: item.filename))
    try:
        sums = (bundle / "SHA256SUMS").read_text(encoding="utf-8")
    except OSError:
        raise ValueError("checksum file unavailable") from None
    if sums != expected_sums:
        raise ValueError("checksum digest mismatch")
    assertions = provenance.get("qualification_assertions")
    if not isinstance(assertions, dict) or not assertions or any(value is not True for value in assertions.values()):
        raise ValueError("release provenance qualification assertions invalid")
    return provenance

def _require_qualification_root(root: Path) -> Path:
    resolved = Path(root).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if resolved == Path.home().resolve() or not resolved.is_relative_to(temp_root):
        raise ValueError("qualification root must be temporary and outside the real home")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _qualification_env(root: Path) -> dict[str, str]:
    resolved = _require_qualification_root(root)
    home = resolved / "home"
    pip_cache = resolved / "pip-cache"
    xdg_cache = resolved / "xdg-cache"
    temp_dir = resolved / "tmp"
    for directory in (home, pip_cache, xdg_cache, temp_dir):
        directory.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR"}}
    env.pop("PYTHONPATH", None)
    env.update({"HOME": str(home), "PIP_CACHE_DIR": str(pip_cache), "PYTHONNOUSERSITE": "1", "XDG_CACHE_HOME": str(xdg_cache), "TMPDIR": str(temp_dir)})
    return env


def _create_venv(venv: Path) -> tuple[Path, Path, Path]:
    venv = Path(venv).resolve()
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, stdin=subprocess.DEVNULL)
    python = venv / "bin" / "python"
    pip = venv / "bin" / "pip"
    token = venv / "bin" / "token"
    if not python.exists() or not pip.exists() or not python.is_absolute() or not pip.is_absolute():
        raise ValueError("qualification virtual environment tools unavailable")
    return python, pip, token


def _pip_install(pip: Path, command: list[str], env: Mapping[str, str]) -> None:
    pip = Path(pip)
    if not pip.is_absolute():
        raise ValueError("qualification pip must be absolute")
    rendered = [str(item) for item in command]
    if "-e" in rendered or "--editable" in rendered:
        raise ValueError("editable installation is forbidden")
    subprocess.run([str(pip), *rendered], check=True, env=dict(env), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def installed_smoke(python: Path, token: Path, expected_version: str, env: Mapping[str, str]) -> None:
    python = Path(python)
    token = Path(token)
    if not python.is_absolute() or not token.is_absolute():
        raise ValueError("qualification smoke tools must be absolute")
    cwd = Path(env["HOME"])
    metadata = subprocess.run([str(python), "-c", "import importlib.metadata as m; import token_runtime; print(m.version('token-runtime'))"], check=True, env=dict(env), cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if metadata.stdout.strip() != expected_version:
        raise ValueError("installed metadata version mismatch")
    help_result = subprocess.run([str(token), "--help"], check=True, env=dict(env), cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if "usage:" not in help_result.stdout.lower():
        raise ValueError("installed token help smoke failed")
    welcome = subprocess.run([str(token)], check=True, env=dict(env), cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if release_label_for_version(expected_version) not in welcome.stdout:
        raise ValueError("installed token welcome version mismatch")


def qualify_pip_wheel(wheel: Path, expected_version: str, root: Path) -> None:
    root = _require_qualification_root(root)
    python, pip, token = _create_venv(root / "venv")
    env = _qualification_env(root / "state")
    _pip_install(pip, ["install", "--no-deps", "--no-index", str(Path(wheel).resolve())], env)
    installed_smoke(python, token, expected_version, env)

def _build_wheelhouse() -> Path:
    raw = os.environ.get("TOKEN_DISTRIBUTION_BUILD_WHEELHOUSE")
    if not raw:
        raise ValueError("controlled build wheelhouse unavailable")
    wheelhouse = Path(raw).resolve()
    if not wheelhouse.is_dir():
        raise ValueError("controlled build wheelhouse unavailable")
    return wheelhouse


def qualify_pip_sdist(sdist: Path, expected_version: str, root: Path) -> None:
    root = _require_qualification_root(root)
    wheelhouse = _build_wheelhouse()
    python, pip, token = _create_venv(root / "venv")
    env = _qualification_env(root / "state")
    _pip_install(pip, ["install", "--no-index", "--find-links", str(wheelhouse), "setuptools==84.0.0", _BUILD_WHEEL_REQUIREMENT], env)
    _pip_install(pip, ["install", "--no-deps", "--no-index", "--no-build-isolation", str(Path(sdist).resolve())], env)
    installed_smoke(python, token, expected_version, env)


def qualify_uv_tool(wheel: Path, expected_version: str, root: Path, python: Path) -> None:
    root = _require_qualification_root(root)
    uv_raw = shutil.which("uv")
    if not uv_raw:
        raise ValueError("uv unavailable for qualification")
    uv = Path(uv_raw).resolve()
    python = Path(python)
    if not python.is_absolute():
        raise ValueError("uv python must be absolute")
    env = _qualification_env(root / "state")
    tool_dir = root / "uv-tools"
    bin_dir = root / "uv-bin"
    tool_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)
    env["UV_TOOL_DIR"] = str(tool_dir)
    env["UV_TOOL_BIN_DIR"] = str(bin_dir)
    subprocess.run([str(uv), "tool", "install", "--offline", "--no-cache", "--python", str(python), str(Path(wheel).resolve())], check=True, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    token = bin_dir / "token"
    tool_python = tool_dir / _PACKAGE_NAME / "bin" / "python"
    installed_smoke(tool_python, token, expected_version, env)

def build_synthetic_previous(dist: Path, source_date_epoch: int) -> Path:
    dist = _require_qualification_root(dist)
    if any(dist.iterdir()):
        raise ValueError("synthetic prior output directory must be empty")
    source = dist.parent / (dist.name + "-source")
    if source.exists():
        shutil.rmtree(source)
    package = source / "src" / "token_runtime"
    package.mkdir(parents=True)
    (source / "pyproject.toml").write_text(
        "[build-system]\nrequires = [\"setuptools==84.0.0\"]\nbuild-backend = \"setuptools.build_meta\"\n\n"
        "[project]\nname = \"token-runtime\"\nversion = \"0.1.0a1\"\nrequires-python = \">=3.12\"\ndependencies = []\n\n"
        "[project.scripts]\ntoken = \"token_runtime.cli:main\"\n\n[tool.setuptools.packages.find]\nwhere = [\"src\"]\n",
        encoding="utf-8",
    )
    (package / "__init__.py").write_text('__version__ = "0.1.0a1"\n', encoding="utf-8")
    (package / "cli.py").write_text(
        "import argparse\n\ndef main(argv=None):\n    parser = argparse.ArgumentParser(prog='token')\n    parser.parse_args(argv)\n    print('TOKEN v0.1.0-alpha.1')\n    return 0\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["SOURCE_DATE_EPOCH"] = str(source_date_epoch)
    subprocess.run([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(dist)], cwd=source, check=True, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    expected = dist / "token_runtime-0.1.0a1-py3-none-any.whl"
    if not expected.is_file():
        raise ValueError("synthetic prior wheel missing")
    with zipfile.ZipFile(expected) as archive:
        metadata_members = []
        for member in archive.namelist():
            _validate_archive_member(member)
            if member.endswith(".dist-info/METADATA"):
                metadata_members.append(member)
        if len(metadata_members) != 1:
            raise ValueError("synthetic prior wheel metadata invalid")
        name, version = _metadata_identity(archive.read(metadata_members[0]), "wheel")
    if (name, version) != (_PACKAGE_NAME, "0.1.0a1"):
        raise ValueError("synthetic prior wheel identity invalid")
    return expected


def qualify_upgrade_rollback(previous_wheel: Path, candidate_wheel: Path, root: Path) -> None:
    root = _require_qualification_root(root)
    previous_wheel = Path(previous_wheel).resolve()
    candidate_wheel = Path(candidate_wheel).resolve()
    previous_name, previous_version = _inspect_wheel(previous_wheel)
    candidate_name, candidate_version = _inspect_wheel(candidate_wheel)
    if previous_name != _PACKAGE_NAME or candidate_name != _PACKAGE_NAME:
        raise ValueError("upgrade/rollback package identity mismatch")
    python, pip, token = _create_venv(root / "venv")
    env = _qualification_env(root / "state")
    stages = (
        ("prior", ["install", "--no-deps", "--no-index", "--force-reinstall", str(previous_wheel)], previous_version),
        ("upgrade", ["install", "--no-deps", "--no-index", "--upgrade", "--force-reinstall", str(candidate_wheel)], candidate_version),
        ("rollback", ["install", "--no-deps", "--no-index", "--force-reinstall", str(previous_wheel)], previous_version),
    )
    for stage, command, version in stages:
        try:
            _pip_install(pip, command, env)
            installed_smoke(python, token, version, env)
        except Exception as exc:
            raise ValueError(f"{stage} qualification failed") from exc


def _qualify_bundle(bundle: Path, previous_wheel: Path, work_root: Path) -> None:
    provenance = verify_release_bundle(bundle)
    version = provenance.get("package_version")
    if not isinstance(version, str):
        raise ValueError("release bundle version unavailable")
    records = inspect_distributions(bundle / "dist", _PACKAGE_NAME, version)
    by_kind = {record.kind: record for record in records}
    wheel = bundle / "dist" / by_kind["wheel"].filename
    sdist = bundle / "dist" / by_kind["sdist"].filename
    work_root = _require_qualification_root(work_root)
    qualify_pip_wheel(wheel, version, work_root / "pip-wheel")
    qualify_pip_sdist(sdist, version, work_root / "pip-sdist")
    qualify_uv_tool(wheel, version, work_root / "uv-tool", Path(sys.executable).resolve())
    qualify_upgrade_rollback(previous_wheel, wheel, work_root / "upgrade-rollback")


def _prior_fixture_cli(dist: Path) -> int:
    try:
        wheel = build_synthetic_previous(dist, _source_date_epoch())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"prior fixture build failed: {exc}", file=sys.stderr)
        return 1
    print(str(wheel))
    return 0


def _qualify_cli(bundle: Path, previous_wheel: Path, work_root: Path) -> int:
    try:
        _qualify_bundle(bundle, previous_wheel, work_root)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"distribution qualification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"qualified": True}, sort_keys=True))
    return 0

def _source_date_epoch() -> int:
    raw = os.environ.get("SOURCE_DATE_EPOCH")
    if raw is None or not raw.isdigit():
        raise ValueError("SOURCE_DATE_EPOCH must be an integer")
    return int(raw)

def _contract(candidate: Path) -> int:
    try:
        try:
            manifest_raw = (candidate / "PUBLIC_RELEASE_MANIFEST.json").read_text(encoding="utf-8")
        except OSError:
            raise ValueError("release manifest unavailable") from None
        try:
            manifest = json.loads(manifest_raw)
        except json.JSONDecodeError:
            raise ValueError("release manifest is invalid JSON") from None
        if not isinstance(manifest, dict):
            raise ValueError("release manifest must be an object")
        name, version = validate_version_contract(candidate, manifest)
    except ValueError as exc:
        print(f"distribution contract failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"name": name, "version": version}, sort_keys=True))
    return 0

def _build_cli(source: Path, candidate: Path, bundle: Path, release_label: str) -> int:
    try:
        manifest = build_candidate(source, candidate, release_label)
        name, version = validate_version_contract(candidate, manifest)
        epoch = _source_date_epoch()
        artifacts = build_distributions(candidate, bundle / "dist", epoch)
        source_runtime = tree_digest(Path(source) / "src" / "token_runtime")
        candidate_runtime = tree_digest(Path(candidate) / "src" / "token_runtime")
        write_release_bundle(bundle, manifest, artifacts, source_runtime, candidate_runtime, epoch)
        verify_release_bundle(bundle)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"distribution build failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"name": name, "version": version, "verified": True}, sort_keys=True))
    return 0

def _verify_cli(bundle: Path) -> int:
    try:
        provenance = verify_release_bundle(bundle)
    except ValueError as exc:
        print(f"distribution verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(provenance, sort_keys=True))
    return 0

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="distribution.py")
    subparsers = parser.add_subparsers(dest="command", required=True)
    contract = subparsers.add_parser("contract")
    contract.add_argument("--candidate", type=Path, required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--source", type=Path, required=True)
    build.add_argument("--candidate", type=Path, required=True)
    build.add_argument("--bundle", type=Path, required=True)
    build.add_argument("--release-label", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    prior = subparsers.add_parser("prior-fixture")
    prior.add_argument("--dist", type=Path, required=True)
    qualify = subparsers.add_parser("qualify")
    qualify.add_argument("--bundle", type=Path, required=True)
    qualify.add_argument("--previous-wheel", type=Path, required=True)
    qualify.add_argument("--work-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "contract":
        return _contract(args.candidate)
    if args.command == "build":
        return _build_cli(args.source, args.candidate, args.bundle, args.release_label)
    if args.command == "verify":
        return _verify_cli(args.bundle)
    if args.command == "prior-fixture":
        return _prior_fixture_cli(args.dist)
    if args.command == "qualify":
        return _qualify_cli(args.bundle, args.previous_wheel, args.work_root)
    raise AssertionError("unreachable")

if __name__ == "__main__":
    raise SystemExit(main())
