"""Single-run model/tool loop with revision, hard limits and explicit completion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import uuid
from typing import Any, Callable

from .completion import CompletionContract, CompletionDecision
from .events import EventStore, utc_now
from .model import Provider
from .state import project_state
from .tools import ToolRuntime


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
        self.provider = provider
        self.tools = tools
        self.event_store = event_store
        self.max_turns = max_turns
        self.max_tool_calls = max_tool_calls
        self.max_repeated_observations = max_repeated_observations
        self.deadline_at = deadline_at
        self.cancel_requested = cancel_requested or (lambda: False)
        self.clock = clock
        self.completion = completion

    def run(self, prompt: str, run_id: str | None = None) -> RunResult:
        run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
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
            emit("model.requested", {"turn": turn})
            try:
                response = self.provider.complete(messages)
            except Exception as exc:
                return finish("failed", f"model call failed: {exc}")

            emit("model.responded", {
                "turn": turn, "text": response.text,
                "tool_calls": [call.name for call in response.tool_calls],
            })
            if not response.tool_calls:
                if self.completion is None:
                    decision = CompletionDecision("unverified", "no completion contract supplied")
                else:
                    try:
                        decision = self.completion.verify(prompt, response.text, self.event_store.load(run_id))
                    except Exception as exc:
                        decision = CompletionDecision("unverified", f"completion check unavailable: {exc}")
                emit("run.verification", {"status": decision.status, "reason": decision.reason})
                if decision.status == "completed":
                    emit("run.completed", {"answer": response.text})
                    return RunResult(run_id, "completed", answer=response.text)
                return finish(decision.status, decision.reason or "completion check did not pass", response.text)

            messages.append({"role": "assistant", "content": response.text})
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
