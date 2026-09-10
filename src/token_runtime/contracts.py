from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Protocol, runtime_checkable

from .model import RequestEnvelope

if TYPE_CHECKING:
    from .capabilities import CapabilityKey, CapabilityProfile


@runtime_checkable
class ClientAdapterContract(Protocol):
    @property
    def client_id(self) -> str: ...

    @property
    def protocol_ids(self) -> tuple[str, ...]: ...


@runtime_checkable
class ProtocolAdapterContract(Protocol):
    @property
    def protocol_id(self) -> str: ...

    def parse(self, payload: Mapping[str, Any]) -> RequestEnvelope: ...

    def serialize(self, envelope: RequestEnvelope) -> dict[str, Any]: ...

@runtime_checkable
class CapabilityProviderContract(Protocol):
    @property
    def provider_id(self) -> str: ...

    def profile_for(self, key: "CapabilityKey") -> "CapabilityProfile | None": ...


@runtime_checkable
class TokenizerAdapterContract(Protocol):
    @property
    def tokenizer_id(self) -> str: ...

    def estimate(self, text: str) -> int: ...


@runtime_checkable
class StrategyContract(Protocol):
    @property
    def strategy_id(self) -> str: ...


@runtime_checkable
class BenchmarkAdapterContract(Protocol):
    @property
    def benchmark_id(self) -> str: ...

    @property
    def assertion_ids(self) -> tuple[str, ...]: ...
