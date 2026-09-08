"""A deliberately small, evented model/tool loop."""

from __future__ import annotations

from dataclasses import dataclass
import uuid
from typing import Any

from .events import EventStore
from .model import Provider
from .tools import ToolRuntime


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str
    answer: str | None = None
    error: str | None = None


class AgentRunner:
    def __init__(self, provider: Provider, tools: ToolRuntime, event_store: EventStore, max_turns: int = 8) -> None:
        if max_turns <= 0:
            raise ValueError("max_turns must be positive")
        self.provider = provider
        self.tools = tools
        self.event_store = event_store
        self.max_turns = max_turns

    def run(self, prompt: str, run_id: str | None = None) -> RunResult:
        run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        self.event_store.append(run_id, "run.started", {"prompt": prompt})

        for turn in range(1, self.max_turns + 1):
            self.event_store.append(run_id, "model.requested", {"turn": turn})
            try:
                response = self.provider.complete(messages)
            except Exception as exc:
                self.event_store.append(run_id, "run.failed", {"error": str(exc), "stage": "model"})
                return RunResult(run_id, "failed", error=str(exc))

            self.event_store.append(run_id, "model.responded", {
                "turn": turn,
                "text": response.text,
                "tool_calls": [call.name for call in response.tool_calls],
            })
            if not response.tool_calls:
                self.event_store.append(run_id, "run.completed", {"answer": response.text})
                return RunResult(run_id, "completed", answer=response.text)

            messages.append({"role": "assistant", "content": response.text})
            for call in response.tool_calls:
                result = self.tools.run(run_id, call)
                messages.append({
                    "role": "tool",
                    "call_id": call.id,
                    "name": call.name,
                    "content": result.value if result.ok else {"error": result.error, "denied": result.denied},
                })

        error = f"maximum model turns exceeded: {self.max_turns}"
        self.event_store.append(run_id, "run.failed", {"error": error, "stage": "runner"})
        return RunResult(run_id, "failed", error=error)

