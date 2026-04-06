from __future__ import annotations

from typing import Any, Protocol

from .types import ModelTurn


class ToolModelClient(Protocol):
    def complete_with_tools(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_seconds: int,
        max_output_tokens: int,
    ) -> ModelTurn: ...

    def complete_text(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        timeout_seconds: int,
        max_output_tokens: int,
    ) -> str: ...
