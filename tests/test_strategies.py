import unittest

from token_runtime.compatibility import CompatibilityState
from token_runtime.strategies import (
    DuplicateStrategyError,
    StrategyDescriptor,
    StrategyRegistry,
    TOKEN_DETERMINISTIC_V1,
)


class StrategyTests(unittest.TestCase):
    def test_existing_strategy_descriptor_is_shadow_metadata_only(self):
        self.assertEqual(TOKEN_DETERMINISTIC_V1.strategy_id, "token-deterministic-v1")
        self.assertEqual(TOKEN_DETERMINISTIC_V1.required_capabilities, ())
        self.assertEqual(
            TOKEN_DETERMINISTIC_V1.consider_states,
            frozenset({CompatibilityState.CANARY, CompatibilityState.CERTIFIED}),
        )
        self.assertFalse(hasattr(TOKEN_DETERMINISTIC_V1, "execute"))
        self.assertFalse(hasattr(TOKEN_DETERMINISTIC_V1, "reduce"))

    def test_registry_is_idempotent_sorted_and_unknown_does_not_guess(self):
        registry = StrategyRegistry()
        later = StrategyDescriptor("z-strategy", (), frozenset({CompatibilityState.CERTIFIED}))
        earlier = StrategyDescriptor("a-strategy", (), frozenset({CompatibilityState.CANARY}))
        self.assertIs(registry.register(later), later)
        self.assertIs(registry.register(earlier), earlier)
        self.assertIs(registry.register(earlier), earlier)
        self.assertEqual(registry.snapshot(), (earlier, later))
        self.assertIs(registry.get("a-strategy"), earlier)
        self.assertIsNone(registry.get("missing"))

    def test_conflicting_duplicate_fails_closed(self):
        registry = StrategyRegistry()
        first = StrategyDescriptor("same", (), frozenset({CompatibilityState.CANARY}))
        registry.register(first)
        with self.assertRaises(DuplicateStrategyError):
            registry.register(
                StrategyDescriptor("same", (), frozenset({CompatibilityState.CERTIFIED}))
            )


if __name__ == "__main__":
    unittest.main()
