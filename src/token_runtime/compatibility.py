from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .capabilities import CapabilityKey


class CompatibilityState(str, Enum):
    CERTIFIED = "CERTIFIED"
    CANARY = "CANARY"
    EXPERIMENTAL = "EXPERIMENTAL"
    PASSTHROUGH_ONLY = "PASSTHROUGH_ONLY"
    UNSUPPORTED = "UNSUPPORTED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class CompatibilityRecord:
    key: CapabilityKey
    state: CompatibilityState
    evidence_id: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, CompatibilityState):
            raise TypeError("state must be CompatibilityState")


class DuplicateCompatibilityError(ValueError):
    pass

def _unknown_record(key: CapabilityKey) -> CompatibilityRecord:
    return CompatibilityRecord(
        key=key,
        state=CompatibilityState.PASSTHROUGH_ONLY,
        evidence_id="unknown",
        reason="unknown_capability",
    )


@dataclass(frozen=True, slots=True)
class CompatibilityMatrix:
    records: tuple[CompatibilityRecord, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "records",
            tuple(sorted(self.records, key=lambda record: record.key)),
        )

    def get(self, key: CapabilityKey) -> CompatibilityRecord:
        for record in self.records:
            if record.key == key:
                return record
        return _unknown_record(key)

class CompatibilityRegistry:
    def __init__(self) -> None:
        self._records: dict[CapabilityKey, CompatibilityRecord] = {}

    def register(self, record: CompatibilityRecord) -> CompatibilityRecord:
        existing = self._records.get(record.key)
        if existing is None:
            self._records[record.key] = record
            return record
        if existing == record:
            return existing
        raise DuplicateCompatibilityError(
            f"conflicting compatibility record: {record.key!r}"
        )

    def get(self, key: CapabilityKey) -> CompatibilityRecord:
        return self._records.get(key, _unknown_record(key))

    def snapshot(self) -> tuple[CompatibilityRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    def matrix(self) -> CompatibilityMatrix:
        return CompatibilityMatrix(self.snapshot())
