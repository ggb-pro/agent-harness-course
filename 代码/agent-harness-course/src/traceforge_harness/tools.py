"""Tool registry, policy pipeline and effect journal."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePath
from typing import Any, Callable, Protocol

from .events import EventStore
from .model import ToolCall


ToolHandler = Callable[[dict[str, Any]], Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, name: str, handler: ToolHandler) -> None:
        if not name:
            raise ValueError("tool name cannot be empty")
        if name in self._handlers:
            raise ValueError(f"tool already registered: {name}")
        self._handlers[name] = handler

    def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self._handlers:
            raise KeyError(f"unknown tool: {name}")
        return self._handlers[name](dict(arguments))


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
        except Exception as exc:
            record.status = "failed"
            record.error = str(exc)
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
        self.event_store.append(run_id, "tool.requested", {
            "call_id": call.id, "tool": call.name, "arguments": call.arguments,
        })
        for policy in self.policies:
            decision = policy.evaluate(call)
            if not decision.allowed:
                self.event_store.append(run_id, "tool.denied", {
                    "call_id": call.id, "tool": call.name, "reason": decision.reason,
                })
                return ToolResult(call.id, False, error=decision.reason, denied=True)

        effect_id = f"{run_id}:{call.id}"
        try:
            value, cached = self.journal.execute(
                effect_id,
                call.arguments,
                lambda: self.registry.execute(call.name, call.arguments),
            )
        except Exception as exc:
            self.event_store.append(run_id, "tool.failed", {
                "call_id": call.id, "tool": call.name, "error": str(exc),
            })
            return ToolResult(call.id, False, error=str(exc))

        self.event_store.append(run_id, "tool.completed", {
            "call_id": call.id, "tool": call.name, "value": value, "cached": cached,
        })
        return ToolResult(call.id, True, value=value, cached=cached)

