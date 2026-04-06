from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelAlias:
    """Maps a logical model name to a concrete provider:model string."""

    provider: str
    model: str
    fallback_provider: str | None = None
    fallback_model: str | None = None


# ---------------------------------------------------------------------------
# Built-in alias registry
# ---------------------------------------------------------------------------

_BUILTIN_ALIASES: dict[str, ModelAlias] = {
    "coding-default": ModelAlias(
        provider="openai",
        model="gpt-4.1",
        fallback_provider="anthropic",
        fallback_model="claude-sonnet-4-20250514",
    ),
    "coding-fast": ModelAlias(
        provider="openai",
        model="gpt-4.1-mini",
    ),
    "coding-cheap": ModelAlias(
        provider="openai",
        model="gpt-4o-mini",
    ),
    "verifier-default": ModelAlias(
        provider="openai",
        model="gpt-4.1-mini",
    ),
    "embedding-default": ModelAlias(
        provider="openai",
        model="text-embedding-3-small",
    ),
    "rerank-default": ModelAlias(
        provider="openai",
        model="text-embedding-3-small",
    ),
}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


@dataclass
class ModelRouter:
    """Resolve logical model aliases to concrete provider:model pairs."""

    aliases: dict[str, ModelAlias] = field(default_factory=dict)
    env_overrides: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        merged: dict[str, ModelAlias] = dict(_BUILTIN_ALIASES)
        merged.update(self.aliases)
        self.aliases = merged

    def resolve(self, alias_or_model: str) -> tuple[str, str]:
        """Return (provider, model) for the given alias or literal model string.

        If alias_or_model is a known alias, return the alias target.
        If it contains a '/' (e.g. 'anthropic/claude-sonnet-4'), split it.
        Otherwise treat it as a model name and use the default provider.
        """
        # Check env override first
        env_key = f"TASKPLANE_MODEL_OVERRIDE_{alias_or_model.upper().replace('-', '_')}"
        env_val = self.env_overrides.get(env_key) or os.environ.get(env_key, "").strip()
        if env_val:
            return self._parse_provider_model(env_val)

        alias = self.aliases.get(alias_or_model)
        if alias is not None:
            return alias.provider, alias.model

        return self._parse_provider_model(alias_or_model)

    def resolve_with_fallback(self, alias_or_model: str) -> list[tuple[str, str]]:
        """Return ordered list of (provider, model) candidates."""
        alias = self.aliases.get(alias_or_model)
        if alias is None:
            return [self._parse_provider_model(alias_or_model)]

        candidates: list[tuple[str, str]] = [(alias.provider, alias.model)]
        if alias.fallback_provider and alias.fallback_model:
            candidates.append((alias.fallback_provider, alias.fallback_model))
        return candidates

    @staticmethod
    def _parse_provider_model(value: str) -> tuple[str, str]:
        """Parse 'provider/model' or return (default_provider, value)."""
        if "/" in value:
            parts = value.split("/", 1)
            return parts[0].strip(), parts[1].strip()
        return "openai", value
