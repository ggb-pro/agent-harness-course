import unittest

from traceforge_harness import (
    AgentRunner,
    AssistantResponse,
    FakeProvider,
    InMemoryEventStore,
    ToolCall,
    ToolRegistry,
    ToolRuntime,
    project_run,
)


def make_runner(responses, max_turns=8):
    store = InMemoryEventStore()
    registry = ToolRegistry()
    registry.register("double", lambda args: args["value"] * 2)
    provider = FakeProvider(responses)
    runner = AgentRunner(provider, ToolRuntime(registry, store), store, max_turns=max_turns)
    return runner, provider, store


class RunnerProjectionTests(unittest.TestCase):
    def test_final_response_completes_and_projects(self):
        runner, _, store = make_runner([AssistantResponse("done")])
        result = runner.run("work", run_id="r1")
        projection = project_run(store.load("r1"))
        self.assertEqual((result.status, result.answer), ("completed", "done"))
        self.assertEqual((projection.status, projection.answer, projection.model_turns), ("completed", "done", 1))

    def test_tool_result_is_returned_to_next_model_turn(self):
        responses = [
            AssistantResponse(tool_calls=(ToolCall("c1", "double", {"value": 21}),)),
            AssistantResponse("42"),
        ]
        runner, provider, store = make_runner(responses)
        result = runner.run("calculate", run_id="r2")
        projection = project_run(store.load("r2"))
        self.assertEqual(result.answer, "42")
        self.assertEqual(provider.calls[1][-1]["content"], 42)
        self.assertEqual(projection.tool_calls, 1)

    def test_provider_failure_becomes_failed_run_event(self):
        runner, _, store = make_runner([])
        result = runner.run("work", run_id="r3")
        projection = project_run(store.load("r3"))
        self.assertEqual(result.status, "failed")
        self.assertEqual(projection.status, "failed")
        self.assertIn("exhausted", projection.errors[0])

    def test_turn_limit_has_explicit_failure(self):
        looping = AssistantResponse(tool_calls=(ToolCall("same", "double", {"value": 2}),))
        runner, _, store = make_runner([looping], max_turns=1)
        result = runner.run("loop", run_id="r4")
        self.assertEqual(result.status, "failed")
        self.assertIn("maximum model turns", result.error)
        self.assertEqual(store.load("r4")[-1].type, "run.failed")


if __name__ == "__main__":
    unittest.main()
