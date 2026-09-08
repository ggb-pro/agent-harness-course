"""Run a deterministic tool loop and print its audit projection."""

from dataclasses import asdict
import json

from traceforge_harness import (
    AgentRunner,
    AssistantResponse,
    DenyPathPolicy,
    FakeProvider,
    InMemoryEventStore,
    ToolCall,
    ToolRegistry,
    ToolRuntime,
    project_run,
)


events = InMemoryEventStore()
registry = ToolRegistry()
registry.register("add", lambda args: args["a"] + args["b"])
runtime = ToolRuntime(registry, events, policies=[DenyPathPolicy()])
provider = FakeProvider([
    AssistantResponse(tool_calls=(ToolCall("call-1", "add", {"a": 20, "b": 22}),)),
    AssistantResponse(text="20 + 22 = 42"),
])

result = AgentRunner(provider, runtime, events).run("请计算 20 + 22", run_id="demo-run")
projection = project_run(events.load(result.run_id))

print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
print(json.dumps(asdict(projection), ensure_ascii=False, indent=2))
