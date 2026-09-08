"""Append-only event stores used by the harness."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class Event:
    run_id: str
    sequence: int
    type: str
    timestamp: str
    payload: dict[str, Any]


class EventStore(Protocol):
    def append(self, run_id: str, event_type: str, payload: dict[str, Any]) -> Event: ...
    def load(self, run_id: str | None = None) -> list[Event]: ...


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryEventStore:
    def __init__(self, clock: Callable[[], str] = utc_now) -> None:
        self._events: list[Event] = []
        self._clock = clock

    def append(self, run_id: str, event_type: str, payload: dict[str, Any]) -> Event:
        json.dumps(payload, ensure_ascii=False)
        sequence = sum(event.run_id == run_id for event in self._events) + 1
        event = Event(run_id, sequence, event_type, self._clock(), dict(payload))
        self._events.append(event)
        return event

    def load(self, run_id: str | None = None) -> list[Event]:
        return [event for event in self._events if run_id is None or event.run_id == run_id]


class JsonlEventStore:
    def __init__(self, path: str | Path, clock: Callable[[], str] = utc_now) -> None:
        self.path = Path(path)
        self._clock = clock

    def append(self, run_id: str, event_type: str, payload: dict[str, Any]) -> Event:
        json.dumps(payload, ensure_ascii=False)
        sequence = len(self.load(run_id)) + 1
        event = Event(run_id, sequence, event_type, self._clock(), dict(payload))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(asdict(event), ensure_ascii=False, sort_keys=True) + "\n")
        return event

    def load(self, run_id: str | None = None) -> list[Event]:
        if not self.path.exists():
            return []
        events: list[Event] = []
        with self.path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                raw = json.loads(line)
                event = Event(**raw)
                if run_id is None or event.run_id == run_id:
                    events.append(event)
        return events

