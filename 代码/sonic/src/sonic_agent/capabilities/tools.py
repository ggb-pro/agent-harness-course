"""Tool registry, policy pipeline, safe failures and effect journal."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import PurePath
import re
from typing import Any, Callable, Protocol

from ..core.events import EventStore
from ..models.model import ToolCall


ToolHandler = Callable[[dict[str, Any]], Any]
ArgumentAuditor = Callable[[dict[str, Any]], dict[str, Any]]


_SAFE_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_TOOL_NAME = re.compile(r"[a-z][a-z0-9_.-]{0,127}\Z")


class ToolError(RuntimeError):
    """A classified Tool failure whose public fields are safe to persist."""

    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        retryable: bool = False,
        denied: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        if not isinstance(code, str) or _SAFE_ERROR_CODE.fullmatch(code) is None:
            raise ValueError("tool error code is invalid")
        if not isinstance(safe_message, str) or not safe_message or len(safe_message) > 500:
            raise ValueError("tool safe_message is invalid")
        if type(retryable) is not bool or type(denied) is not bool:
            raise TypeError("tool error flags must be bools")
        if details is not None and not isinstance(details, dict):
            raise TypeError("tool error details must be an object")
        safe_details = dict(details or {})
        json.dumps(safe_details, ensure_ascii=False)
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable
        self.denied = denied
        self.details = safe_details


@dataclass(frozen=True)
class ToolSpec:
    """Stable Tool metadata. Handler validation remains the security boundary."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    read_only: bool = False
    version: str = "1"

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _TOOL_NAME.fullmatch(self.name) is None:
            raise ValueError("tool spec name is invalid")
        if not isinstance(self.description, str):
            raise TypeError("tool spec description must be a string")
        if not isinstance(self.input_schema, dict):
            raise TypeError("tool spec input_schema must be an object")
        if type(self.read_only) is not bool:
            raise TypeError("tool spec read_only must be a bool")
        if not isinstance(self.version, str) or not self.version:
            raise ValueError("tool spec version cannot be empty")
        json.dumps(self.input_schema, ensure_ascii=False)


@dataclass(frozen=True)
class ToolOutput:
    """Full model-visible value plus a bounded, persistence-safe audit receipt."""

    value: Any
    audit: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.audit, dict):
            raise TypeError("tool output audit must be an object")
        json.dumps(self.value, ensure_ascii=False)
        json.dumps(self.audit, ensure_ascii=False)


@dataclass(frozen=True)
class _RegisteredTool:
    spec: ToolSpec
    handler: ToolHandler
    argument_auditor: ArgumentAuditor


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, _RegisteredTool] = {}

    def register(
        self,
        name: str,
        handler: ToolHandler,
        *,
        spec: ToolSpec | None = None,
        audit_arguments: ArgumentAuditor | None = None,
    ) -> None:
        if not isinstance(name, str) or _TOOL_NAME.fullmatch(name) is None:
            raise ValueError("tool name is invalid")
        if not callable(handler):
            raise TypeError("tool handler must be callable")
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        resolved_spec = spec or ToolSpec(name=name)
        if resolved_spec.name != name:
            raise ValueError("tool spec name must match registration name")
        auditor = audit_arguments or (lambda arguments: dict(arguments))
        self._tools[name] = _RegisteredTool(resolved_spec, handler, auditor)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def manifest(self) -> tuple[ToolSpec, ...]:
        return tuple(self._tools[name].spec for name in self.names)

    def spec(self, name: str) -> ToolSpec:
        try:
            return self._tools[name].spec
        except KeyError:
            raise ToolError(
                "unknown_tool",
                "tool is not registered for this runtime",
                denied=True,
            ) from None

    def audited_arguments(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            auditor = self._tools[name].argument_auditor
        except KeyError:
            return {}
        try:
            audited = auditor(dict(arguments))
            if not isinstance(audited, dict):
                raise TypeError("argument auditor must return an object")
            json.dumps(audited, ensure_ascii=False)
        except ToolError:
            raise
        except Exception:
            raise ToolError("invalid_argument", "tool arguments could not be audited") from None
        return audited

    def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        try:
            handler = self._tools[name].handler
        except KeyError:
            raise ToolError(
                "unknown_tool",
                "tool is not registered for this runtime",
                denied=True,
            ) from None
        return handler(dict(arguments))


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""


class Policy(Protocol):
    def evaluate(self, call: ToolCall) -> PolicyDecision: ...


class DenyPathPolicy:
    def __init__(self, forbidden_names: tuple[str, ...] = (".env", ".git")) -> None:
        self.forbidden_names = {name.casefold() for name in forbidden_names}

    def evaluate(self, call: ToolCall) -> PolicyDecision:
        for key, value in call.arguments.items():
            if "path" not in key.casefold() or not isinstance(value, str):
                continue
            parts = {part.casefold() for part in PurePath(value.replace("\\", "/")).parts}
            blocked = sorted(parts & self.forbidden_names)
            if blocked:
                return PolicyDecision(False, f"sensitive path component: {blocked[0]}")
        return PolicyDecision(True)


@dataclass
class EffectRecord:
    arguments_hash: str
    status: str
    result: Any = None
    error: str | None = None
    attempts: int = 0


class EffectJournal:
    def __init__(self) -> None:
        self.records: dict[str, EffectRecord] = {}

    @staticmethod
    def _hash(arguments: dict[str, Any]) -> str:
        body = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def execute(self, effect_id: str, arguments: dict[str, Any], operation: Callable[[], Any]) -> tuple[Any, bool]:
        arguments_hash = self._hash(arguments)
        existing = self.records.get(effect_id)
        if existing and existing.arguments_hash != arguments_hash:
            raise ValueError("effect id reused with different arguments")
        if existing and existing.status == "completed":
            return existing.result, True

        record = existing or EffectRecord(arguments_hash, "planned")
        self.records[effect_id] = record
        record.status = "started"
        record.attempts += 1
        try:
            record.result = operation()
        except ToolError as exc:
            record.status = "failed"
            record.error = exc.safe_message
            raise
        except Exception:
            record.status = "failed"
            record.error = "tool execution failed unexpectedly"
            raise
        record.status = "completed"
        record.error = None
        return record.result, False


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    ok: bool
    value: Any = None
    error: str | None = None
    error_code: str | None = None
    retryable: bool = False
    denied: bool = False
    cached: bool = False


class ToolRuntime:
    def __init__(
        self,
        registry: ToolRegistry,
        event_store: EventStore,
        policies: list[Policy] | None = None,
        journal: EffectJournal | None = None,
    ) -> None:
        self.registry = registry
        self.event_store = event_store
        self.policies = list(policies or [])
        self.journal = journal or EffectJournal()

    def run(self, run_id: str, call: ToolCall) -> ToolResult:
        try:
            spec = self.registry.spec(call.name)
            audited_arguments = self.registry.audited_arguments(call.name, call.arguments)
        except ToolError as exc:
            self.event_store.append(run_id, "tool.requested", {
                "call_id": call.id, "tool": "<unregistered>", "arguments": {},
            })
            return self._record_failure(run_id, call, exc)

        self.event_store.append(run_id, "tool.requested", {
            "call_id": call.id,
            "tool": call.name,
            "arguments": audited_arguments,
            "read_only": spec.read_only,
            "tool_version": spec.version,
        })
        for policy in self.policies:
            decision = policy.evaluate(call)
            if not decision.allowed:
                self.event_store.append(run_id, "tool.denied", {
                    "call_id": call.id,
                    "tool": call.name,
                    "code": "policy_denied",
                    "reason": decision.reason,
                })
                return ToolResult(
                    call.id,
                    False,
                    error=decision.reason,
                    error_code="policy_denied",
                    denied=True,
                )

        effect_id = f"{run_id}:{call.id}"
        try:
            if spec.read_only:
                raw_output = self.registry.execute(call.name, call.arguments)
                cached = False
            else:
                raw_output, cached = self.journal.execute(
                    effect_id,
                    call.arguments,
                    lambda: self.registry.execute(call.name, call.arguments),
                )
        except ToolError as exc:
            return self._record_failure(run_id, call, exc)
        except Exception:
            return self._record_failure(
                run_id,
                call,
                ToolError("internal_error", "tool execution failed unexpectedly"),
            )

        if isinstance(raw_output, ToolOutput):
            value = raw_output.value
            completed_payload = {
                "call_id": call.id,
                "tool": call.name,
                "receipt": raw_output.audit,
                "cached": cached,
            }
        else:
            value = raw_output
            completed_payload = {
                "call_id": call.id,
                "tool": call.name,
                "value": value,
                "cached": cached,
            }
        self.event_store.append(run_id, "tool.completed", completed_payload)
        return ToolResult(call.id, True, value=value, cached=cached)

    def _record_failure(
        self,
        run_id: str,
        call: ToolCall,
        error: ToolError,
    ) -> ToolResult:
        event_type = "tool.denied" if error.denied else "tool.failed"
        tool_name = "<unregistered>" if error.code == "unknown_tool" else call.name
        self.event_store.append(run_id, event_type, {
            "call_id": call.id,
            "tool": tool_name,
            "code": error.code,
            "message": error.safe_message,
            "retryable": error.retryable,
            "details": error.details,
        })
        return ToolResult(
            call.id,
            False,
            error=error.safe_message,
            error_code=error.code,
            retryable=error.retryable,
            denied=error.denied,
        )
