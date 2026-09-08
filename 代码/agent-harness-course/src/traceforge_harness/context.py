"""Small context-governance example with source and budget tracking."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextItem:
    source: str
    content: str
    priority: int = 0
    required: bool = False
    token_estimate: int | None = None

    @property
    def tokens(self) -> int:
        return self.token_estimate if self.token_estimate is not None else max(1, len(self.content) // 4)


class ContextBuilder:
    def __init__(self, budget: int) -> None:
        if budget <= 0:
            raise ValueError("context budget must be positive")
        self.budget = budget

    def build(self, items: list[ContextItem]) -> list[ContextItem]:
        selected = {index for index, item in enumerate(items) if item.required}
        used = sum(items[index].tokens for index in selected)
        optional = sorted(
            (index for index, item in enumerate(items) if not item.required),
            key=lambda index: (-items[index].priority, index),
        )
        for index in optional:
            if used + items[index].tokens <= self.budget:
                selected.add(index)
                used += items[index].tokens
        return [item for index, item in enumerate(items) if index in selected]

