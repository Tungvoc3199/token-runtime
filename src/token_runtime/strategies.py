from __future__ import annotations

from dataclasses import dataclass

from .compatibility import CompatibilityState


@dataclass(frozen=True, slots=True)
class StrategyDescriptor:
    strategy_id: str
    required_capabilities: tuple[str, ...]
    consider_states: frozenset[CompatibilityState]


class DuplicateStrategyError(ValueError):
    pass


TOKEN_DETERMINISTIC_V1 = StrategyDescriptor(
    strategy_id="token-deterministic-v1",
    required_capabilities=(),
    consider_states=frozenset(
        {CompatibilityState.CANARY, CompatibilityState.CERTIFIED}
    ),
)


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, StrategyDescriptor] = {}

    def register(self, strategy: StrategyDescriptor) -> StrategyDescriptor:
        existing = self._strategies.get(strategy.strategy_id)
        if existing is None:
            self._strategies[strategy.strategy_id] = strategy
            return strategy
        if existing == strategy:
            return existing
        raise DuplicateStrategyError(
            f"conflicting strategy descriptor: {strategy.strategy_id}"
        )

    def get(self, strategy_id: str) -> StrategyDescriptor | None:
        return self._strategies.get(strategy_id)

    def snapshot(self) -> tuple[StrategyDescriptor, ...]:
        return tuple(
            self._strategies[strategy_id]
            for strategy_id in sorted(self._strategies)
        )
