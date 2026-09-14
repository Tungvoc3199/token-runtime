from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol

from .adapters import ChatCompletionsAdapter, ResponsesAdapter
from .model import RequestEnvelope


class ProtocolAdapter(Protocol):
    name: str

    def parse(self, payload: Mapping[str, Any]) -> RequestEnvelope: ...

    def serialize(self, envelope: RequestEnvelope) -> dict[str, Any]: ...


AdapterFactory = Callable[[], ProtocolAdapter]


class DuplicateProtocolAdapterError(ValueError):
    pass


class ProtocolAdapterRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, AdapterFactory] = {}

    @staticmethod
    def _normalize(path: str) -> str:
        return path.split("?", 1)[0]

    def register(self, endpoint: str, factory: AdapterFactory) -> None:
        endpoint = self._normalize(endpoint)
        if endpoint in self._factories:
            raise DuplicateProtocolAdapterError(
                f"duplicate protocol endpoint: {endpoint}"
            )
        self._factories[endpoint] = factory

    def resolve(self, path: str) -> ProtocolAdapter | None:
        factory = self._factories.get(self._normalize(path))
        return None if factory is None else factory()


def default_protocol_adapter_registry() -> ProtocolAdapterRegistry:
    registry = ProtocolAdapterRegistry()
    registry.register("/v1/responses", ResponsesAdapter)
    registry.register("/v1/chat/completions", ChatCompletionsAdapter)
    return registry
