"""Model-side data types and a deterministic fake provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AssistantResponse:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)


class Provider(Protocol):
    def complete(self, messages: list[dict[str, Any]]) -> AssistantResponse: ...


class FakeProvider:
    """Returns predefined responses and records the requests it observed."""

    def __init__(self, responses: list[AssistantResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict[str, Any]]] = []

    def complete(self, messages: list[dict[str, Any]]) -> AssistantResponse:
        self.calls.append([dict(message) for message in messages])
        if not self._responses:
            raise RuntimeError("FakeProvider response script exhausted")
        return self._responses.pop(0)

    @property
    def remaining(self) -> int:
        return len(self._responses)

