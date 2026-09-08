import json
from pathlib import Path
import tempfile
import unittest

from traceforge_harness import InMemoryEventStore, JsonlEventStore


FIXED_TIME = lambda: "2026-09-08T00:00:00+00:00"


class EventStoreTests(unittest.TestCase):
    def test_memory_sequences_are_per_run(self):
        store = InMemoryEventStore(FIXED_TIME)
        self.assertEqual(store.append("a", "one", {}).sequence, 1)
        self.assertEqual(store.append("b", "one", {}).sequence, 1)
        self.assertEqual(store.append("a", "two", {}).sequence, 2)

    def test_memory_load_filters_by_run(self):
        store = InMemoryEventStore(FIXED_TIME)
        store.append("a", "one", {})
        store.append("b", "two", {})
        self.assertEqual([event.type for event in store.load("b")], ["two"])

    def test_payload_must_be_json_serializable(self):
        store = InMemoryEventStore(FIXED_TIME)
        with self.assertRaises(TypeError):
            store.append("a", "bad", {"value": object()})

    def test_jsonl_round_trip_preserves_unicode(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.jsonl"
            store = JsonlEventStore(path, FIXED_TIME)
            store.append("r", "message", {"text": "你好"})
            event = store.load("r")[0]
            self.assertEqual(event.payload["text"], "你好")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["type"], "message")

    def test_jsonl_restart_continues_sequence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.jsonl"
            JsonlEventStore(path, FIXED_TIME).append("r", "one", {})
            event = JsonlEventStore(path, FIXED_TIME).append("r", "two", {})
            self.assertEqual(event.sequence, 2)


if __name__ == "__main__":
    unittest.main()

