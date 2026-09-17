import unittest

from sonic_agent import (
    DenyPathPolicy,
    EffectJournal,
    InMemoryEventStore,
    ToolCall,
    ToolError,
    ToolOutput,
    ToolRegistry,
    ToolRuntime,
    ToolSpec,
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
        with self.assertRaises(ToolError) as caught:
            registry.execute("missing", {})
        self.assertEqual(caught.exception.code, "unknown_tool")

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

    def test_registry_exposes_sorted_manifest(self):
        registry = ToolRegistry()
        registry.register("z.read", lambda args: args, spec=ToolSpec("z.read", read_only=True))
        registry.register("a.write", lambda args: args)
        self.assertEqual(registry.names, ("a.write", "z.read"))
        self.assertEqual([spec.name for spec in registry.manifest()], ["a.write", "z.read"])
        self.assertTrue(registry.spec("z.read").read_only)

    def test_runtime_does_not_cache_read_only_tools_and_persists_receipt_only(self):
        values = []
        store = InMemoryEventStore()
        registry = ToolRegistry()

        def read(_):
            values.append(len(values) + 1)
            return ToolOutput({"secret_content": values[-1]}, {"sha256": "safe"})

        registry.register("repo.read", read, spec=ToolSpec("repo.read", read_only=True))
        runtime = ToolRuntime(registry, store)
        first = runtime.run("run", ToolCall("same", "repo.read", {}))
        second = runtime.run("run", ToolCall("same", "repo.read", {}))
        self.assertEqual((first.value, second.value), ({"secret_content": 1}, {"secret_content": 2}))
        self.assertFalse(first.cached)
        completed = [event.payload for event in store.load("run") if event.type == "tool.completed"]
        self.assertEqual([event["receipt"] for event in completed], [{"sha256": "safe"}] * 2)
        self.assertNotIn("secret_content", repr(completed))

    def test_runtime_redacts_unknown_tool_name_and_unexpected_error(self):
        store = InMemoryEventStore()
        registry = ToolRegistry()
        registry.register("fail", lambda _: (_ for _ in ()).throw(RuntimeError("C:/secret/token")))
        runtime = ToolRuntime(registry, store)

        failed = runtime.run("run", ToolCall("1", "fail", {}))
        missing = runtime.run("run", ToolCall("2", "evil.secret-name", {"token": "secret"}))

        self.assertEqual((failed.error_code, failed.error), (
            "internal_error", "tool execution failed unexpectedly"
        ))
        self.assertEqual(missing.error_code, "unknown_tool")
        serialized = repr([event.payload for event in store.load("run")])
        self.assertNotIn("C:/secret/token", serialized)
        self.assertNotIn("evil.secret-name", serialized)
        self.assertNotIn("secret'", serialized)


if __name__ == "__main__":
    unittest.main()
