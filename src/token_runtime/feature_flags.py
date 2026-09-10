from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .compatibility import CompatibilityState


class FeatureFlagState(str, Enum):
    DISABLED = "disabled"
    SHADOW = "shadow"
    CANARY = "canary"
    ENABLED = "enabled"


class FeatureEffect(str, Enum):
    NONE = "none"
    OBSERVE = "observe"
    EXECUTE = "execute"


@dataclass(frozen=True, slots=True)
class FeatureFlag:
    name: str
    state: FeatureFlagState

    def __post_init__(self) -> None:
        if not isinstance(self.state, FeatureFlagState):
            raise TypeError("state must be FeatureFlagState")


class DuplicateFeatureFlagError(ValueError):
    pass


def permitted_effect(
    flag_state: FeatureFlagState,
    compatibility_state: CompatibilityState,
) -> FeatureEffect:
    if flag_state is FeatureFlagState.DISABLED:
        return FeatureEffect.NONE
    if compatibility_state in {
        CompatibilityState.BLOCKED,
        CompatibilityState.UNSUPPORTED,
    }:
        return FeatureEffect.NONE
    if flag_state is FeatureFlagState.SHADOW:
        return FeatureEffect.OBSERVE
    if flag_state is FeatureFlagState.CANARY:
        if compatibility_state in {
            CompatibilityState.CANARY,
            CompatibilityState.CERTIFIED,
        }:
            return FeatureEffect.EXECUTE
        return FeatureEffect.OBSERVE
    if compatibility_state is CompatibilityState.CERTIFIED:
        return FeatureEffect.EXECUTE
    return FeatureEffect.OBSERVE


class FeatureFlagRegistry:
    def __init__(self) -> None:
        self._flags: dict[str, FeatureFlag] = {}

    def register(self, flag: FeatureFlag) -> FeatureFlag:
        existing = self._flags.get(flag.name)
        if existing is None:
            self._flags[flag.name] = flag
            return flag
        if existing == flag:
            return existing
        raise DuplicateFeatureFlagError(f"conflicting feature flag: {flag.name}")

    def get(self, name: str) -> FeatureFlag:
        return self._flags.get(name, FeatureFlag(name, FeatureFlagState.DISABLED))

    def snapshot(self) -> tuple[FeatureFlag, ...]:
        return tuple(self._flags[name] for name in sorted(self._flags))
