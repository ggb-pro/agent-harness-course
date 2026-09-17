import unittest

from sonic_agent import (
    AgentRunner,
    AssistantResponse,
    ExactTextCompletion,
    FakeProvider,
    InMemoryEventStore,
    ToolCall,
    ToolRegistry,
    ToolRuntime,
    ToolError,
    project_run,
)


def make_runner(responses, max_turns=8, completion=None):
    store = InMemoryEventStore()
    registry = ToolRegistry()
    registry.register("double", lambda args: args["value"] * 2)
    provider = FakeProvider(responses)
    runner = AgentRunner(provider, ToolRuntime(registry, store), store, max_turns=max_turns,
                         completion=completion)
    return runner, provider, store


class RunnerProjectionTests(unittest.TestCase):
    def test_final_response_completes_and_projects(self):
        runner, _, store = make_runner([AssistantResponse("done")],
                                       completion=ExactTextCompletion("done"))
        result = runner.run("work", run_id="r1")
        projection = project_run(store.load("r1"))
        self.assertEqual((result.status, result.answer), ("completed", "done"))
        self.assertEqual((projection.status, projection.answer, projection.model_turns), ("completed", "done", 1))

    def test_tool_result_is_returned_to_next_model_turn(self):
        responses = [
            AssistantResponse(tool_calls=(ToolCall("c1", "double", {"value": 21}),)),
            AssistantResponse("42"),
        ]
        runner, provider, store = make_runner(responses, completion=ExactTextCompletion("42"))
        result = runner.run("calculate", run_id="r2")
        projection = project_run(store.load("r2"))
        self.assertEqual(result.answer, "42")
        self.assertEqual(provider.calls[1][-2]["tool_calls"], [
            {"id": "c1", "name": "double", "arguments": {"value": 21}},
        ])
        self.assertEqual(provider.calls[1][-1]["content"], 42)
        self.assertEqual(projection.tool_calls, 1)

    def test_structured_tool_failure_is_returned_to_next_model_turn(self):
        store = InMemoryEventStore()
        registry = ToolRegistry()
        registry.register("bounded.read", lambda _: (_ for _ in ()).throw(ToolError(
            "path_scope_denied", "repository path is outside the allowed scope", denied=True
        )))
        provider = FakeProvider([
            AssistantResponse(tool_calls=(ToolCall("c1", "bounded.read", {}),)),
            AssistantResponse("stopped"),
        ])
        runner = AgentRunner(
            provider,
            ToolRuntime(registry, store),
            store,
            completion=ExactTextCompletion("stopped"),
        )
        self.assertEqual(runner.run("read", run_id="structured-error").status, "completed")
        self.assertEqual(provider.calls[1][-1]["content"], {
            "error": "repository path is outside the allowed scope",
            "error_code": "path_scope_denied",
            "retryable": False,
            "denied": True,
        })

    def test_provider_failure_becomes_failed_run_event(self):
        runner, _, store = make_runner([])
        result = runner.run("work", run_id="r3")
        projection = project_run(store.load("r3"))
        self.assertEqual(result.status, "failed")
        self.assertEqual(projection.status, "failed")
        self.assertIn("exhausted", projection.errors[0])

    def test_turn_limit_has_explicit_budget_exhaustion(self):
        looping = AssistantResponse(tool_calls=(ToolCall("same", "double", {"value": 2}),))
        runner, _, store = make_runner([looping], max_turns=1)
        result = runner.run("loop", run_id="r4")
        self.assertEqual(result.status, "budget_exhausted")
        self.assertIn("maximum model turns", result.error)
        self.assertEqual(store.load("r4")[-1].type, "run.budget_exhausted")


if __name__ == "__main__":
    unittest.main()
