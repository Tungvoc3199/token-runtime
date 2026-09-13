from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json

from .anthropic_conformance import build_anthropic_conformance
from .capabilities import CapabilityKey
from .codex_recertification import build_codex_01540_recertification
from .compatibility import CompatibilityRecord, CompatibilityState
from .gemini_conformance import build_gemini_conformance
from .openai_certification import build_openai_certification


class OSFamily(str, Enum):
    LINUX = "linux"
    WINDOWS = "windows"
    MACOS = "macos"


class OSScopeKind(str, Enum):
    EXACT = "EXACT"
    TESTED_SET = "TESTED_SET"
    OS_AGNOSTIC = "OS_AGNOSTIC"


class UpgradeDimension(str, Enum):
    CLIENT_UI = "client_ui"
    CLIENT_VERSION = "client_version"
    SDK = "sdk"
    TOKENIZER = "tokenizer"
    CACHE_SEMANTICS = "cache_semantics"
    TOOL_SCHEMA = "tool_schema"
    OS_RUNTIME = "os_runtime"
    BENCHMARK_GENERATION = "benchmark_generation"
    PROTOCOL_WIRE = "protocol_wire"
    SECURITY_CRITICAL = "security_critical"


class UpgradeImpact(str, Enum):
    NO_ACTION = "NO_ACTION"
    REVIEW = "REVIEW"
    TARGETED_RECERTIFY = "TARGETED_RECERTIFY"
    FULL_RECERTIFY = "FULL_RECERTIFY"
    BLOCK = "BLOCK"


@dataclass(frozen=True, slots=True)
class BenchmarkGeneration:
    generation_id: str
    schema_version: int
    corpus_version: str
    evaluator_version: str
    policy_version: str
    evidence_digest: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.generation_id:
            raise ValueError("generation_id must be non-empty")
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")
        for name in (
            "corpus_version",
            "evaluator_version",
            "policy_version",
            "evidence_digest",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} must be non-empty")
        evidence = tuple(sorted(set(self.evidence_ids)))
        if not evidence or any(not item.strip() for item in evidence):
            raise ValueError("evidence_ids must contain non-blank values")
        object.__setattr__(self, "evidence_ids", evidence)
        encoded = json.dumps(list(evidence), separators=(",", ":")).encode("utf-8")
        if sha256(encoded).hexdigest() != self.evidence_digest:
            raise ValueError("evidence_digest does not match evidence_ids")

    def to_primitive(self) -> dict[str, object]:
        return {
            "generation_id": self.generation_id,
            "schema_version": self.schema_version,
            "corpus_version": self.corpus_version,
            "evaluator_version": self.evaluator_version,
            "policy_version": self.policy_version,
            "evidence_digest": self.evidence_digest,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, order=True, slots=True)
class CertificationTarget:
    client_family: str
    protocol_family: str
    provider_family: str
    model_family: str | None = None

    @classmethod
    def from_key(cls, key: CapabilityKey) -> "CertificationTarget":
        return cls(
            client_family=key.client_family,
            protocol_family=key.protocol_family,
            provider_family=key.provider_family,
            model_family=key.model_family,
        )

    def matches(self, key: CapabilityKey) -> bool:
        return (
            self.client_family == key.client_family
            and self.protocol_family == key.protocol_family
            and self.provider_family == key.provider_family
            and self.model_family == key.model_family
        )

    def to_primitive(self) -> dict[str, object]:
        return {
            "client_family": self.client_family,
            "protocol_family": self.protocol_family,
            "provider_family": self.provider_family,
            "model_family": self.model_family,
        }


@dataclass(frozen=True, slots=True)
class CertificationScope:
    target: CertificationTarget
    client_versions: tuple[str, ...] = ()
    os_scope: OSScopeKind = OSScopeKind.OS_AGNOSTIC
    os_families: tuple[OSFamily, ...] = ()

    def __post_init__(self) -> None:
        versions = tuple(sorted(set(self.client_versions)))
        families = tuple(sorted(set(self.os_families), key=lambda item: item.value))
        object.__setattr__(self, "client_versions", versions)
        object.__setattr__(self, "os_families", families)

        if not isinstance(self.os_scope, OSScopeKind):
            raise TypeError("os_scope must be OSScopeKind")
        if any(not version for version in versions):
            raise ValueError("client_versions must be non-empty strings")
        if self.os_scope is OSScopeKind.EXACT and len(families) != 1:
            raise ValueError("EXACT os scope requires exactly one OS family")
        if self.os_scope is OSScopeKind.TESTED_SET and not families:
            raise ValueError("TESTED_SET os scope requires at least one OS family")
        if self.os_scope is OSScopeKind.OS_AGNOSTIC and families:
            raise ValueError("OS_AGNOSTIC scope cannot enumerate OS families")

    def matches(self, key: CapabilityKey, os_family: OSFamily) -> bool:
        if not isinstance(os_family, OSFamily):
            return False
        if not self.target.matches(key):
            return False
        if self.client_versions:
            if key.client_version not in self.client_versions:
                return False
        elif key.client_version:
            return False

        if self.os_scope is OSScopeKind.OS_AGNOSTIC:
            return True
        return os_family in self.os_families

    def to_primitive(self) -> dict[str, object]:
        return {
            "target": self.target.to_primitive(),
            "client_versions": list(self.client_versions),
            "os_scope": self.os_scope.value,
            "os_families": [item.value for item in self.os_families],
        }


@dataclass(frozen=True, slots=True)
class CertificationEntry:
    scope: CertificationScope
    state: CompatibilityState
    evidence_ids: tuple[str, ...]
    benchmark_generation_id: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, CompatibilityState):
            raise TypeError("state must be CompatibilityState")
        evidence = tuple(sorted(set(self.evidence_ids)))
        if any(not item.strip() for item in evidence):
            raise ValueError("evidence_ids must contain non-blank values")
        object.__setattr__(self, "evidence_ids", evidence)

    def to_primitive(self) -> dict[str, object]:
        return {
            "scope": self.scope.to_primitive(),
            "state": self.state.value,
            "evidence_ids": list(self.evidence_ids),
            "benchmark_generation_id": self.benchmark_generation_id,
            "reason": self.reason,
        }


def _entry_sort_key(entry: CertificationEntry) -> tuple[object, ...]:
    target = entry.scope.target
    return (
        target.client_family,
        target.protocol_family,
        target.provider_family,
        target.model_family or "",
        entry.scope.client_versions,
        entry.scope.os_scope.value,
        tuple(item.value for item in entry.scope.os_families),
        entry.state.value,
        entry.evidence_ids,
        entry.benchmark_generation_id or "",
        entry.reason or "",
    )


@dataclass(frozen=True, slots=True)
class CertificationMatrix:
    entries: tuple[CertificationEntry, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(sorted(self.entries, key=_entry_sort_key)))

    def matches(
        self,
        key: CapabilityKey,
        os_family: OSFamily,
    ) -> tuple[CertificationEntry, ...]:
        return tuple(
            entry for entry in self.entries if entry.scope.matches(key, os_family)
        )

    def to_primitive(self) -> list[dict[str, object]]:
        return [entry.to_primitive() for entry in self.entries]


@dataclass(frozen=True, slots=True)
class UpgradeSignal:
    dimension: UpgradeDimension
    before: str
    after: str

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, UpgradeDimension):
            raise TypeError("dimension must be UpgradeDimension")


def _effective_evidence_id(entry: CertificationEntry) -> str:
    if not entry.evidence_ids:
        return "unknown"
    if len(entry.evidence_ids) == 1:
        return entry.evidence_ids[0]
    joined = "\n".join(entry.evidence_ids).encode("utf-8")
    return f"compat-cert:{sha256(joined).hexdigest()}"


def _passthrough(key: CapabilityKey, reason: str) -> CompatibilityRecord:
    return CompatibilityRecord(
        key=key,
        state=CompatibilityState.PASSTHROUGH_ONLY,
        evidence_id="unknown",
        reason=reason,
    )


class CompatibilityPolicy:
    _UPGRADE_IMPACT = {
        UpgradeDimension.CLIENT_UI: UpgradeImpact.REVIEW,
        UpgradeDimension.CLIENT_VERSION: UpgradeImpact.TARGETED_RECERTIFY,
        UpgradeDimension.SDK: UpgradeImpact.REVIEW,
        UpgradeDimension.TOKENIZER: UpgradeImpact.TARGETED_RECERTIFY,
        UpgradeDimension.CACHE_SEMANTICS: UpgradeImpact.TARGETED_RECERTIFY,
        UpgradeDimension.TOOL_SCHEMA: UpgradeImpact.TARGETED_RECERTIFY,
        UpgradeDimension.OS_RUNTIME: UpgradeImpact.TARGETED_RECERTIFY,
        UpgradeDimension.BENCHMARK_GENERATION: UpgradeImpact.TARGETED_RECERTIFY,
        UpgradeDimension.PROTOCOL_WIRE: UpgradeImpact.FULL_RECERTIFY,
        UpgradeDimension.SECURITY_CRITICAL: UpgradeImpact.BLOCK,
    }

    def __init__(self, generations: tuple[BenchmarkGeneration, ...]) -> None:
        by_id: dict[str, BenchmarkGeneration] = {}
        for generation in generations:
            existing = by_id.get(generation.generation_id)
            if existing is not None and existing != generation:
                raise ValueError(
                    f"conflicting benchmark generation: {generation.generation_id}"
                )
            by_id[generation.generation_id] = generation
        self._generations = by_id

    def resolve(
        self,
        matrix: CertificationMatrix,
        key: CapabilityKey,
        os_family: OSFamily,
        *,
        required_benchmark_generation_id: str | None = None,
    ) -> CompatibilityRecord:
        matches = matrix.matches(key, os_family)
        if not matches:
            return _passthrough(key, "unknown_capability")
        if len(matches) != 1:
            return _passthrough(key, "ambiguous_certification_scope")

        entry = matches[0]
        if entry.state is CompatibilityState.CERTIFIED:
            if not entry.evidence_ids:
                return _passthrough(key, "missing_certification_evidence")
            generation_id = entry.benchmark_generation_id
            if not generation_id:
                return _passthrough(key, "missing_benchmark_generation")
            generation = self._generations.get(generation_id)
            if generation is None:
                return _passthrough(key, "unknown_benchmark_generation")
            if not set(entry.evidence_ids).issubset(generation.evidence_ids):
                return _passthrough(key, "benchmark_evidence_mismatch")
            if (
                required_benchmark_generation_id is not None
                and required_benchmark_generation_id != generation_id
            ):
                return _passthrough(key, "benchmark_generation_mismatch")

        return CompatibilityRecord(
            key=key,
            state=entry.state,
            evidence_id=_effective_evidence_id(entry),
            reason=entry.reason,
        )

    def classify_upgrade(self, signal: UpgradeSignal) -> UpgradeImpact:
        if signal.before == signal.after:
            return UpgradeImpact.NO_ACTION
        return self._UPGRADE_IMPACT[signal.dimension]


@dataclass(frozen=True, slots=True)
class CompatibilityCertificationBundle:
    matrix: CertificationMatrix
    benchmark_generations: tuple[BenchmarkGeneration, ...]

    def resolve(
        self,
        key: CapabilityKey,
        os_family: OSFamily,
        *,
        required_benchmark_generation_id: str | None = None,
    ) -> CompatibilityRecord:
        return CompatibilityPolicy(self.benchmark_generations).resolve(
            self.matrix,
            key,
            os_family,
            required_benchmark_generation_id=required_benchmark_generation_id,
        )

    def to_primitive(self) -> dict[str, object]:
        generations = sorted(
            self.benchmark_generations,
            key=lambda item: item.generation_id,
        )
        return {
            "benchmark_generations": [item.to_primitive() for item in generations],
            "matrix": self.matrix.to_primitive(),
        }


def _scope_for_key(
    key: CapabilityKey,
    *,
    os_scope: OSScopeKind,
    os_families: tuple[OSFamily, ...] = (),
) -> CertificationScope:
    versions = (key.client_version,) if key.client_version else ()
    return CertificationScope(
        target=CertificationTarget.from_key(key),
        client_versions=versions,
        os_scope=os_scope,
        os_families=os_families,
    )


def _benchmark_generation(evidence_ids: tuple[str, ...]) -> BenchmarkGeneration:
    encoded = json.dumps(sorted(evidence_ids), separators=(",", ":")).encode("utf-8")
    return BenchmarkGeneration(
        generation_id="token-compat-cert-1:compat-v1",
        schema_version=1,
        corpus_version="c3-c6-conformance-v1",
        evaluator_version="token-conformance-v1",
        policy_version="compat-policy-v1",
        evidence_digest=sha256(encoded).hexdigest(),
        evidence_ids=tuple(sorted(evidence_ids)),
    )


def build_current_certification() -> CompatibilityCertificationBundle:
    openai = build_openai_certification()
    codex = build_codex_01540_recertification()
    anthropic = build_anthropic_conformance()
    gemini = build_gemini_conformance()

    certified_evidence_ids = tuple(
        sorted(
            {
                *(item.evidence_id for item in openai.evidence),
                codex.evidence.evidence_id,
            }
        )
    )
    generation = _benchmark_generation(certified_evidence_ids)
    entries: list[CertificationEntry] = []

    for record in openai.records:
        if record.key.client_family == "codex":
            scope = _scope_for_key(
                record.key,
                os_scope=OSScopeKind.EXACT,
                os_families=(OSFamily.LINUX,),
            )
        else:
            scope = _scope_for_key(
                record.key,
                os_scope=OSScopeKind.OS_AGNOSTIC,
            )
        entries.append(
            CertificationEntry(
                scope=scope,
                state=record.state,
                evidence_ids=(record.evidence_id,),
                benchmark_generation_id=generation.generation_id,
                reason=record.reason,
            )
        )

    entries.append(
        CertificationEntry(
            scope=_scope_for_key(
                codex.record.key,
                os_scope=OSScopeKind.EXACT,
                os_families=(OSFamily.LINUX,),
            ),
            state=codex.record.state,
            evidence_ids=(codex.record.evidence_id,),
            benchmark_generation_id=generation.generation_id,
            reason=codex.record.reason,
        )
    )

    for bundle in (anthropic, gemini):
        entries.append(
            CertificationEntry(
                scope=_scope_for_key(
                    bundle.record.key,
                    os_scope=OSScopeKind.OS_AGNOSTIC,
                ),
                state=bundle.record.state,
                evidence_ids=(bundle.record.evidence_id,),
                reason=bundle.record.reason,
            )
        )

    return CompatibilityCertificationBundle(
        matrix=CertificationMatrix(tuple(entries)),
        benchmark_generations=(generation,),
    )
