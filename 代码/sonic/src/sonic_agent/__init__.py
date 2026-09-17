"""sonic 的可审计 Harness 教学内核。"""

from .core.context import ContextBuilder, ContextItem
from .core.completion import CompletionContract, CompletionDecision, ExactTextCompletion
from .core.events import Event, InMemoryEventStore, JsonlEventStore, RevisionConflict, SqliteEventStore
from .models.model import (
    AssistantResponse,
    FakeProvider,
    ModelAccess,
    ModelResponseMetadata,
    ProviderError,
    ProviderInfo,
    TokenUsage,
    ToolCall,
)
from .models.openai_responses import OpenAIResponsesProvider
from .core.projections import RunProjection, project_run
from .core.runner import AgentRunner, RunResult
from .core.state import RunState, project_state
from .capabilities.tools import (
    DenyPathPolicy,
    EffectJournal,
    ToolError,
    ToolOutput,
    ToolRegistry,
    ToolResult,
    ToolRuntime,
    ToolSpec,
)
from .capabilities.repository import ReadOnlyRepositoryTools, WorkspaceLimits, WorkspaceScope

__all__ = [
    "AgentRunner",
    "AssistantResponse",
    "ContextBuilder",
    "ContextItem",
    "CompletionDecision",
    "CompletionContract",
    "DenyPathPolicy",
    "EffectJournal",
    "Event",
    "ExactTextCompletion",
    "FakeProvider",
    "InMemoryEventStore",
    "JsonlEventStore",
    "ModelAccess",
    "ModelResponseMetadata",
    "OpenAIResponsesProvider",
    "ProviderError",
    "ProviderInfo",
    "RevisionConflict",
    "ReadOnlyRepositoryTools",
    "RunState",
    "SqliteEventStore",
    "RunProjection",
    "RunResult",
    "ToolCall",
    "ToolError",
    "ToolOutput",
    "ToolRegistry",
    "ToolResult",
    "ToolRuntime",
    "ToolSpec",
    "TokenUsage",
    "WorkspaceLimits",
    "WorkspaceScope",
    "project_run",
    "project_state",
]

