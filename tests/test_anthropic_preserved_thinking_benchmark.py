import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "benchmarks" / "anthropic-preserved-thinking-v1"
RUNNER = ROOT / "benchmarks" / "run_anthropic_preserved_thinking_offline.py"
FROZEN = ROOT / "benchmarks" / "results" / "anthropic-preserved-thinking-v1.json"


class AnthropicPreservedThinkingBenchmarkTests(unittest.TestCase):
    def test_manifest_is_ordered_and_bounded(self):
        manifest = json.loads((CORPUS / "manifest.json").read_text())
        files = [item["file"] for item in manifest["trajectories"]]
        self.assertEqual(len(files), 5)
        self.assertEqual(files, sorted(files))
        self.assertEqual(
            manifest["generation_id"],
            "token-anthropic-preserved-thinking-cert-1:pt-v1",
        )

    def test_runner_is_byte_deterministic_and_matches_frozen_result(self):
        first = self._run()
        second = self._run()
        self.assertEqual(first, second)
        self.assertEqual(first, FROZEN.read_bytes())
    def test_frozen_result_covers_all_offline_contract_gates(self):
        payload = json.loads(FROZEN.read_text())
        self.assertEqual(payload["corpus_cases"], 5)
        self.assertTrue(payload["inventory_complete"])
        self.assertTrue(payload["protected_prefix_exact"])
        self.assertTrue(payload["token_off_on_wire_equivalent"])
        self.assertTrue(payload["tool_history_fidelity"])
        self.assertTrue(payload["cache_metadata_preserved"])
        self.assertTrue(payload["resume_continuity"])
        self.assertTrue(payload["unknown_native_passthrough"])
        self.assertEqual(payload["classification"], "PASSTHROUGH_ONLY")
        self.assertEqual(payload["classification_reason"], "offline_conformance_only")

    def test_result_is_sanitized(self):
        payload = json.loads(FROZEN.read_text())
        rendered = json.dumps(payload, sort_keys=True)
        self.assertNotIn("signature-value", rendered)
        self.assertNotIn("ciphertext-value", rendered)
        self.assertNotIn("raw_payload", rendered)
        self.assertNotIn("raw_thinking", rendered)

    @staticmethod
    def _run() -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "result.json"
            env = dict(os.environ)
            env["PYTHONPATH"] = str(ROOT / "src")
            subprocess.run(
                [sys.executable, str(RUNNER), str(CORPUS), "--output", str(output)],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            return output.read_bytes()


class AnthropicPreservedThinkingHardBypassBenchmarkTests(unittest.TestCase):
    def test_frozen_result_proves_hard_bypass_not_noop_corpus(self):
        payload = json.loads(FROZEN.read_text())
        self.assertEqual(payload["optimized_count"], 0)
        self.assertEqual(payload["bypass_count"], payload["corpus_cases"])
        self.assertEqual(payload["changed_block_ids"], [])
        self.assertTrue(payload["thinking_stripped_control_reducible"])
        self.assertIn("unsupported_wire_shape", payload["bypass_reasons"])

    def test_manifest_declares_every_trajectory_bypass(self):
        manifest = json.loads((CORPUS / "manifest.json").read_text())
        outcomes = [item.get("expected_decision") for item in manifest["trajectories"]]
        self.assertEqual(outcomes, ["BYPASS"] * 5)


class AnthropicPreservedThinkingFinalReviewBenchmarkTests(unittest.TestCase):
    def _mutated_result(self, mutate):
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "corpus"
            shutil.copytree(CORPUS, corpus)
            mutate(corpus)
            output = Path(tmp) / "result.json"
            env = dict(os.environ)
            env["PYTHONPATH"] = str(ROOT / "src")
            subprocess.run(
                [sys.executable, str(RUNNER), str(corpus), "--output", str(output)],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            return json.loads(output.read_text())

    def test_inventory_is_derived_from_corpus_bytes(self):
        def mutate(corpus):
            path = corpus / "01-thinking-tool-chain.json"
            payload = json.loads(path.read_text())
            for message in payload["messages"]:
                if isinstance(message.get("content"), list):
                    message["content"] = [
                        part for part in message["content"]
                        if not (isinstance(part, dict) and part.get("type") == "tool_use")
                    ]
            path.write_text(json.dumps(payload, indent=2) + "\n")

        result = self._mutated_result(mutate)
        self.assertFalse(result["inventory_complete"])
        self.assertEqual(result["classification_reason"], "offline_contract_incomplete")

    def test_tool_history_requires_nonempty_linked_pairs(self):
        def mutate(corpus):
            path = corpus / "manifest.json"
            manifest = json.loads(path.read_text())
            manifest["trajectories"][0]["checks"].remove("tool_history")
            manifest["trajectories"][3]["checks"].append("tool_history")
            path.write_text(json.dumps(manifest, indent=2) + "\n")

        result = self._mutated_result(mutate)
        self.assertFalse(result["tool_history_fidelity"])
        self.assertEqual(result["classification_reason"], "offline_contract_incomplete")

    def test_exact_fable_model_scope_is_required(self):
        def mutate(corpus):
            path = corpus / "02-redacted-resume.json"
            payload = json.loads(path.read_text())
            payload["model"] = "claude-other"
            path.write_text(json.dumps(payload, indent=2) + "\n")

        result = self._mutated_result(mutate)
        self.assertFalse(result["model_scope_exact"])
        self.assertEqual(result["classification_reason"], "offline_contract_incomplete")

    def test_hard_bypass_contract_controls_classification(self):
        def mutate(corpus):
            path = corpus / "01-thinking-tool-chain.json"
            payload = json.loads(path.read_text())
            payload["messages"][0]["content"] += "\ndiff --git synthetic"
            path.write_text(json.dumps(payload, indent=2) + "\n")

        result = self._mutated_result(mutate)
        self.assertFalse(result["hard_bypass_complete"])
        self.assertEqual(result["classification_reason"], "offline_contract_incomplete")

    def test_reducible_control_controls_classification(self):
        def mutate(corpus):
            path = corpus / "04-multiturn-off-on.json"
            payload = json.loads(path.read_text())
            payload["messages"][0]["content"] += "\ndiff --git synthetic"
            path.write_text(json.dumps(payload, indent=2) + "\n")

        result = self._mutated_result(mutate)
        self.assertFalse(result["thinking_stripped_control_reducible"])
        self.assertEqual(result["classification_reason"], "offline_contract_incomplete")


if __name__ == "__main__":
    unittest.main()
