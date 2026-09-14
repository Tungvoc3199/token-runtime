import unittest

from token_runtime.adapters import ChatCompletionsAdapter, ResponsesAdapter
from token_runtime.protocol_registry import (
    DuplicateProtocolAdapterError,
    ProtocolAdapterRegistry,
    default_protocol_adapter_registry,
)


class ProtocolAdapterRegistryTests(unittest.TestCase):
    def test_default_registry_resolves_existing_endpoints(self):
        registry = default_protocol_adapter_registry()
        self.assertIsInstance(registry.resolve("/v1/responses"), ResponsesAdapter)
        self.assertIsInstance(
            registry.resolve("/v1/chat/completions"), ChatCompletionsAdapter
        )

    def test_query_string_is_ignored_for_endpoint_resolution(self):
        registry = default_protocol_adapter_registry()
        self.assertIsInstance(
            registry.resolve("/v1/chat/completions?trace=1"),
            ChatCompletionsAdapter,
        )

    def test_unknown_endpoint_resolves_to_none(self):
        self.assertIsNone(default_protocol_adapter_registry().resolve("/v1/future"))

    def test_duplicate_endpoint_registration_fails_closed(self):
        registry = ProtocolAdapterRegistry()
        registry.register("/v1/example", ResponsesAdapter)
        with self.assertRaises(DuplicateProtocolAdapterError):
            registry.register("/v1/example", ResponsesAdapter)
        with self.assertRaises(DuplicateProtocolAdapterError):
            registry.register("/v1/example", ChatCompletionsAdapter)


if __name__ == "__main__":
    unittest.main()
