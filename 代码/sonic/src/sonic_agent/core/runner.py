"""Single-run model/tool loop with revision, hard limits and explicit completion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import inspect
import json
import uuid
from typing import Any, Callable

from .completion import CompletionContract, CompletionDecision
from .events import EventStore, utc_now
from ..models.model import ModelAccess, ModelResponseMetadata, Provider, ProviderError, ProviderInfo
from .state import project_state
from ..capabilities.tools import ToolRuntime


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str
    answer: str | None = None
    error: str | None = None


class AgentRunner:
    def __init__(
        self,
        provider: Provider,
        tools: ToolRuntime,
        event_store: EventStore,
        max_turns: int = 8,
        *,
        max_tool_calls: int = 32,
        max_repeated_observations: int = 2,
        deadline_at: str | None = None,
        cancel_requested: Callable[[], bool] | None = None,
        clock: Callable[[], str] = utc_now,
        completion: CompletionContract | None = None,
    ) -> None:
        if max_turns <= 0 or max_tool_calls <= 0 or max_repeated_observations <= 0:
            raise ValueError("model, tool and repetition limits must be positive")
        if deadline_at is not None and datetime.fromisoformat(deadline_at).tzinfo is None:
            raise ValueError("deadline_at must include a timezone")
        try:
            provider_info = provider.info
        except Exception:
            raise TypeError("provider must expose a stable ProviderInfo via .info") from None
        complete = getattr(provider, "complete", None)
        if not isinstance(provider_info, ProviderInfo) or not callable(complete):
            raise TypeError("provider must implement the current Provider contract")
        try:
            complete_signature = inspect.signature(complete)
        except (TypeError, ValueError):
            raise TypeError("provider.complete must expose an inspectable current signature") from None
        try:
            complete_signature.bind([], access=ModelAccess())
        except TypeError:
            raise TypeError("provider.complete must accept messages and the access keyword") from None
        self.provider = provider
        self.provider_info = provider_info
        self.tools = tools
        self.event_store = event_store
        self.max_turns = max_turns
        self.max_tool_calls = max_tool_calls
        self.max_repeated_observations = max_repeated_observations
        self.deadline_at = deadline_at
        self.cancel_requested = cancel_requested or (lambda: False)
        self.clock = clock
        self.completion = completion

    def run(
        self,
        prompt: str,
        run_id: str | None = None,
        *,
        model_access: ModelAccess | None = None,
    ) -> RunResult:
        run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
        if model_access is None:
            access = ModelAccess()
        elif isinstance(model_access, ModelAccess):
            access = model_access
        else:
            raise TypeError("model_access must be a ModelAccess instance")
        if self.event_store.load(run_id):
            raise ValueError(f"run already exists: {run_id}; resume is not implemented")
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        revision = 0

        def emit(event_type: str, payload: dict[str, Any]) -> None:
            nonlocal revision
            event = self.event_store.append(run_id, event_type, payload, expected_revision=revision)
            revision = event.sequence

        def finish(status: str, reason: str, answer: str | None = None) -> RunResult:
            event_type = {
                "failed": "run.failed",
                "unverified": "run.unverified",
                "cancelled": "run.cancelled",
                "budget_exhausted": "run.budget_exhausted",
            }[status]
            payload = {"answer": answer, "reason": reason} if status == "unverified" else {"reason": reason}
            if status == "failed":
                payload = {"error": reason}
            emit(event_type, payload)
            return RunResult(run_id, status, answer=answer, error=reason)

        emit("run.started", {"prompt": prompt, "limits": {
            "max_turns": self.max_turns,
            "max_tool_calls": self.max_tool_calls,
            "max_repeated_observations": self.max_repeated_observations,
            "deadline_at": self.deadline_at,
        }})

        while True:
            state = project_state(self.event_store.load(run_id))
            revision = state.revision
            if self.cancel_requested():
                return finish("cancelled", "cancellation requested")
            if self.deadline_at is not None and datetime.fromisoformat(self.clock()) >= datetime.fromisoformat(self.deadline_at):
                return finish("budget_exhausted", "run deadline exceeded")
            if state.model_calls >= self.max_turns:
                return finish("budget_exhausted", f"maximum model turns exceeded: {self.max_turns}")
            if state.repeated_observations >= self.max_repeated_observations:
                return finish("failed", "repeated identical tool action and observation without progress")

            turn = state.model_calls + 1
            provider_info = self.provider_info
            provider_payload = self._provider_payload(provider_info)
            if not access.allows(provider_info):
                emit("model.denied", {
                    "turn": turn,
                    **provider_payload,
                    "grant_ref": self._grant_reference(access.grant_id),
                    "reason": "remote model access was not authorized for this endpoint",
                })
                return finish("failed", "model call failed [egress_denied]: remote model access was not authorized")
            emit("model.requested", {
                "turn": turn,
                **provider_payload,
                "grant_ref": self._grant_reference(access.grant_id),
            })
            try:
                response = self.provider.complete(messages, access=access)
            except ProviderError as exc:
                emit("model.failed", {
                    "turn": turn,
                    **provider_payload,
                    "code": exc.code,
                    "retryable": exc.retryable,
                    "status_code": exc.status_code,
                    "request_id": exc.request_id,
                    "latency_ms": exc.latency_ms,
                    "message": exc.safe_message,
                })
                return finish("failed", f"model call failed [{exc.code}]: {exc.safe_message}")
            except Exception:
                emit("model.failed", {
                    "turn": turn,
                    **provider_payload,
                    "code": "internal",
                    "retryable": False,
                    "status_code": None,
                    "request_id": None,
                    "latency_ms": None,
                    "message": "model provider failed unexpectedly",
                })
                return finish("failed", "model call failed [internal]: model provider failed unexpectedly")

            emit("model.responded", {
                "turn": turn, "text": response.text,
                "tool_calls": [call.name for call in response.tool_calls],
                **provider_payload,
                **self._metadata_payload(response.metadata),
            })
            if not response.tool_calls:
                if self.completion is None:
                    decision = CompletionDecision("unverified", "no completion contract supplied")
                else:
                    try:
                        decision = self.completion.verify(prompt, response.text, self.event_store.load(run_id))
                    except Exception:
                        decision = CompletionDecision("unverified", "completion check unavailable")
                emit("run.verification", {"status": decision.status, "reason": decision.reason})
                if decision.status == "completed":
                    emit("run.completed", {"answer": response.text})
                    return RunResult(run_id, "completed", answer=response.text)
                return finish(decision.status, decision.reason or "completion check did not pass", response.text)

            messages.append({
                "role": "assistant",
                "content": response.text,
                "tool_calls": [
                    {"id": call.id, "name": call.name, "arguments": call.arguments}
                    for call in response.tool_calls
                ],
            })
            for call in response.tool_calls:
                state = project_state(self.event_store.load(run_id))
                revision = state.revision
                if self.cancel_requested():
                    return finish("cancelled", "cancellation requested")
                if self.deadline_at is not None and datetime.fromisoformat(self.clock()) >= datetime.fromisoformat(self.deadline_at):
                    return finish("budget_exhausted", "run deadline exceeded")
                if state.tool_calls >= self.max_tool_calls:
                    return finish("budget_exhausted", f"maximum tool calls exceeded: {self.max_tool_calls}")
                result = self.tools.run(run_id, call)
                revision = project_state(self.event_store.load(run_id)).revision
                observation = json.dumps({
                    "tool": call.name, "arguments": call.arguments,
                    "result": result.value if result.ok else {"error": result.error, "denied": result.denied},
                }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                emit("run.observed", {"fingerprint": hashlib.sha256(observation.encode("utf-8")).hexdigest()})
                messages.append({
                    "role": "tool", "call_id": call.id, "name": call.name,
                    "content": result.value if result.ok else {"error": result.error, "denied": result.denied},
                })

    @staticmethod
    def _provider_payload(info: ProviderInfo) -> dict[str, Any]:
        return {
            "provider": info.provider,
            "requested_model": info.requested_model,
            "transport": info.transport,
            "endpoint_origin": info.endpoint_origin,
        }

    @staticmethod
    def _grant_reference(grant_id: str | None) -> str | None:
        if grant_id is None:
            return None
        return f"sha256:{hashlib.sha256(grant_id.encode('utf-8')).hexdigest()[:16]}"

    @staticmethod
    def _metadata_payload(metadata: ModelResponseMetadata | None) -> dict[str, Any]:
        if metadata is None:
            return {
                "resolved_model": None,
                "response_id": None,
                "request_id": None,
                "response_status": None,
                "latency_ms": None,
                "usage": None,
            }
        usage = metadata.usage
        return {
            "resolved_model": metadata.resolved_model,
            "response_id": metadata.response_id,
            "request_id": metadata.request_id,
            "response_status": metadata.status,
            "latency_ms": metadata.latency_ms,
            "usage": None if usage is None else {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
                "cached_input_tokens": usage.cached_input_tokens,
                "reasoning_output_tokens": usage.reasoning_output_tokens,
            },
        }
