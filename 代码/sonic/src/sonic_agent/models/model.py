"""Stable model boundary, audit metadata and a deterministic fake provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit


Transport = Literal["test", "local", "remote"]


def canonical_origin(value: str) -> str:
    """Return a strict, comparable origin (scheme + host + optional port)."""

    parse_failed = False
    try:
        parsed = urlsplit(value)
    except (TypeError, ValueError):
        parse_failed = True
        parsed = None
    if parse_failed:
        raise ValueError("expected a valid HTTP(S) origin")
    assert parsed is not None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("expected an HTTP(S) origin without path, credentials, query or fragment")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    invalid_port = False
    try:
        parsed_port = parsed.port
    except ValueError:
        invalid_port = True
        parsed_port = None
    if invalid_port:
        raise ValueError("origin contains an invalid port")
    default_port = 443 if parsed.scheme == "https" else 80
    port = f":{parsed_port}" if parsed_port and parsed_port != default_port else ""
    return f"{parsed.scheme}://{host}{port}"


@dataclass(frozen=True)
class ProviderInfo:
    provider: str
    requested_model: str
    transport: Transport
    endpoint_origin: str | None = None


@dataclass(frozen=True)
class ModelAccess:
    """Per-run outbound authorization. This is an app guard, not a firewall."""

    allow_remote: bool = False
    allowed_origins: tuple[str, ...] = field(default_factory=tuple)
    grant_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.allow_remote) is not bool:
            raise TypeError("allow_remote must be a bool")
        if self.grant_id is not None and (
            not isinstance(self.grant_id, str) or not self.grant_id or len(self.grant_id) > 256
        ):
            raise ValueError("grant_id must be a non-empty string of at most 256 characters")
        normalized = tuple(canonical_origin(origin) for origin in self.allowed_origins)
        object.__setattr__(self, "allowed_origins", normalized)

    def allows(self, info: ProviderInfo) -> bool:
        if info.transport in {"test", "local"}:
            return True
        if info.transport != "remote" or info.endpoint_origin is None:
            return False
        return self.allow_remote and info.endpoint_origin in self.allowed_origins


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int = 0
    reasoning_output_tokens: int = 0


@dataclass(frozen=True)
class ModelResponseMetadata:
    provider: str
    requested_model: str
    resolved_model: str | None
    response_id: str | None
    request_id: str | None
    status: str
    latency_ms: int
    usage: TokenUsage | None = None


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AssistantResponse:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)
    metadata: ModelResponseMetadata | None = None


class ProviderError(RuntimeError):
    """A classified provider failure whose string form is safe to persist."""

    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        request_id: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable
        self.status_code = status_code
        self.request_id = request_id
        self.latency_ms = latency_ms


class Provider(Protocol):
    @property
    def info(self) -> ProviderInfo: ...

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        access: ModelAccess | None = None,
    ) -> AssistantResponse: ...


class FakeProvider:
    """Returns predefined responses and records the requests it observed."""

    def __init__(self, responses: list[AssistantResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict[str, Any]]] = []

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo("fake", "scripted", "test")

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        access: ModelAccess | None = None,
    ) -> AssistantResponse:
        del access
        self.calls.append([dict(message) for message in messages])
        if not self._responses:
            raise ProviderError(
                "test_script_exhausted",
                "FakeProvider response script exhausted",
            )
        return self._responses.pop(0)

    @property
    def remaining(self) -> int:
        return len(self._responses)

