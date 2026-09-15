"""Authoritative run state rebuilt from the committed event stream."""

from __future__ import annotations

from dataclasses import dataclass

from .events import Event


TERMINAL = {"completed", "failed", "unverified", "cancelled", "budget_exhausted"}


@dataclass(frozen=True)
class RunState:
    run_id: str
    revision: int = 0
    status: str = "created"
    model_calls: int = 0
    tool_calls: int = 0
    max_turns: int = 0
    max_tool_calls: int = 0
    max_repeated_observations: int = 0
    deadline_at: str | None = None
    repeated_observations: int = 0
    answer: str | None = None
    error: str | None = None


def project_state(events: list[Event]) -> RunState:
    if not events:
        raise ValueError("cannot restore a run without events")
    run_id = events[0].run_id
    first = events[0]
    if first.type != "run.started":
        raise ValueError("run event stream must begin with run.started")
    limits = first.payload.get("limits", {})
    state = RunState(
        run_id=run_id,
        max_turns=int(limits.get("max_turns", 0)),
        max_tool_calls=int(limits.get("max_tool_calls", 0)),
        max_repeated_observations=int(limits.get("max_repeated_observations", 0)),
        deadline_at=limits.get("deadline_at"),
    )
    revision = 0
    model_calls = 0
    tool_calls = 0
    repeated_observations = 0
    previous_observation: str | None = None
    status = "running"
    answer = None
    error = None
    for event in events:
        if event.run_id != run_id or event.sequence != revision + 1:
            raise ValueError("run event sequence is missing, duplicated, or mixed")
        if revision and event.type == "run.started":
            raise ValueError("run.started cannot occur twice")
        if status in TERMINAL:
            raise ValueError("terminal run has trailing events")
        revision = event.sequence
        if event.type == "model.requested":
            model_calls += 1
        elif event.type == "tool.requested":
            tool_calls += 1
        elif event.type == "run.observed":
            fingerprint = str(event.payload["fingerprint"])
            repeated_observations = repeated_observations + 1 if fingerprint == previous_observation else 0
            previous_observation = fingerprint
        elif event.type == "run.completed":
            status = "completed"
            answer = str(event.payload.get("answer", ""))
        elif event.type == "run.unverified":
            status = "unverified"
            answer = str(event.payload.get("answer", ""))
            error = str(event.payload.get("reason", "not verified"))
        elif event.type == "run.failed":
            status = "failed"
            error = str(event.payload.get("error", "unknown error"))
        elif event.type == "run.cancelled":
            status = "cancelled"
            error = str(event.payload.get("reason", "cancelled"))
        elif event.type == "run.budget_exhausted":
            status = "budget_exhausted"
            error = str(event.payload.get("reason", "budget exhausted"))
    return RunState(run_id=run_id, revision=revision, status=status,
                    model_calls=model_calls, tool_calls=tool_calls,
                    max_turns=state.max_turns, max_tool_calls=state.max_tool_calls,
                    max_repeated_observations=state.max_repeated_observations,
                    deadline_at=state.deadline_at, repeated_observations=repeated_observations,
                    answer=answer, error=error)
