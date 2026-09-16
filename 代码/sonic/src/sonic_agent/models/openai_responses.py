"""OpenAI Responses API adapter with explicit egress and audit boundaries."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import ipaddress
import os
import re
import time
from typing import Any
from urllib.parse import urlsplit

from .model import (
    AssistantResponse,
    ModelAccess,
    ModelResponseMetadata,
    ProviderError,
    ProviderInfo,
    TokenUsage,
    canonical_origin,
)


_SAFE_ID = re.compile(r"[A-Za-z0-9._:/-]{1,200}\Z")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_OPENAI_ORIGIN = "https://api.openai.com"


def _field(value: Any, name: str, default: Any = None) -> Any:
    try:
        if isinstance(value, Mapping):
            return value.get(name, default)
        return getattr(value, name, default)
    except Exception:
        return default


def _safe_identifier(value: Any) -> str | None:
    return value if isinstance(value, str) and _SAFE_ID.fullmatch(value) else None


def _safe_label(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 200:
        return None
    return value if all(character.isprintable() for character in value) else None


def _elapsed_ms(clock: Callable[[], float], started: float) -> int:
    return max(0, int(round((clock() - started) * 1000)))


class OpenAIResponsesProvider:
    """Synchronous Responses adapter with a fixed, hardened SDK transport."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "https://api.openai.com/v1",
        max_output_tokens: int | None = None,
        timeout_seconds: float = 60.0,
        credential_env: str | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        if max_output_tokens is not None and max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        self._base_url, origin, transport = self._validate_endpoint(base_url)
        if credential_env is not None and not (
            isinstance(credential_env, str) and _ENV_NAME.fullmatch(credential_env)
        ):
            raise ValueError("credential_env must be a valid environment variable name")
        if transport == "remote" and credential_env is None:
            if origin != _OPENAI_ORIGIN:
                raise ValueError(
                    "custom remote endpoints require an explicit credential_env"
                )
            credential_env = "OPENAI_API_KEY"
        self._info = ProviderInfo("openai", model.strip(), transport, origin)
        self._max_output_tokens = max_output_tokens
        self._timeout_seconds = float(timeout_seconds)
        self._client: Any | None = None
        self._credential_env = credential_env
        self._monotonic = monotonic

    @property
    def info(self) -> ProviderInfo:
        return self._info

    def __repr__(self) -> str:
        return (
            "OpenAIResponsesProvider("
            f"model={self.info.requested_model!r}, transport={self.info.transport!r}, "
            f"endpoint_origin={self.info.endpoint_origin!r})"
        )

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        access: ModelAccess | None = None,
    ) -> AssistantResponse:
        if access is None:
            policy = ModelAccess()
        elif isinstance(access, ModelAccess):
            policy = access
        else:
            raise TypeError("access must be a ModelAccess instance")
        if not policy.allows(self.info):
            raise ProviderError(
                "egress_denied",
                "remote model access was not authorized for this endpoint",
            )

        input_items = self._serialize_messages(messages)
        client = self._client_or_create()
        request: dict[str, Any] = {
            "model": self.info.requested_model,
            "input": input_items,
            "store": False,
        }
        if self._max_output_tokens is not None:
            request["max_output_tokens"] = self._max_output_tokens
        started = self._monotonic()
        failure: ProviderError | None = None
        try:
            response = client.responses.create(**request)
        except Exception as exc:
            failure = self._classify_sdk_error(exc, _elapsed_ms(self._monotonic, started))
        if failure is not None:
            raise failure
        latency_ms = _elapsed_ms(self._monotonic, started)
        return self._parse_response(response, latency_ms)

    @staticmethod
    def _validate_endpoint(base_url: str) -> tuple[str, str, str]:
        parse_failed = False
        try:
            parsed = urlsplit(base_url)
        except (TypeError, ValueError):
            parse_failed = True
            parsed = None
        if parse_failed:
            raise ValueError("base_url must be a valid HTTP(S) URL")
        assert parsed is not None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url must be an HTTP(S) URL without credentials, query or fragment")
        invalid_port = False
        try:
            port = parsed.port
        except ValueError:
            invalid_port = True
            port = None
        if invalid_port:
            raise ValueError("base_url contains an invalid port")

        host = parsed.hostname.lower()
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = host == "localhost"
        transport = "local" if is_loopback else "remote"
        if transport == "remote" and parsed.scheme != "https":
            raise ValueError("remote model endpoints must use HTTPS")

        origin_host = f"[{host}]" if ":" in host else host
        origin = canonical_origin(f"{parsed.scheme}://{origin_host}{f':{port}' if port else ''}")
        return base_url.rstrip("/"), origin, transport

    def _client_or_create(self) -> Any:
        if self._client is not None:
            return self._client

        credential_env = self._credential_env
        if credential_env is None:
            api_key = "local-no-credential"
        else:
            credential_lookup_failed = False
            try:
                api_key = os.environ.get(credential_env)
            except Exception:
                credential_lookup_failed = True
                api_key = None
            if credential_lookup_failed:
                raise ProviderError("configuration", "model credential lookup failed")
            if not api_key:
                raise ProviderError(
                    "missing_api_key",
                    "required model credential is missing",
                )

        dependency_missing = False
        try:
            from openai import DefaultHttpxClient, OpenAI
        except ImportError:
            dependency_missing = True
        if dependency_missing:
            raise ProviderError(
                "missing_dependency", "install sonic-agent[openai] to use the OpenAI provider"
            )
        http_client = None
        initialization_failed = False
        try:
            http_client = DefaultHttpxClient(
                timeout=self._timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            )
            self._client = OpenAI(
                api_key=api_key,
                base_url=self._base_url,
                timeout=self._timeout_seconds,
                max_retries=0,
                http_client=http_client,
            )
        except Exception:
            initialization_failed = True
            close = getattr(http_client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        if initialization_failed:
            raise ProviderError(
                "configuration",
                "model client initialization failed",
            )
        return self._client

    @staticmethod
    def _serialize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(messages, list) or not messages:
            raise ProviderError("invalid_request", "model messages must be a non-empty list")
        items: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, Mapping):
                raise ProviderError("invalid_request", "each model message must be an object")
            role = message.get("role")
            if role == "tool":
                raise ProviderError(
                    "unsupported_input",
                    "the text-only provider does not accept tool result history",
                )
            if role not in {"user", "assistant", "system", "developer"}:
                raise ProviderError("invalid_request", "model message role is unsupported")
            content = message.get("content", "")
            if not isinstance(content, str):
                raise ProviderError("invalid_request", "text message content must be a string")
            if content:
                items.append({"role": role, "content": content})
            if role == "assistant":
                tool_calls = message.get("tool_calls", ())
                if not isinstance(tool_calls, (list, tuple)):
                    raise ProviderError("invalid_request", "assistant tool_calls must be a list")
                if tool_calls:
                    raise ProviderError(
                        "unsupported_input",
                        "the text-only provider does not accept function call history",
                    )
        if not items:
            raise ProviderError("invalid_request", "model input cannot be empty")
        return items

    def _parse_response(self, response: Any, latency_ms: int) -> AssistantResponse:
        status = _field(response, "status")
        request_id = _safe_identifier(_field(response, "_request_id"))
        if status != "completed":
            remote_error_code = _field(_field(response, "error"), "code")
            if status == "failed" and remote_error_code in {"server_error", "internal_error"}:
                code, message, retryable = "unavailable", "model service failed while generating a response", True
            elif status == "failed" and remote_error_code in {"rate_limit_error", "rate_limit_exceeded"}:
                code, message, retryable = "rate_limit", "model service rate limit was reached", True
            elif status == "failed" and remote_error_code in {"timeout", "request_timeout"}:
                code, message, retryable = "timeout", "model service request timed out", True
            elif status == "incomplete":
                code, message, retryable = "incomplete", "model response was incomplete", False
            else:
                code, message, retryable = "invalid_response", "model response did not complete successfully", False
            raise ProviderError(
                code,
                message,
                retryable=retryable,
                request_id=request_id,
                latency_ms=latency_ms,
            )

        output = _field(response, "output", ())
        if not isinstance(output, (list, tuple)):
            raise ProviderError(
                "invalid_response",
                "model response output is invalid",
                request_id=request_id,
                latency_ms=latency_ms,
            )
        for item in output:
            if _field(item, "type") == "function_call":
                raise ProviderError(
                    "unsupported_response",
                    "the text-only provider does not accept model function calls",
                    request_id=request_id,
                    latency_ms=latency_ms,
                )

        text = _field(response, "output_text", "")
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise ProviderError(
                "invalid_response", "model response text is invalid",
                request_id=request_id, latency_ms=latency_ms,
            )
        if not text:
            raise ProviderError(
                "invalid_response", "model response contained no text",
                request_id=request_id, latency_ms=latency_ms,
            )

        metadata = ModelResponseMetadata(
            provider=self.info.provider,
            requested_model=self.info.requested_model,
            resolved_model=_safe_label(_field(response, "model")),
            response_id=_safe_identifier(_field(response, "id")),
            request_id=request_id,
            status=status,
            latency_ms=latency_ms,
            usage=self._parse_usage(_field(response, "usage")),
        )
        return AssistantResponse(text=text, metadata=metadata)

    @staticmethod
    def _parse_usage(usage: Any) -> TokenUsage | None:
        if usage is None:
            return None
        values = [_field(usage, name) for name in ("input_tokens", "output_tokens", "total_tokens")]
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
            return None
        input_details = _field(usage, "input_tokens_details")
        output_details = _field(usage, "output_tokens_details")
        cached = _field(input_details, "cached_tokens", 0)
        reasoning = _field(output_details, "reasoning_tokens", 0)
        cached = cached if isinstance(cached, int) and not isinstance(cached, bool) and cached >= 0 else 0
        reasoning = reasoning if isinstance(reasoning, int) and not isinstance(reasoning, bool) and reasoning >= 0 else 0
        return TokenUsage(values[0], values[1], values[2], cached, reasoning)

    @staticmethod
    def _classify_sdk_error(exc: Exception, latency_ms: int) -> ProviderError:
        names = {kind.__name__ for kind in type(exc).__mro__}
        try:
            status_code = getattr(exc, "status_code", None)
        except Exception:
            status_code = None
        status_code = status_code if isinstance(status_code, int) else None
        try:
            request_id = _safe_identifier(getattr(exc, "request_id", None))
        except Exception:
            request_id = None

        if "AuthenticationError" in names or status_code == 401:
            code, message, retryable = "auth", "model service rejected the credential", False
        elif "PermissionDeniedError" in names or status_code == 403:
            code, message, retryable = "permission", "model service denied this request", False
        elif "RateLimitError" in names or status_code == 429:
            code, message, retryable = "rate_limit", "model service rate limit was reached", True
        elif "APITimeoutError" in names or "TimeoutError" in names or status_code == 408:
            code, message, retryable = "timeout", "model service request timed out", True
        elif "APIConnectionError" in names or "ConnectionError" in names:
            code, message, retryable = "network", "model service connection failed", True
        elif status_code == 409:
            code, message, retryable = "conflict", "model service reported a request conflict", True
        elif (status_code is not None and status_code >= 500) or "InternalServerError" in names:
            code, message, retryable = "unavailable", "model service is temporarily unavailable", True
        elif status_code is not None and 400 <= status_code < 500:
            code, message, retryable = "invalid_request", "model service rejected the request", False
        else:
            code, message, retryable = "internal", "model provider failed unexpectedly", False
        return ProviderError(
            code,
            message,
            retryable=retryable,
            status_code=status_code,
            request_id=request_id,
            latency_ms=latency_ms,
        )
