from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json

from .capabilities import CapabilityDetector, CapabilityKey, CapabilityProfile, CapabilityRegistry
from .compatibility import CompatibilityRecord, CompatibilityRegistry, CompatibilityState
from .conformance import ConformanceResult, require_conformance, run_conformance

OPENAI_AGENTS_API_KEY = CapabilityKey('generic-openai', 'openai_agents_api', 'openai')
SNAPSHOT_DATE = '2026-09-13'
CORPUS_VERSION = 'openai-agents-api-conformance-v1'
API_STATUS = 'public_beta'
OFFICIAL_SOURCE_REFS = (
    'https://openai.com/index/introducing-the-agents-api/',
    'https://openai.com/vi-VN/products/release-notes/',
    'https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/subresources/sessions/methods/create',
    'https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/subresources/sessions/subresources/events/methods/create',
    'https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/subresources/sessions/subresources/events/methods/stream',
    'https://github.com/openai/openai-python/tree/e12b81d3bbf644ec7045e152d69bc4b68d69cd48/src/openai/types/beta',
)

TESTED_SHAPE_MANIFEST = {
    'api_family': 'openai_agents_api',
    'endpoint_families': (
        'POST /agents/sessions',
        'POST /agents/sessions/{session_id}/events',
        'GET /agents/sessions/{session_id}/events',
    ),
    'session_fields': ('environment', 'agent', 'agent_id', 'input', 'metadata', 'stream', 'vault_ids'),
    'agent_fields': ('tools', 'multi_agent'),
    'documented_exact_input_event_types': ('agent.session.input.message',),
    'documented_input_event_categories': ('message', 'cancellation', 'tool_result'),
    'stream_events': (
        'agent.session.created',
        'agent.session.turn.created',
        'agent.session.environment.ready',
        'agent.session.subagent.created',
        'agent.session.turn.item.added',
        'agent.session.turn.content_part.added',
        'agent.session.turn.output_text.delta',
        'agent.session.turn.reasoning_summary_text.delta',
        'agent.output.command_execution_output.delta',
        'agent.session.requires_action',
        'error',
        'agent.session.idle',
    ),
    'synthetic_unknown_stream_events': ('agent.session.future.event',),
    'identifier_fields': (
        'event_id', 'session_id', 'item_id', 'turn_id', 'output_index',
        'content_index', 'summary_index', 'session.id', 'subagent.session_id',
    ),
}

ASSERTION_IDS = (
    'certification_state_passthrough_only',
    'corpus_digest_matches_raw_ordered_bytes',
    'idempotency_key_frozen',
    'mcp_and_vault_fixture_covered',
    'native_context_management_claim_bounded',
    'near_match_non_inheritance',
    'official_sources_bound',
    'stream_duplicate_and_order_frozen',
    'stream_identifiers_frozen',
    'unknown_event_frozen',
)

SESSION_CREATE_FIXTURE = b'''{
  "environment" : {"type":"none"},
  "agent_id" : "agent_fixture_saved",
  "agent" : {"name":"fixture-agent","tools":[{"type":"mcp","server_label":"fixture-mcp","server_url":"https://example.invalid/mcp"}],"multi_agent":{"enabled":true,"max_concurrent_subagents":2}},
  "input" : [{"role":"user","content":"fixture input"}],
  "metadata" : {"fixture":"agents-conformance"},
  "stream" : true,
  "vault_ids" : ["vault_fixture"],
  "future_field" : {"opaque":true}
}'''

INPUT_EVENT_FIXTURES = (
    ('input-message', b'''{
  "idempotency_key" : "idem_fixture_001",
  "events" : [{"type":"agent.session.input.message","role":"user","content":"hello","future_nested":{"opaque":true}}]
}'''),
    ('input-cancellation', b'''{"fixture_category":"cancellation","payload":{"session_id":"sess_fixture","future_nested":{"opaque":true}}}'''),
    ('input-tool-result', b'''{"fixture_category":"tool_result","payload":{"call_id":"call_fixture","output":"ok","future_nested":{"opaque":true}}}'''),
)

_DUPLICATE_FRAME = b'{"type":"agent.session.idle","event_id":"evt_dup","session":{"id":"sess_fixture"}}'
STREAM_EVENT_FRAMES = (
    ('session-created', b'{"type":"agent.session.created","event_id":"evt_001","session":{"id":"sess_fixture"}}'),
    ('turn-created', b'{"type":"agent.session.turn.created","event_id":"evt_002","session_id":"sess_fixture","turn_id":"turn_fixture","turn":{"id":"turn_fixture","session_id":"sess_fixture"}}'),
    ('environment-ready', b'{"type":"agent.session.environment.ready","event_id":"evt_003","session_id":"sess_fixture","turn_id":"turn_fixture","environment":{"type":"none"}}'),
    ('subagent-created', b'{"type":"agent.session.subagent.created","event_id":"evt_004","subagent":{"id":"subagent_fixture","session_id":"sess_fixture"}}'),
    ('item-added', b'{"type":"agent.session.turn.item.added","event_id":"evt_005","session_id":"sess_fixture","turn_id":"turn_fixture","output_index":0,"item":{"id":"item_fixture"}}'),
    ('content-part-added', b'{"type":"agent.session.turn.content_part.added","event_id":"evt_006","session_id":"sess_fixture","turn_id":"turn_fixture","item_id":"item_fixture","output_index":0,"content_index":0,"part":{"type":"output_text","text":""}}'),
    ('output-text-delta-a', b'{"type":"agent.session.turn.output_text.delta","event_id":"evt_007","session_id":"sess_fixture","turn_id":"turn_fixture","item_id":"item_fixture","output_index":0,"content_index":0,"delta":"A"}'),
    ('output-text-delta-b', b'{"type":"agent.session.turn.output_text.delta","event_id":"evt_008","session_id":"sess_fixture","turn_id":"turn_fixture","item_id":"item_fixture","output_index":0,"content_index":0,"delta":"B"}'),
    ('reasoning-summary-delta', b'{"type":"agent.session.turn.reasoning_summary_text.delta","event_id":"evt_009","session_id":"sess_fixture","turn_id":"turn_fixture","item_id":"reason_fixture","output_index":0,"summary_index":0,"delta":"reason"}'),
    ('command-output-delta', b'{"type":"agent.output.command_execution_output.delta","event_id":"evt_010","session_id":"sess_fixture","turn_id":"turn_fixture","item_id":"command_fixture","output_index":0,"delta":"chunk"}'),
    ('requires-action', b'{"type":"agent.session.requires_action","event_id":"evt_011","session":{"id":"sess_fixture","required_actions":[{"id":"action_fixture"}]}}'),
    ('idle-error', b'{"type":"error","event_id":"evt_012","session_id":"sess_fixture","error":{"message":"fixture"}}'),
    ('unknown-future-event', b'{"type":"agent.session.future.event","session_id":"sess_fixture","opaque":{"nested":[1,2,3]}}'),
    ('duplicate-frame', _DUPLICATE_FRAME),
    ('duplicate-frame-copy', _DUPLICATE_FRAME),
)
RAW_CORPUS = (('session-create', SESSION_CREATE_FIXTURE), *INPUT_EVENT_FIXTURES, *STREAM_EVENT_FRAMES)

@dataclass(frozen=True, slots=True)
class OpenAIAgentsConformanceEvidence:
    api_family: str
    api_status: str
    snapshot_date: str
    official_source_refs: tuple[str, ...]
    sdk_client_version: str | None
    corpus_version: str
    tested_endpoint_families: tuple[str, ...]
    protected_fields: tuple[str, ...]
    tested_input_event_shapes: tuple[str, ...]
    tested_stream_event_shapes: tuple[str, ...]
    tested_identifier_fields: tuple[str, ...]
    assertion_ids: tuple[str, ...]
    tested_shape_fingerprint: str
    corpus_digest: str
    evidence_fingerprint: str
    evidence_id: str

@dataclass(frozen=True, slots=True)
class OpenAIAgentsConformanceBundle:
    evidence: OpenAIAgentsConformanceEvidence
    profile: CapabilityProfile
    record: CompatibilityRecord
    detector: CapabilityDetector

def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')

def tested_shape_fingerprint(manifest: Mapping[str, object]) -> str:
    return sha256(_canonical_json_bytes(manifest)).hexdigest()

def corpus_digest(records: Sequence[tuple[str, bytes]]) -> str:
    digest = sha256()
    for label, payload in records:
        label_bytes = label.encode('utf-8')
        digest.update(len(label_bytes).to_bytes(8, 'big'))
        digest.update(label_bytes)
        digest.update(len(payload).to_bytes(8, 'big'))
        digest.update(payload)
    return digest.hexdigest()

def evidence_fingerprint(*, tested_shape_fingerprint: str, corpus_digest: str, assertion_ids: Sequence[str], snapshot_date: str, official_source_refs: Sequence[str], sdk_client_version: str | None) -> str:
    payload = {
        'api_family': 'openai_agents_api', 'api_status': API_STATUS,
        'snapshot_date': snapshot_date, 'official_source_refs': sorted(official_source_refs),
        'sdk_client_version': sdk_client_version, 'corpus_version': CORPUS_VERSION,
        'tested_shape_fingerprint': tested_shape_fingerprint, 'corpus_digest': corpus_digest,
        'assertion_ids': sorted(assertion_ids),
    }
    return sha256(_canonical_json_bytes(payload)).hexdigest()

def _build_evidence() -> OpenAIAgentsConformanceEvidence:
    shape_fp = tested_shape_fingerprint(TESTED_SHAPE_MANIFEST)
    corpus_fp = corpus_digest(RAW_CORPUS)
    evidence_fp = evidence_fingerprint(
        tested_shape_fingerprint=shape_fp, corpus_digest=corpus_fp,
        assertion_ids=ASSERTION_IDS, snapshot_date=SNAPSHOT_DATE,
        official_source_refs=OFFICIAL_SOURCE_REFS, sdk_client_version=None,
    )
    return OpenAIAgentsConformanceEvidence(
        api_family='openai_agents_api', api_status=API_STATUS, snapshot_date=SNAPSHOT_DATE,
        official_source_refs=OFFICIAL_SOURCE_REFS, sdk_client_version=None,
        corpus_version=CORPUS_VERSION,
        tested_endpoint_families=tuple(TESTED_SHAPE_MANIFEST['endpoint_families']),
        protected_fields=('session_state','agent_config','environment','metadata','native_compaction','native_recovery','tools','mcp','subagents','cancellation','usage_accounting','unknown_beta_fields'),
        tested_input_event_shapes=(*TESTED_SHAPE_MANIFEST['documented_exact_input_event_types'], *TESTED_SHAPE_MANIFEST['documented_input_event_categories']),
        tested_stream_event_shapes=tuple(TESTED_SHAPE_MANIFEST['stream_events']),
        tested_identifier_fields=tuple(TESTED_SHAPE_MANIFEST['identifier_fields']),
        assertion_ids=ASSERTION_IDS, tested_shape_fingerprint=shape_fp,
        corpus_digest=corpus_fp, evidence_fingerprint=evidence_fp,
        evidence_id=f'token-openai-agents-api-conformance-1:{SNAPSHOT_DATE}:{evidence_fp}',
    )

def build_openai_agents_conformance() -> OpenAIAgentsConformanceBundle:
    evidence = _build_evidence()
    profile = CapabilityProfile(key=OPENAI_AGENTS_API_KEY, stateful_sessions=True, native_context_management=True, evidence_id=evidence.evidence_id)
    record = CompatibilityRecord(key=OPENAI_AGENTS_API_KEY, state=CompatibilityState.PASSTHROUGH_ONLY, evidence_id=evidence.evidence_id, reason='offline_conformance_only')
    capabilities = CapabilityRegistry()
    capabilities.register(profile)
    compatibility = CompatibilityRegistry()
    compatibility.register(record)
    return OpenAIAgentsConformanceBundle(evidence, profile, record, CapabilityDetector(capabilities, compatibility))

def _certification_state_passthrough_only() -> bool:
    b = build_openai_agents_conformance()
    return b.record.state is CompatibilityState.PASSTHROUGH_ONLY and b.record.reason == 'offline_conformance_only' and b.profile.evidence_id == b.record.evidence_id

def _corpus_digest_matches_raw_ordered_bytes() -> bool:
    return corpus_digest(RAW_CORPUS) == build_openai_agents_conformance().evidence.corpus_digest

def _idempotency_key_frozen() -> bool:
    p = json.loads(dict(INPUT_EVENT_FIXTURES)['input-message'].decode('utf-8'))
    return p.get('idempotency_key') == 'idem_fixture_001'

def _mcp_and_vault_fixture_covered() -> bool:
    p = json.loads(SESSION_CREATE_FIXTURE.decode('utf-8'))
    return p.get('vault_ids') == ['vault_fixture'] and any(t.get('type') == 'mcp' for t in p['agent']['tools']) and p.get('future_field') == {'opaque': True}

def _native_context_management_claim_bounded() -> bool:
    b = build_openai_agents_conformance()
    p = b.profile
    return p.stateful_sessions is True and p.native_context_management is True and p.streaming == 'unknown' and p.tool_calls == 'unknown' and p.reasoning_state == 'unknown' and p.exact_byte_preservation == 'unknown' and p.multimodal == 'unknown' and p.structured_output == 'unknown' and b.record.state is CompatibilityState.PASSTHROUGH_ONLY

def _near_match_non_inheritance() -> bool:
    b = build_openai_agents_conformance()
    near = (
        CapabilityKey('generic-openai','responses','openai'),
        CapabilityKey('generic-openai','chat_completions','openai'),
        CapabilityKey('generic-openai','openai_agents_api_v2','openai'),
        CapabilityKey('generic-openai','openai_agents_api','openai-compatible'),
        CapabilityKey('generic-openai','openai_agents_api','openai',model_family='gpt-future'),
        CapabilityKey('generic-openai','openai_agents_api','openai',client_version='1'),
        CapabilityKey('codex','openai_agents_api','openai'),
    )
    return all(b.detector.detect(k).profile is None and b.detector.detect(k).compatibility.state is CompatibilityState.PASSTHROUGH_ONLY and b.detector.detect(k).compatibility.reason == 'unknown_capability' for k in near)

def _official_sources_bound() -> bool:
    e = build_openai_agents_conformance().evidence
    return e.snapshot_date == SNAPSHOT_DATE and e.sdk_client_version is None and e.official_source_refs == OFFICIAL_SOURCE_REFS

def _stream_duplicate_and_order_frozen() -> bool:
    labels = tuple(label for label, _ in STREAM_EVENT_FRAMES)
    frames = tuple(payload for _, payload in STREAM_EVENT_FRAMES)
    return labels[-2:] == ('duplicate-frame','duplicate-frame-copy') and frames[-2] == frames[-1] and frames.count(frames[-2]) == 2 and labels.index('output-text-delta-a') < labels.index('output-text-delta-b')

def _stream_identifiers_frozen() -> bool:
    parsed = {
        label: json.loads(frame.decode('utf-8'))
        for label, frame in STREAM_EVENT_FRAMES
    }
    known = {
        label: event
        for label, event in parsed.items()
        if label != 'unknown-future-event'
    }
    if not all('event_id' in event for event in known.values()):
        return False
    for field in ('session_id', 'turn_id', 'item_id', 'output_index', 'content_index', 'summary_index'):
        if not any(field in event for event in known.values()):
            return False
    return (
        parsed['session-created']['session']['id'] == 'sess_fixture'
        and parsed['subagent-created']['subagent']['session_id'] == 'sess_fixture'
    )

def _unknown_event_frozen() -> bool:
    return any(json.loads(f.decode('utf-8')).get('type') == 'agent.session.future.event' and json.loads(f.decode('utf-8')).get('opaque') == {'nested':[1,2,3]} for _,f in STREAM_EVENT_FRAMES)

def openai_agents_conformance_cases() -> Mapping[str, Callable[[], bool]]:
    return {
        'certification_state_passthrough_only': _certification_state_passthrough_only,
        'corpus_digest_matches_raw_ordered_bytes': _corpus_digest_matches_raw_ordered_bytes,
        'idempotency_key_frozen': _idempotency_key_frozen,
        'mcp_and_vault_fixture_covered': _mcp_and_vault_fixture_covered,
        'native_context_management_claim_bounded': _native_context_management_claim_bounded,
        'near_match_non_inheritance': _near_match_non_inheritance,
        'official_sources_bound': _official_sources_bound,
        'stream_duplicate_and_order_frozen': _stream_duplicate_and_order_frozen,
        'stream_identifiers_frozen': _stream_identifiers_frozen,
        'unknown_event_frozen': _unknown_event_frozen,
    }

def run_openai_agents_conformance() -> tuple[ConformanceResult, ...]:
    results = run_conformance(openai_agents_conformance_cases())
    require_conformance(results)
    return results
