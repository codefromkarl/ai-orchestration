from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolInvocation:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelTurn:
    text: str
    tool_calls: tuple[ToolInvocation, ...]
    assistant_message: dict[str, Any]


@dataclass(frozen=True)
class UsageSnapshot:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
