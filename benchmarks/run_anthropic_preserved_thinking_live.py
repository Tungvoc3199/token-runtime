from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

MODEL_ID = "claude-fable-5-1"
MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
BINDING_BETA = "thinking-binding-controls-2026-08-01"
BINDING_MODE = "drop_block"
HARD_CAP_USD = Decimal("1.00")
DEFAULT_MAX_SPEND_USD = Decimal("0.50")
MAX_REQUESTS = 4
MAX_TOKENS = 256
MILLION = Decimal("1000000")
INPUT_RATE = Decimal("10")
CACHE_WRITE_RATE = Decimal("12.50")
CACHE_READ_RATE = Decimal("0.25")
OUTPUT_RATE = Decimal("50")
USAGE_KEYS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)
KNOWN_STOP_REASONS = frozenset({"tool_use", "end_turn"})
KNOWN_CONTENT_TYPES = frozenset({"thinking", "redacted_thinking", "tool_use", "text"})


def validate_budget(max_spend_usd: Decimal, *, max_requests: int, max_tokens: int) -> None:
    if not max_spend_usd.is_finite() or max_spend_usd <= 0 or max_spend_usd > HARD_CAP_USD:
        raise ValueError("max_spend_usd must be finite, > 0 and <= 1.00")
    if max_requests < 1 or max_requests > MAX_REQUESTS:
        raise ValueError("max_requests must be between 1 and 4")
    if max_tokens < 1 or max_tokens > MAX_TOKENS:
        raise ValueError("max_tokens must be between 1 and 256")


def message_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "anthropic-beta": BINDING_BETA,
        "content-type": "application/json",
    }


def _count(usage: dict[str, Any], key: str) -> Decimal:
    if key not in usage:
        raise ValueError(f"missing usage counter: {key}")
    value = usage[key]
    if isinstance(value, bool):
        raise ValueError(f"invalid usage counter: {key}")
    try:
        count = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid usage counter: {key}") from exc
    if not count.is_finite() or count < 0 or count != count.to_integral_value():
        raise ValueError(f"invalid usage counter: {key}")
    return count


def _validated_usage(response: dict[str, Any]) -> dict[str, int]:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("response missing usage")
    return {key: int(_count(usage, key)) for key in USAGE_KEYS}


def estimate_cost_usd(usage: dict[str, Any]) -> Decimal:
    validated = {key: _count(usage, key) for key in USAGE_KEYS}
    cost = (
        validated["input_tokens"] * INPUT_RATE
        + validated["cache_creation_input_tokens"] * CACHE_WRITE_RATE
        + validated["cache_read_input_tokens"] * CACHE_READ_RATE
        + validated["output_tokens"] * OUTPUT_RATE
    ) / MILLION
    return cost.normalize()


def input_transformations_clear(response: dict[str, Any]) -> bool:
    transformations = response.get("input_transformations")
    return isinstance(transformations, list) and not transformations


def _binding_drop_observed(response: dict[str, Any]) -> bool:
    transformations = response.get("input_transformations")
    expected = {
        "type": "thinking_dropped",
        "path": "messages.1.content.0",
        "reason": "prefix_binding_mismatch",
    }
    return isinstance(transformations, list) and transformations == [expected]


def sanitize_response(response: dict[str, Any], *, request_sha256: str) -> dict[str, Any]:
    content = response.get("content")
    content_types: list[str] = []
    if isinstance(content, list):
        for part in content:
            part_type = part.get("type") if isinstance(part, dict) else None
            content_types.append(part_type if part_type in KNOWN_CONTENT_TYPES else "unknown")
    stop_reason = response.get("stop_reason")
    transformations = response.get("input_transformations")
    if transformations == []:
        transformation_status = "clear"
    elif _binding_drop_observed(response):
        transformation_status = "binding_drop"
    else:
        transformation_status = "unknown"
    return {
        "request_sha256": request_sha256,
        "model": MODEL_ID if response.get("model") == MODEL_ID else "unexpected",
        "stop_reason": stop_reason if stop_reason in KNOWN_STOP_REASONS else "unknown",
        "content_types": content_types,
        "usage": _validated_usage(response),
        "input_transformations": transformation_status,
    }


def execute_sequence(
    requests: Iterable[dict[str, Any]],
    transport: Callable[[dict[str, Any]], dict[str, Any]],
) -> list[dict[str, Any]]:
    responses = []
    for payload in requests:
        responses.append(transport(payload))
    return responses


def cache_hit_observed(responses: Iterable[dict[str, Any]]) -> bool:
    for response in responses:
        usage = response.get("usage")
        if isinstance(usage, dict) and "cache_read_input_tokens" in usage:
            if _count(usage, "cache_read_input_tokens") > 0:
                return True
    return False


def _request_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _stable_system_text() -> str:
    sentence = (
        "Synthetic TOKEN certification context. Preserve protocol state exactly; "
        "use only the provided synthetic lookup tool and synthetic values. "
    )
    return sentence * 40


def build_seed_request(*, max_tokens: int) -> dict[str, Any]:
    validate_budget(DEFAULT_MAX_SPEND_USD, max_requests=MAX_REQUESTS, max_tokens=max_tokens)
    return {
        "model": MODEL_ID,
        "max_tokens": max_tokens,
        "thinking": {
            "type": "adaptive",
            "display": "summarized",
            "block_binding": {"prefix_mismatch_behavior": BINDING_MODE},
        },
        "output_config": {"effort": "low"},
        "system": [{
            "type": "text",
            "text": _stable_system_text(),
            "cache_control": {"type": "ephemeral"},
        }],
        "tools": [{
            "name": "lookup",
            "description": "Return one synthetic certification value.",
            "input_schema": {
                "type": "object",
                "properties": {"item": {"type": "string"}},
                "required": ["item"],
                "additionalProperties": False,
            },
        }],
        "messages": [{
            "role": "user",
            "content": "Use lookup exactly once with item alpha, then wait for its result.",
        }],
    }


def _strict_seed_content(response: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    content = response.get("content")
    if not isinstance(content, list) or not content:
        raise ValueError("unsupported native content")
    tool_use: dict[str, Any] | None = None
    saw_thinking = False
    for index, part in enumerate(content):
        if not isinstance(part, dict):
            raise ValueError("unsupported native content")
        part_type = part.get("type")
        if part_type == "thinking":
            if set(part) != {"type", "thinking", "signature"}:
                raise ValueError("unsupported native content")
            if not isinstance(part.get("thinking"), str) or not isinstance(part.get("signature"), str):
                raise ValueError("unsupported native content")
            if tool_use is not None:
                raise ValueError("unsupported native content")
            saw_thinking = True
            continue
        if part_type == "redacted_thinking":
            if set(part) != {"type", "data"} or not isinstance(part.get("data"), str):
                raise ValueError("unsupported native content")
            if tool_use is not None:
                raise ValueError("unsupported native content")
            saw_thinking = True
            continue
        if part_type == "tool_use":
            if index != len(content) - 1 or tool_use is not None:
                raise ValueError("unexpected tool use")
            if set(part) != {"type", "id", "name", "input"}:
                raise ValueError("unexpected tool use")
            if not isinstance(part.get("id"), str) or not part["id"]:
                raise ValueError("unexpected tool use")
            if part.get("name") != "lookup" or part.get("input") != {"item": "alpha"}:
                raise ValueError("unexpected tool use")
            tool_use = part
            continue
        raise ValueError("unsupported native content")
    if not saw_thinking or tool_use is None:
        raise ValueError("unsupported native content")
    return content, tool_use["id"]


def build_resume_request(seed: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    content, tool_use_id = _strict_seed_content(response)
    payload = _clone(seed)
    payload["messages"] = [
        _clone(seed["messages"][0]),
        {"role": "assistant", "content": _clone(content)},
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": "alpha=green",
                },
                {
                    "type": "text",
                    "text": "Continue from the exact prior state and answer RESUME_OK.",
                },
            ],
        },
    ]
    return payload


def build_cache_probe(seed: dict[str, Any]) -> dict[str, Any]:
    payload = _clone(seed)
    payload["messages"] = [{
        "role": "user",
        "content": "Cache probe only. Reply with CACHE_OK in one short line.",
    }]
    return payload


def build_prefix_mismatch_probe(resume: dict[str, Any]) -> dict[str, Any]:
    payload = _clone(resume)
    system = payload.get("system")
    if not isinstance(system, list) or not system or not isinstance(system[0], dict):
        raise ValueError("expected structured system prompt")
    original = system[0].get("text")
    if not isinstance(original, str):
        raise ValueError("expected system text")
    system[0]["text"] = "INTENTIONAL_PREFIX_MUTATION. " + original
    return payload


def build_sequence_plan(
    seed: dict[str, Any], response: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    resume = build_resume_request(seed, response)
    return [
        ("seed", _clone(seed)),
        ("resume", resume),
        ("cache_probe", build_cache_probe(seed)),
        ("prefix_mismatch", build_prefix_mismatch_probe(resume)),
    ]


class ProviderHTTPError(RuntimeError):
    def __init__(self, status: int, error_type: str):
        super().__init__(f"provider_http_{status}:{error_type}")
        self.status = status
        self.error_type = error_type


def _require_model(response: dict[str, Any], phase: str) -> None:
    if response.get("model") != MODEL_ID:
        raise ValueError(f"{phase} response returned unexpected model")


def _require_positive_transformations(response: dict[str, Any], phase: str) -> None:
    if not input_transformations_clear(response):
        raise ValueError(f"{phase} input transformations not clear")


def _require_exact_text_response(
    response: dict[str, Any], *, phase: str, expected_text: str
) -> None:
    _require_model(response, phase)
    _require_positive_transformations(response, phase)
    _validated_usage(response)
    if response.get("stop_reason") != "end_turn":
        raise ValueError(f"{phase} response did not end cleanly")
    if response.get("content") != [{"type": "text", "text": expected_text}]:
        raise ValueError(f"unexpected {phase} response")


def _require_binding_probe_response(response: dict[str, Any]) -> bool:
    transformations = response.get("input_transformations")
    if transformations == []:
        return False
    if not _binding_drop_observed(response):
        raise ValueError("prefix mismatch returned unsupported transformation state")
    if response.get("stop_reason") != "end_turn":
        raise ValueError("prefix mismatch response did not end cleanly")
    if response.get("content") != [{"type": "text", "text": "BINDING_DROP_OK"}]:
        raise ValueError("unexpected prefix mismatch response")
    return True


def run_protocol(
    transport: Callable[[dict[str, Any]], dict[str, Any]], *, max_tokens: int
) -> dict[str, Any]:
    seed = build_seed_request(max_tokens=max_tokens)
    seed_response = transport(seed)
    _require_model(seed_response, "seed")
    _require_positive_transformations(seed_response, "seed")
    _validated_usage(seed_response)
    if seed_response.get("stop_reason") != "tool_use":
        raise ValueError("seed response did not request tool")
    seed_content, tool_use_id = _strict_seed_content(seed_response)

    resume = build_resume_request(seed, seed_response)
    resume_response = transport(resume)
    _require_exact_text_response(
        resume_response, phase="resume", expected_text="RESUME_OK"
    )

    cache_probe = build_cache_probe(seed)
    cache_response = transport(cache_probe)
    _require_exact_text_response(
        cache_response, phase="cache", expected_text="CACHE_OK"
    )

    mismatch = build_prefix_mismatch_probe(resume)
    mismatch_response = transport(mismatch)
    _require_model(mismatch_response, "prefix mismatch")
    _validated_usage(mismatch_response)
    prefix_binding_observed = _require_binding_probe_response(mismatch_response)

    request_payloads = [seed, resume, cache_probe, mismatch]
    raw_responses = [
        seed_response,
        resume_response,
        cache_response,
        mismatch_response,
    ]
    safe_responses = [
        sanitize_response(response, request_sha256=_request_hash(payload))
        for response, payload in zip(raw_responses, request_payloads)
    ]
    estimated = sum(
        (estimate_cost_usd(response["usage"]) for response in raw_responses),
        Decimal("0"),
    )
    tool_result = resume["messages"][2]["content"][0]
    tool_history_fidelity = (
        resume["messages"][1]["content"] == seed_content
        and tool_result.get("tool_use_id") == tool_use_id
    )
    return {
        "model": MODEL_ID,
        "request_count": MAX_REQUESTS,
        "max_tokens": max_tokens,
        "cache_hit_observed": cache_hit_observed(raw_responses[:3]),
        "tool_history_fidelity": tool_history_fidelity,
        "resume_continuity": True,
        "prefix_binding_observed": prefix_binding_observed,
        "input_transformations_clear": all(
            input_transformations_clear(item) for item in raw_responses[:3]
        ),
        "usage_complete": True,
        "estimated_cost_usd": format(estimated, "f"),
        "accounting_status": "estimated_from_response_usage",
        "responses": safe_responses,
    }


def _decode_error_type(exc: HTTPError) -> str:
    try:
        body = json.loads(exc.read().decode("utf-8"))
    except Exception:
        return "unknown_error"
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and isinstance(error.get("type"), str):
        return error["type"]
    return "unknown_error"


def _post_message(api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(
        MESSAGES_URL,
        data=data,
        method="POST",
        headers=message_headers(api_key),
    )
    try:
        with urlopen(request, timeout=60) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ProviderHTTPError(exc.code, _decode_error_type(exc)) from None
    if not isinstance(parsed, dict):
        raise ValueError("provider response must be an object")
    return parsed


def _payload_upper_bound_usd(payload: dict[str, Any]) -> Decimal:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    max_input = Decimal(len(encoded)) * CACHE_WRITE_RATE / MILLION
    max_output = Decimal(int(payload.get("max_tokens", 0))) * OUTPUT_RATE / MILLION
    return max_input + max_output


def make_budgeted_transport(
    api_key: str, *, max_spend_usd: Decimal
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    observed = Decimal("0")
    calls = 0

    def transport(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal observed, calls
        if calls >= MAX_REQUESTS:
            raise RuntimeError("request_cap_exceeded")
        projected = _payload_upper_bound_usd(payload)
        if observed + projected > max_spend_usd:
            raise RuntimeError("budget_guard_would_exceed_max_spend")
        calls += 1
        response = _post_message(api_key, payload)
        usage = _validated_usage(response)
        observed += estimate_cost_usd(usage)
        if observed > max_spend_usd:
            raise RuntimeError("budget_guard_observed_spend_exceeded")
        return response

    return transport


def _offline_evidence():
    from token_runtime.anthropic_preserved_thinking_cert import (
        AnthropicPreservedThinkingOfflineEvidence,
    )

    frozen = Path(__file__).resolve().parent / "results" / "anthropic-preserved-thinking-v1.json"
    payload = json.loads(frozen.read_text(encoding="utf-8"))
    return AnthropicPreservedThinkingOfflineEvidence(
        evidence_id=payload["evidence_id"],
        inventory_complete=payload["inventory_complete"],
        model_scope_exact=payload["model_scope_exact"],
        hard_bypass_complete=payload["hard_bypass_complete"],
        thinking_stripped_control_reducible=payload["thinking_stripped_control_reducible"],
        protected_prefix_exact=payload["protected_prefix_exact"],
        token_off_on_wire_equivalent=payload["token_off_on_wire_equivalent"],
        tool_history_fidelity=payload["tool_history_fidelity"],
        cache_metadata_preserved=payload["cache_metadata_preserved"],
        resume_continuity=payload["resume_continuity"],
        unknown_native_passthrough=payload["unknown_native_passthrough"],
    )


def _live_evidence_id(result: dict[str, Any]) -> str:
    safe = {
        key: value
        for key, value in result.items()
        if key != "classification_evidence_id"
    }
    encoded = json.dumps(safe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"token-anthropic-preserved-thinking-cert-1:live:{sha256(encoded).hexdigest()}"


def execute_live(
    *, api_key: str, max_spend_usd: Decimal, max_tokens: int
) -> dict[str, Any]:
    from token_runtime.anthropic_preserved_thinking_cert import (
        AnthropicPreservedThinkingLiveEvidence,
        classify_anthropic_preserved_thinking,
    )

    validate_budget(max_spend_usd, max_requests=MAX_REQUESTS, max_tokens=max_tokens)
    result = run_protocol(
        make_budgeted_transport(api_key, max_spend_usd=max_spend_usd),
        max_tokens=max_tokens,
    )
    evidence_id = _live_evidence_id(result)
    live = AnthropicPreservedThinkingLiveEvidence(
        evidence_id=evidence_id,
        model_id=result["model"],
        binding_beta=BINDING_BETA,
        prefix_mismatch_behavior=BINDING_MODE,
        cache_hit_observed=result["cache_hit_observed"],
        tool_history_fidelity=result["tool_history_fidelity"],
        resume_continuity=result["resume_continuity"],
        prefix_binding_observed=result["prefix_binding_observed"],
        input_transformations_clear=result["input_transformations_clear"],
        usage_complete=result["usage_complete"],
        estimated_cost_usd=result["estimated_cost_usd"],
        accounting_status=result["accounting_status"],
    )
    record = classify_anthropic_preserved_thinking(_offline_evidence(), live)
    safe_result = dict(result)
    safe_result["classification"] = record.state.value
    safe_result["classification_reason"] = record.reason
    safe_result["classification_evidence_id"] = record.evidence_id
    return safe_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument(
        "--max-spend-usd", type=Decimal, default=DEFAULT_MAX_SPEND_USD
    )
    parser.add_argument("--max-tokens", type=int, default=192)
    args = parser.parse_args(argv)
    validate_budget(
        args.max_spend_usd,
        max_requests=MAX_REQUESTS,
        max_tokens=args.max_tokens,
    )

    if not args.execute_live:
        print(json.dumps({
            "status": "OWNER_COST_GATE",
            "model": MODEL_ID,
            "max_requests": MAX_REQUESTS,
            "max_tokens": args.max_tokens,
            "max_spend_usd": format(args.max_spend_usd, "f"),
            "classification_ceiling": "PASSTHROUGH_ONLY",
        }, sort_keys=True))
        return 0
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return 2
    result = execute_live(
        api_key=api_key,
        max_spend_usd=args.max_spend_usd,
        max_tokens=args.max_tokens,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
