from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class UsageSnapshot:
    """Immutable snapshot of token usage for a single model invocation."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    estimated_cost_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


def merge_usage(*snapshots: UsageSnapshot) -> UsageSnapshot:
    """Combine multiple usage snapshots into one aggregate snapshot."""
    if not snapshots:
        return UsageSnapshot()
    return UsageSnapshot(
        input_tokens=sum(s.input_tokens for s in snapshots),
        output_tokens=sum(s.output_tokens for s in snapshots),
        total_tokens=sum(s.total_tokens for s in snapshots),
        cache_read_tokens=sum(s.cache_read_tokens for s in snapshots),
        cache_write_tokens=sum(s.cache_write_tokens for s in snapshots),
        reasoning_tokens=sum(s.reasoning_tokens for s in snapshots),
        estimated_cost_usd=sum(s.estimated_cost_usd for s in snapshots),
        metadata={k: v for s in snapshots for k, v in s.metadata.items()},
    )


# ---------------------------------------------------------------------------
# Minimal cost estimation (approximate, model-agnostic)
# ---------------------------------------------------------------------------

# Default per-1M-token rates (USD) — rough OpenAI baseline.
# Real implementations should override with provider-specific pricing.
_DEFAULT_INPUT_RATE_PER_M = 2.50
_DEFAULT_OUTPUT_RATE_PER_M = 10.00


def estimate_cost(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    input_rate_per_m: float = _DEFAULT_INPUT_RATE_PER_M,
    output_rate_per_m: float = _DEFAULT_OUTPUT_RATE_PER_M,
) -> float:
    """Estimate cost in USD given token counts and per-million-token rates."""
    return (input_tokens / 1_000_000) * input_rate_per_m + (
        output_tokens / 1_000_000
    ) * output_rate_per_m


# ---------------------------------------------------------------------------
# Usage ledger — simple in-memory accumulator
# ---------------------------------------------------------------------------


@dataclass
class UsageLedger:
    """In-memory usage accumulator for a single caller/session."""

    entries: list[UsageSnapshot] = field(default_factory=list)

    def add(self, snapshot: UsageSnapshot) -> None:
        self.entries.append(snapshot)

    def total(self) -> UsageSnapshot:
        return merge_usage(*self.entries)

    def clear(self) -> None:
        self.entries.clear()
