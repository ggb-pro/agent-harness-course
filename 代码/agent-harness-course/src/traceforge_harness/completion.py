"""A task-specific completion contract, separate from model text."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .events import Event


@dataclass(frozen=True)
class CompletionDecision:
    status: str
    reason: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"completed", "failed", "unverified"}:
            raise ValueError("completion status must be completed, failed, or unverified")


class CompletionContract(Protocol):
    def verify(self, prompt: str, answer: str, events: list[Event]) -> CompletionDecision: ...


class ExactTextCompletion:
    """Only for deterministic text tasks; does not validate external side effects."""

    def __init__(self, expected: str) -> None:
        self.expected = expected

    def verify(self, prompt: str, answer: str, events: list[Event]) -> CompletionDecision:
        if answer == self.expected:
            return CompletionDecision("completed")
        return CompletionDecision("failed", f"expected {self.expected!r}, received {answer!r}")
