from __future__ import annotations

from .protocol import ToolModelClient
from .providers.anthropic import AnthropicModelClient
from .providers.openai import OpenAIModelClient
from .router import ModelRouter


def build_model_client(
    provider: str,
    *,
    router: ModelRouter | None = None,
) -> ToolModelClient:
    normalized = provider.strip().lower()
    if normalized == "anthropic":
        return AnthropicModelClient()
    return OpenAIModelClient()


def build_model_client_with_routing(
    *,
    alias: str,
    router: ModelRouter | None = None,
) -> tuple[ToolModelClient, list[tuple[str, str]]]:
    """Build a client and return (client, fallback_candidates)."""
    effective_router = router or ModelRouter()
    candidates = effective_router.resolve_with_fallback(alias)
    provider, model = candidates[0]
    return build_model_client(provider), candidates
