"""Append-only event stores used by the harness."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class Event:
    run_id: str
    sequence: int
    type: str
    timestamp: str
    payload: dict[str, Any]


class EventStore(Protocol):
    def append(self, run_id: str, event_type: str, payload: dict[str, Any], expected_revision: int | None = None) -> Event: ...
    def load(self, run_id: str | None = None) -> list[Event]: ...


class RevisionConflict(RuntimeError):
    """A writer tried to append against an obsolete run revision."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryEventStore:
    def __init__(self, clock: Callable[[], str] = utc_now) -> None:
        self._events: list[Event] = []
        self._clock = clock

    def append(self, run_id: str, event_type: str, payload: dict[str, Any], expected_revision: int | None = None) -> Event:
        json.dumps(payload, ensure_ascii=False)
        current = sum(event.run_id == run_id for event in self._events)
        if expected_revision is not None and current != expected_revision:
            raise RevisionConflict(f"run {run_id}: expected revision {expected_revision}, found {current}")
        sequence = current + 1
        event = Event(run_id, sequence, event_type, self._clock(), dict(payload))
        self._events.append(event)
        return event

    def load(self, run_id: str | None = None) -> list[Event]:
        return [event for event in self._events if run_id is None or event.run_id == run_id]


class JsonlEventStore:
    def __init__(self, path: str | Path, clock: Callable[[], str] = utc_now) -> None:
        self.path = Path(path)
        self._clock = clock

    def append(self, run_id: str, event_type: str, payload: dict[str, Any], expected_revision: int | None = None) -> Event:
        json.dumps(payload, ensure_ascii=False)
        current = len(self.load(run_id))
        if expected_revision is not None and current != expected_revision:
            raise RevisionConflict(f"run {run_id}: expected revision {expected_revision}, found {current}")
        sequence = current + 1
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


class SqliteEventStore:
    """Transactional single-host event store; local commit is not an external Tool transaction."""

    def __init__(self, path: str | Path, clock: Callable[[], str] = utc_now) -> None:
        self.path = Path(path)
        self._clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (run_id, sequence)
            )""")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def append(self, run_id: str, event_type: str, payload: dict[str, Any], expected_revision: int | None = None) -> Event:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM events WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
            if expected_revision is not None and current != expected_revision:
                raise RevisionConflict(f"run {run_id}: expected revision {expected_revision}, found {current}")
            event = Event(run_id, current + 1, event_type, self._clock(), dict(payload))
            db.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?)",
                (event.run_id, event.sequence, event.type, event.timestamp, body),
            )
        return event

    def load(self, run_id: str | None = None) -> list[Event]:
        with closing(self._connect()) as db:
            if run_id is None:
                rows = db.execute(
                    "SELECT run_id, sequence, type, timestamp, payload FROM events ORDER BY run_id, sequence"
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT run_id, sequence, type, timestamp, payload FROM events WHERE run_id = ? ORDER BY sequence",
                    (run_id,),
                ).fetchall()
        return [Event(row[0], row[1], row[2], row[3], json.loads(row[4])) for row in rows]

