import unittest

from traceforge_harness import (
    DenyPathPolicy,
    EffectJournal,
    InMemoryEventStore,
    ToolCall,
    ToolRegistry,
    ToolRuntime,
)


class ToolTests(unittest.TestCase):
    def test_registry_executes_registered_tool(self):
        registry = ToolRegistry()
        registry.register("add", lambda args: args["a"] + args["b"])
        self.assertEqual(registry.execute("add", {"a": 2, "b": 3}), 5)

    def test_registry_rejects_duplicate_and_unknown_tools(self):
        registry = ToolRegistry()
        registry.register("echo", lambda args: args)
        with self.assertRaises(ValueError):
            registry.register("echo", lambda args: args)
        with self.assertRaises(KeyError):
            registry.execute("missing", {})

    def test_path_policy_denies_sensitive_component(self):
        policy = DenyPathPolicy()
        unix = policy.evaluate(ToolCall("1", "read", {"file_path": "/repo/.env"}))
        windows = policy.evaluate(ToolCall("2", "read", {"path": r"C:\repo\.git\config"}))
        self.assertFalse(unix.allowed)
        self.assertFalse(windows.allowed)

    def test_path_policy_allows_normal_path(self):
        decision = DenyPathPolicy().evaluate(ToolCall("1", "read", {"path": "src/main.py"}))
        self.assertTrue(decision.allowed)

    def test_effect_journal_returns_completed_result_from_cache(self):
        calls = []
        journal = EffectJournal()
        first = journal.execute("e1", {"x": 1}, lambda: calls.append(1) or 42)
        second = journal.execute("e1", {"x": 1}, lambda: calls.append(2) or 99)
        self.assertEqual(first, (42, False))
        self.assertEqual(second, (42, True))
        self.assertEqual(calls, [1])

    def test_effect_journal_allows_retry_after_failure(self):
        journal = EffectJournal()
        with self.assertRaisesRegex(RuntimeError, "boom"):
            journal.execute("e1", {}, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        result, cached = journal.execute("e1", {}, lambda: "recovered")
        self.assertEqual((result, cached), ("recovered", False))
        self.assertEqual(journal.records["e1"].attempts, 2)

    def test_runtime_records_denial_without_executing_tool(self):
        executed = []
        store = InMemoryEventStore()
        registry = ToolRegistry()
        registry.register("read", lambda args: executed.append(args) or "secret")
        runtime = ToolRuntime(registry, store, policies=[DenyPathPolicy()])
        result = runtime.run("run", ToolCall("call", "read", {"path": ".env"}))
        self.assertTrue(result.denied)
        self.assertEqual(executed, [])
        self.assertEqual([event.type for event in store.load("run")], ["tool.requested", "tool.denied"])


if __name__ == "__main__":
    unittest.main()

