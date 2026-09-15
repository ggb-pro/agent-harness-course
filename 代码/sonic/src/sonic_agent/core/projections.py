"""Read models derived entirely from events."""

from __future__ import annotations

from dataclasses import dataclass, field

from .events import Event


@dataclass
class RunProjection:
    run_id: str
    status: str = "unknown"
    model_turns: int = 0
    tool_calls: int = 0
    tool_denials: int = 0
    errors: list[str] = field(default_factory=list)
    answer: str | None = None


def project_run(events: list[Event]) -> RunProjection:
    if not events:
        raise ValueError("cannot project an empty event stream")
    projection = RunProjection(events[0].run_id)
    for event in events:
        if event.type == "run.started":
            projection.status = "running"
        elif event.type == "model.responded":
            projection.model_turns += 1
        elif event.type == "tool.requested":
            projection.tool_calls += 1
        elif event.type == "tool.denied":
            projection.tool_denials += 1
        elif event.type == "tool.failed":
            projection.errors.append(str(event.payload.get("error", "unknown error")))
        elif event.type == "run.completed":
            projection.status = "completed"
            projection.answer = str(event.payload.get("answer", ""))
        elif event.type == "run.failed":
            projection.status = "failed"
            projection.errors.append(str(event.payload.get("error", "unknown error")))
        elif event.type == "run.unverified":
            projection.status = "unverified"
            projection.answer = str(event.payload.get("answer", ""))
            projection.errors.append(str(event.payload.get("reason", "not verified")))
        elif event.type == "run.cancelled":
            projection.status = "cancelled"
            projection.errors.append(str(event.payload.get("reason", "cancelled")))
        elif event.type == "run.budget_exhausted":
            projection.status = "budget_exhausted"
            projection.errors.append(str(event.payload.get("reason", "budget exhausted")))
    return projection
