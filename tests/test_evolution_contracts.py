import unittest

from token_runtime.adapters import ResponsesAdapter
from token_runtime.contracts import (
    BenchmarkAdapterContract,
    CapabilityProviderContract,
    ClientAdapterContract,
    ProtocolAdapterContract,
    StrategyContract,
    TokenizerAdapterContract,
)


class ClientView:
    client_id = "codex"
    protocol_ids = ("responses",)


class ResponsesContractView:
    protocol_id = "responses"

    def parse(self, payload):
        return ResponsesAdapter().parse(payload)

    def serialize(self, envelope):
        return ResponsesAdapter().serialize(envelope)

class CapabilityProviderView:
    provider_id = "fixture-provider"

    def profile_for(self, key):
        return None


class TokenizerView:
    tokenizer_id = "fixture-tokenizer"

    def estimate(self, text):
        return len(text)


class StrategyView:
    strategy_id = "fixture-strategy"


class BenchmarkView:
    benchmark_id = "fixture-benchmark"
    assertion_ids = ("fixture-assertion",)


class EvolutionContractTests(unittest.TestCase):
    def test_runtime_checkable_contracts_accept_structural_implementations(self):
        self.assertIsInstance(ClientView(), ClientAdapterContract)
        self.assertIsInstance(ResponsesContractView(), ProtocolAdapterContract)
        self.assertIsInstance(CapabilityProviderView(), CapabilityProviderContract)
        self.assertIsInstance(TokenizerView(), TokenizerAdapterContract)
        self.assertIsInstance(StrategyView(), StrategyContract)
        self.assertIsInstance(BenchmarkView(), BenchmarkAdapterContract)

    def test_protocol_adapter_contract_round_trips_existing_response_fixture(self):
        payload = {"model": "fixture", "input": "current task"}
        adapter = ResponsesContractView()
        self.assertEqual(adapter.serialize(adapter.parse(payload)), payload)


if __name__ == "__main__":
    unittest.main()
