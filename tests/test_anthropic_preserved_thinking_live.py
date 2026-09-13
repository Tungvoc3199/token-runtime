import importlib.util
from decimal import Decimal
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "benchmarks" / "run_anthropic_preserved_thinking_live.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("anthropic_pt_live", RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load live runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AnthropicPreservedThinkingLiveTests(unittest.TestCase):
    def test_budget_guard_caps_owner_spend_and_request_shape(self):
        live = _load_runner()
        live.validate_budget(Decimal("0.50"), max_requests=4, max_tokens=256)
        with self.assertRaises(ValueError):
            live.validate_budget(Decimal("1.01"), max_requests=4, max_tokens=256)
        with self.assertRaises(ValueError):
            live.validate_budget(Decimal("0.50"), max_requests=5, max_tokens=256)

    def test_sanitizer_never_persists_raw_thinking_or_auth_material(self):
        live = _load_runner()
        response = {
            "id": "msg_fixture",
            "model": "claude-fable-5-1",
            "stop_reason": "tool_use",
            "content": [
                {"type": "thinking", "thinking": "raw-secret", "signature": "sig-secret"},
                {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {"q": "secret"}},
            ],
            "usage": {"input_tokens": 100, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 20},
        }
        safe = live.sanitize_response(response, request_sha256="abc")
        rendered = repr(safe)
        self.assertNotIn("raw-secret", rendered)
        self.assertNotIn("sig-secret", rendered)
        self.assertNotIn("secret", rendered)
        self.assertEqual(safe["content_types"], ["thinking", "tool_use"])

    def test_cost_estimate_uses_fable_51_rates_and_cache_counters(self):
        live = _load_runner()
        usage = {
            "input_tokens": 1000,
            "cache_creation_input_tokens": 1000,
            "cache_read_input_tokens": 1000,
            "output_tokens": 1000,
        }
        self.assertEqual(live.estimate_cost_usd(usage), Decimal("0.07275"))

    def test_sequence_has_no_blind_retry_after_transport_failure(self):
        live = _load_runner()
        calls = []

        def transport(payload):
            calls.append(payload)
            if len(calls) == 2:
                raise RuntimeError("fixture failure")
            return {"model": "claude-fable-5-1", "content": [], "usage": {}}

        with self.assertRaises(RuntimeError):
            live.execute_sequence([{"n": 1}, {"n": 2}, {"n": 3}], transport)
        self.assertEqual(len(calls), 2)

    def test_cache_hit_requires_positive_provider_counter(self):
        live = _load_runner()
        self.assertFalse(live.cache_hit_observed([{"usage": {"cache_read_input_tokens": 0}}]))
        self.assertTrue(live.cache_hit_observed([{"usage": {"cache_read_input_tokens": 9}}]))

    def test_accounting_does_not_expose_cost_report_attribution(self):
        live = _load_runner()
        self.assertFalse(hasattr(live, "cost_report_delta_usd"))
        self.assertFalse(hasattr(live, "_get_cost_report"))


class AnthropicPreservedThinkingSequenceTests(unittest.TestCase):
    def test_seed_request_is_bounded_cacheable_and_low_effort(self):
        live = _load_runner()
        payload = live.build_seed_request(max_tokens=192)
        self.assertEqual(payload["model"], "claude-fable-5-1")
        self.assertEqual(payload["max_tokens"], 192)
        self.assertEqual(payload["output_config"], {"effort": "low"})
        self.assertEqual(payload["thinking"]["type"], "adaptive")
        self.assertEqual(payload["thinking"]["display"], "summarized")
        self.assertEqual(
            payload["thinking"]["block_binding"],
            {"prefix_mismatch_behavior": "drop_block"},
        )
        self.assertNotIn("tool_choice", payload)
        self.assertGreater(len(payload["system"][0]["text"]), 3000)
        self.assertEqual(payload["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(len(payload["tools"]), 1)

    def test_resume_replays_assistant_content_exactly_and_links_tool_result(self):
        live = _load_runner()
        seed = live.build_seed_request(max_tokens=192)
        assistant_content = [
            {"type": "thinking", "thinking": "summary", "signature": "sig"},
            {"type": "tool_use", "id": "toolu_live", "name": "lookup", "input": {"item": "alpha"}},
        ]
        response = {"model": "claude-fable-5-1", "content": assistant_content}
        resume = live.build_resume_request(seed, response)
        self.assertEqual(resume["messages"][1], {"role": "assistant", "content": assistant_content})
        result = resume["messages"][2]["content"]
        self.assertEqual(result[0]["type"], "tool_result")
        self.assertEqual(result[0]["tool_use_id"], "toolu_live")
        self.assertEqual(resume["system"], seed["system"])
        self.assertEqual(resume["tools"], seed["tools"])

    def test_cache_probe_and_prefix_mismatch_probe_are_planned_not_retries(self):
        live = _load_runner()
        seed = live.build_seed_request(max_tokens=192)
        response = {
            "model": "claude-fable-5-1",
            "content": [
                {"type": "thinking", "thinking": "summary", "signature": "sig"},
                {"type": "tool_use", "id": "toolu_live", "name": "lookup", "input": {"item": "alpha"}},
            ],
        }
        resume = live.build_resume_request(seed, response)
        cache_probe = live.build_cache_probe(seed)
        mismatch = live.build_prefix_mismatch_probe(resume)
        self.assertEqual(cache_probe["system"], seed["system"])
        self.assertEqual(cache_probe["tools"], seed["tools"])
        self.assertNotEqual(cache_probe["messages"], seed["messages"])
        self.assertEqual(mismatch["messages"], resume["messages"])
        self.assertEqual(mismatch["tools"], resume["tools"])
        self.assertNotEqual(mismatch["system"], resume["system"])
        self.assertEqual(
            ["seed", "resume", "cache_probe", "prefix_mismatch"],
            [item[0] for item in live.build_sequence_plan(seed, response)],
        )

class AnthropicPreservedThinkingProtocolTests(unittest.TestCase):
    @staticmethod
    def _seed_response():
        return {
            "model": "claude-fable-5-1",
            "stop_reason": "tool_use",
            "content": [
                {"type": "thinking", "thinking": "private-summary", "signature": "signed-state"},
                {"type": "tool_use", "id": "toolu_pt", "name": "lookup", "input": {"item": "alpha"}},
            ],
            "usage": {"input_tokens": 50, "cache_creation_input_tokens": 800, "cache_read_input_tokens": 0, "output_tokens": 20},
            "input_transformations": [],
        }

    def test_protocol_run_records_cache_resume_and_binding_without_raw_state(self):
        live = _load_runner()
        usage = {"input_tokens": 20, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 800, "output_tokens": 5}
        responses = [
            self._seed_response(),
            {"model": live.MODEL_ID, "stop_reason": "end_turn", "content": [{"type": "text", "text": "RESUME_OK"}], "usage": usage, "input_transformations": []},
            {"model": live.MODEL_ID, "stop_reason": "end_turn", "content": [{"type": "text", "text": "CACHE_OK"}], "usage": usage, "input_transformations": []},
            {"model": live.MODEL_ID, "stop_reason": "end_turn", "content": [{"type": "text", "text": "BINDING_DROP_OK"}], "usage": usage, "input_transformations": [{"type": "thinking_dropped", "path": "messages.1.content.0", "reason": "prefix_binding_mismatch"}]},
        ]
        result = live.run_protocol(lambda _payload: responses.pop(0), max_tokens=192)
        self.assertTrue(result["cache_hit_observed"])
        self.assertTrue(result["tool_history_fidelity"])
        self.assertTrue(result["resume_continuity"])
        self.assertTrue(result["prefix_binding_observed"])
        self.assertNotIn("private-summary", repr(result))
        self.assertNotIn("signed-state", repr(result))
        self.assertNotIn("alpha", repr(result))

    def test_prefix_mismatch_success_does_not_claim_enforcement(self):
        live = _load_runner()
        usage = {"input_tokens": 20, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 800, "output_tokens": 5}
        responses = [
            self._seed_response(),
            {"model": live.MODEL_ID, "stop_reason": "end_turn", "content": [{"type": "text", "text": "RESUME_OK"}], "usage": usage, "input_transformations": []},
            {"model": live.MODEL_ID, "stop_reason": "end_turn", "content": [{"type": "text", "text": "CACHE_OK"}], "usage": usage, "input_transformations": []},
            {"model": live.MODEL_ID, "stop_reason": "end_turn", "content": [{"type": "text", "text": "MISMATCH_ACCEPTED"}], "usage": usage, "input_transformations": []},
        ]
        result = live.run_protocol(lambda _payload: responses.pop(0), max_tokens=192)
        self.assertFalse(result["prefix_binding_observed"])
        self.assertTrue(result["cache_hit_observed"])


class AnthropicPreservedThinkingBindingControlTests(unittest.TestCase):
    def test_seed_opts_into_binding_enforcement(self):
        live = _load_runner()
        payload = live.build_seed_request(max_tokens=192)
        self.assertEqual(
            payload["thinking"].get("block_binding"),
            {"prefix_mismatch_behavior": "drop_block"},
        )

    def test_message_headers_include_binding_control_beta(self):
        live = _load_runner()
        headers = live.message_headers("test-key")
        self.assertEqual(headers["x-api-key"], "test-key")
        self.assertEqual(
            headers["anthropic-beta"],
            "thinking-binding-controls-2026-08-01",
        )

    def test_input_transformations_fail_closed_for_drop_unknown_or_missing(self):
        live = _load_runner()
        self.assertTrue(live.input_transformations_clear({"input_transformations": []}))
        self.assertFalse(
            live.input_transformations_clear(
                {"input_transformations": [{
                    "type": "thinking_dropped",
                    "path": "messages.1.content.0",
                    "reason": "prefix_binding_mismatch",
                }]}
            )
        )
        self.assertFalse(
            live.input_transformations_clear(
                {"input_transformations": [{"type": "future_native_event"}]}
            )
        )
        self.assertFalse(live.input_transformations_clear({}))

    def test_execute_live_returns_passthrough_candidate_without_billed_claims(self):
        from unittest.mock import patch

        live = _load_runner()
        protocol = {
            "model": live.MODEL_ID,
            "request_count": 4,
            "max_tokens": 192,
            "cache_hit_observed": True,
            "tool_history_fidelity": True,
            "resume_continuity": True,
            "prefix_binding_observed": True,
            "input_transformations_clear": True,
            "usage_complete": True,
            "estimated_cost_usd": "0.04",
            "accounting_status": "estimated_from_response_usage",
            "responses": [],
        }
        with patch.object(live, "run_protocol", return_value=protocol), patch.object(live, "make_budgeted_transport", return_value=lambda _payload: {}):
            result = live.execute_live(api_key="x", max_spend_usd=Decimal("0.50"), max_tokens=192)
        self.assertEqual(result["classification"], "PASSTHROUGH_ONLY")
        self.assertEqual(result["classification_reason"], "live_canary_candidate")
        self.assertNotIn("billed_cost_usd", result)
        self.assertNotIn("billed_cost_verified", result)


class AnthropicPreservedThinkingCliTests(unittest.TestCase):
    def test_cli_defaults_to_owner_cost_gate_without_network(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch

        live = _load_runner()
        output = StringIO()
        with patch.object(live, "execute_live") as execute, redirect_stdout(output):
            rc = live.main([])
        self.assertEqual(rc, 0)
        execute.assert_not_called()
        rendered = output.getvalue()
        self.assertIn("OWNER_COST_GATE", rendered)
        self.assertIn("claude-fable-5-1", rendered)

    def test_cli_explicit_live_requires_api_key_from_environment(self):
        from unittest.mock import patch

        live = _load_runner()
        with patch.dict(live.os.environ, {}, clear=True):
            rc = live.main(["--execute-live"])
        self.assertEqual(rc, 2)


class AnthropicPreservedThinkingReviewRegressionTests(unittest.TestCase):
    @staticmethod
    def _usage(*, cache_read: int = 0):
        return {
            "input_tokens": 20,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": cache_read,
            "output_tokens": 5,
        }

    @classmethod
    def _seed(cls):
        return {
            "model": "claude-fable-5-1",
            "stop_reason": "tool_use",
            "content": [
                {"type": "thinking", "thinking": "summary", "signature": "sig"},
                {"type": "tool_use", "id": "toolu_pt", "name": "lookup", "input": {"item": "alpha"}},
            ],
            "usage": cls._usage(),
            "input_transformations": [],
        }

    @classmethod
    def _resume(cls, text="RESUME_OK"):
        return {
            "model": "claude-fable-5-1",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": text}],
            "usage": cls._usage(cache_read=800),
            "input_transformations": [],
        }
    @classmethod
    def _cache(cls):
        return {
            "model": "claude-fable-5-1",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "CACHE_OK"}],
            "usage": cls._usage(cache_read=800),
            "input_transformations": [],
        }

    @classmethod
    def _binding_drop(cls):
        return {
            "model": "claude-fable-5-1",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "BINDING_DROP_OK"}],
            "usage": cls._usage(),
            "input_transformations": [{
                "type": "thinking_dropped",
                "path": "messages.1.content.0",
                "reason": "prefix_binding_mismatch",
            }],
        }
    def test_budget_transport_aborts_on_missing_usage(self):
        from unittest.mock import patch

        live = _load_runner()
        response = {"model": live.MODEL_ID, "content": [], "input_transformations": []}
        with patch.object(live, "_post_message", return_value=response) as post:
            transport = live.make_budgeted_transport("x", max_spend_usd=Decimal("0.50"))
            with self.assertRaises(ValueError):
                transport({"model": live.MODEL_ID, "max_tokens": 1, "messages": []})
        self.assertEqual(post.call_count, 1)

    def test_generic_400_is_not_binding_evidence(self):
        live = _load_runner()
        responses = [self._seed(), self._resume(), self._cache()]

        def transport(_payload):
            if responses:
                return responses.pop(0)
            raise live.ProviderHTTPError(400, "invalid_request_error")

        with self.assertRaises(live.ProviderHTTPError):
            live.run_protocol(transport, max_tokens=192)
    def test_wrong_tool_semantics_are_rejected(self):
        live = _load_runner()
        seed = self._seed()
        seed["content"][1]["name"] = "wrong_tool"
        responses = [seed, self._resume(), self._cache(), self._binding_drop()]
        with self.assertRaises(ValueError):
            live.run_protocol(lambda _payload: responses.pop(0), max_tokens=192)

    def test_unrelated_resume_is_not_continuity(self):
        live = _load_runner()
        responses = [self._seed(), self._resume("UNRELATED"), self._cache(), self._binding_drop()]
        with self.assertRaises(ValueError):
            live.run_protocol(lambda _payload: responses.pop(0), max_tokens=192)

    def test_malformed_or_unknown_native_state_is_rejected(self):
        live = _load_runner()
        for content in (
            [{"type": "thinking"}, self._seed()["content"][1]],
            [self._seed()["content"][0], {"type": "future_native_state"}, self._seed()["content"][1]],
        ):
            seed = self._seed()
            seed["content"] = content
            with self.subTest(content=content), self.assertRaises(ValueError):
                live.run_protocol(lambda _payload, r=[seed]: r.pop(0), max_tokens=192)
    def test_structured_drop_block_is_binding_evidence(self):
        live = _load_runner()
        responses = [self._seed(), self._resume(), self._cache(), self._binding_drop()]
        result = live.run_protocol(lambda _payload: responses.pop(0), max_tokens=192)
        self.assertTrue(result["prefix_binding_observed"])
        self.assertTrue(result["usage_complete"])

    def test_transport_enforces_four_request_cap_before_network(self):
        from unittest.mock import patch

        live = _load_runner()
        response = self._cache()
        with patch.object(live, "_post_message", return_value=response) as post:
            transport = live.make_budgeted_transport("x", max_spend_usd=Decimal("0.50"))
            payload = {"model": live.MODEL_ID, "max_tokens": 1, "messages": []}
            for _ in range(4):
                transport(payload)
            with self.assertRaises(RuntimeError):
                transport(payload)
        self.assertEqual(post.call_count, 4)

    def test_execute_live_never_claims_request_specific_billed_cost(self):
        from unittest.mock import patch

        live = _load_runner()
        protocol = live.run_protocol(
            lambda _payload, r=[self._seed(), self._resume(), self._cache(), self._binding_drop()]: r.pop(0),
            max_tokens=192,
        )
        with (
            patch.object(live, "run_protocol", return_value=protocol),
            patch.object(live, "make_budgeted_transport", return_value=lambda _payload: {}),
        ):
            result = live.execute_live(
                api_key="x",
                max_spend_usd=Decimal("0.50"),
                max_tokens=192,
            )
        self.assertEqual(result["classification"], "PASSTHROUGH_ONLY")
        self.assertEqual(result["classification_reason"], "live_canary_candidate")
        self.assertEqual(result["accounting_status"], "estimated_from_response_usage")
        self.assertNotIn("billed_cost_verified", result)
        self.assertNotIn("billed_cost_usd", result)


class AnthropicPreservedThinkingFinalReviewTests(unittest.TestCase):
    @staticmethod
    def _usage():
        return {
            "input_tokens": 20,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 800,
            "output_tokens": 5,
        }

    @classmethod
    def _seed(cls):
        return {
            "model": "claude-fable-5-1",
            "stop_reason": "tool_use",
            "content": [
                {"type": "thinking", "thinking": "summary", "signature": "sig"},
                {"type": "tool_use", "id": "toolu_pt", "name": "lookup", "input": {"item": "alpha"}},
            ],
            "usage": cls._usage(),
            "input_transformations": [],
        }

    @classmethod
    def _text(cls, value):
        return {
            "model": "claude-fable-5-1",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": value}],
            "usage": cls._usage(),
            "input_transformations": [],
        }

    @classmethod
    def _binding(cls):
        response = cls._text("BINDING_DROP_OK")
        response["input_transformations"] = [{
            "type": "thinking_dropped",
            "path": "messages.1.content.0",
            "reason": "prefix_binding_mismatch",
        }]
        return response

    def test_binding_drop_requires_clean_exact_response(self):
        live = _load_runner()
        for mutate in (
            lambda response: response.__setitem__("stop_reason", "max_tokens"),
            lambda response: response.__setitem__(
                "content", [{"type": "future_native_state", "payload": "private-sentinel"}]
            ),
        ):
            binding = self._binding()
            mutate(binding)
            responses = [self._seed(), self._text("RESUME_OK"), self._text("CACHE_OK"), binding]
            with self.subTest(binding=binding), self.assertRaises(ValueError):
                live.run_protocol(lambda _payload, r=responses: r.pop(0), max_tokens=192)

    def test_unknown_provider_strings_are_bounded_in_sanitized_output(self):
        live = _load_runner()
        response = {
            "model": "private-model-sentinel",
            "stop_reason": "private-stop-sentinel",
            "content": [{"type": "private-content-sentinel"}],
            "usage": self._usage(),
            "input_transformations": [{
                "type": "private-transform-sentinel",
                "path": "private-path-sentinel",
                "reason": "private-reason-sentinel",
            }],
        }
        safe = live.sanitize_response(response, request_sha256="abc")
        rendered = repr(safe)
        self.assertNotIn("private-", rendered)
        self.assertEqual(safe["model"], "unexpected")
        self.assertEqual(safe["stop_reason"], "unknown")
        self.assertEqual(safe["content_types"], ["unknown"])
        self.assertEqual(safe["input_transformations"], "unknown")

if __name__ == "__main__":
    unittest.main()
