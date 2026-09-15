from pathlib import Path
import tempfile
import unittest

from traceforge_harness import (
    AgentRunner, AssistantResponse, ExactTextCompletion,
    FakeProvider, InMemoryEventStore, RevisionConflict, SqliteEventStore,
    ToolCall, ToolRegistry, ToolRuntime, project_state,
)


FIXED_TIME = lambda: "2026-09-15T00:00:00+00:00"


def runner_for(store, responses, *, handler=None, **options):
    registry = ToolRegistry()
    registry.register("write", handler or (lambda args: args))
    provider = FakeProvider(responses)
    runner = AgentRunner(provider, ToolRuntime(registry, store), store, **options)
    return runner, provider


class CoreContractTests(unittest.TestCase):
    def test_model_finish_without_contract_is_not_task_success(self):
        store = InMemoryEventStore(FIXED_TIME)
        runner, _ = runner_for(store, [AssistantResponse("fixed")])
        result = runner.run("repair", "no-verifier")
        self.assertEqual(result.status, "unverified")
        self.assertEqual(project_state(store.load("no-verifier")).status, "unverified")
        self.assertFalse(any(event.type == "run.completed" for event in store.load("no-verifier")))

    def test_wrong_answer_is_failed_by_explicit_contract(self):
        store = InMemoryEventStore(FIXED_TIME)
        runner, _ = runner_for(store, [AssistantResponse("wrong")],
                               completion=ExactTextCompletion("expected"))
        result = runner.run("text task", "bad-answer")
        self.assertEqual(result.status, "failed")
        self.assertEqual(store.load("bad-answer")[-2].payload["status"], "failed")

    def test_sqlite_revision_and_budget_survive_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "runs.db"
            first = SqliteEventStore(path, FIXED_TIME)
            runner, _ = runner_for(first, [AssistantResponse(tool_calls=(ToolCall("c1", "write", {"n": 1}),))],
                                   max_turns=1)
            result = runner.run("task", "persistent")
            self.assertEqual(result.status, "budget_exhausted")
            reopened = SqliteEventStore(path, FIXED_TIME)
            state = project_state(reopened.load("persistent"))
            self.assertEqual((state.model_calls, state.tool_calls, state.status),
                             (1, 1, "budget_exhausted"))
            with self.assertRaisesRegex(ValueError, "already exists"):
                runner_for(reopened, [AssistantResponse("retry")])[0].run("task", "persistent")
            with self.assertRaises(RevisionConflict):
                reopened.append("persistent", "late", {}, expected_revision=state.revision - 1)
            self.assertEqual(project_state(first.load("persistent")).revision, state.revision)

    def test_sqlite_cas_rejects_two_writers_on_same_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "runs.db"
            a, b = SqliteEventStore(path, FIXED_TIME), SqliteEventStore(path, FIXED_TIME)
            a.append("r", "run.started", {"limits": {}}, expected_revision=0)
            b.append("r", "model.requested", {}, expected_revision=1)
            with self.assertRaises(RevisionConflict):
                a.append("r", "model.requested", {}, expected_revision=1)
            self.assertEqual([event.sequence for event in b.load("r")], [1, 2])

    def test_tool_budget_blocks_second_side_effect(self):
        calls = []
        store = InMemoryEventStore(FIXED_TIME)
        response = AssistantResponse(tool_calls=(
            ToolCall("c1", "write", {"n": 1}), ToolCall("c2", "write", {"n": 2}),
        ))
        runner, _ = runner_for(store, [response], handler=lambda args: calls.append(args["n"]),
                               max_tool_calls=1)
        result = runner.run("do work", "tool-limit")
        self.assertEqual((result.status, calls), ("budget_exhausted", [1]))
        self.assertEqual(project_state(store.load("tool-limit")).tool_calls, 1)

    def test_cancellation_after_first_tool_stops_following_tool(self):
        cancelled = {"value": False}
        calls = []
        def write(args):
            calls.append(args["n"])
            cancelled["value"] = True
            return "written"
        store = InMemoryEventStore(FIXED_TIME)
        response = AssistantResponse(tool_calls=(
            ToolCall("c1", "write", {"n": 1}), ToolCall("c2", "write", {"n": 2}),
        ))
        runner, _ = runner_for(store, [response], handler=write,
                               cancel_requested=lambda: cancelled["value"])
        result = runner.run("do work", "cancelled")
        self.assertEqual((result.status, calls), ("cancelled", [1]))
        self.assertEqual(store.load("cancelled")[-1].type, "run.cancelled")

    def test_deadline_prevents_model_call(self):
        store = InMemoryEventStore(FIXED_TIME)
        runner, provider = runner_for(store, [AssistantResponse("answer")],
                                      clock=FIXED_TIME, deadline_at=FIXED_TIME())
        result = runner.run("task", "expired")
        self.assertEqual(result.status, "budget_exhausted")
        self.assertEqual(len(provider.calls), 0)

    def test_identical_tool_observations_stop_loop_before_next_model_call(self):
        store = InMemoryEventStore(FIXED_TIME)
        repeated = AssistantResponse(tool_calls=(ToolCall("same", "write", {"n": 1}),))
        runner, provider = runner_for(store, [repeated, repeated, repeated, AssistantResponse("false finish")],
                                      max_turns=8)
        result = runner.run("task", "stalled")
        self.assertEqual(result.status, "failed")
        self.assertIn("without progress", result.error)
        self.assertEqual((len(provider.calls), provider.remaining), (3, 1))
        state = project_state(store.load("stalled"))
        self.assertEqual((state.repeated_observations, state.max_repeated_observations), (2, 2))


if __name__ == "__main__":
    unittest.main()
