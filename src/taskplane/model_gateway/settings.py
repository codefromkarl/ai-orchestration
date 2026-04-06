from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Shared env helpers
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    return (os.environ.get(name) or default).strip()


# ---------------------------------------------------------------------------
# Provider / auth settings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderSettings:
    openai_base_url: str
    openai_api_key: str
    anthropic_base_url: str
    anthropic_api_key: str


def load_provider_settings_from_env() -> ProviderSettings:
    return ProviderSettings(
        openai_base_url=(
            os.environ.get("TASKPLANE_OPENAI_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/"),
        openai_api_key=(
            os.environ.get("TASKPLANE_OPENAI_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        ).strip(),
        anthropic_base_url=(
            os.environ.get("TASKPLANE_ANTHROPIC_BASE_URL")
            or os.environ.get("ANTHROPIC_BASE_URL")
            or "https://api.anthropic.com/v1"
        ).rstrip("/"),
        anthropic_api_key=(
            os.environ.get("TASKPLANE_ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or ""
        ).strip(),
    )


# ---------------------------------------------------------------------------
# Executor model / provider defaults
# ---------------------------------------------------------------------------

DEFAULT_EXECUTOR_MODEL = "gpt-4.1-mini"
DEFAULT_VERIFIER_MODEL = "gpt-4.1-mini"


@dataclass(frozen=True)
class ExecutorModelSettings:
    provider: str = "openai"
    executor_model: str = DEFAULT_EXECUTOR_MODEL
    verifier_model: str = DEFAULT_VERIFIER_MODEL
    max_turns: int = 18
    executor_max_output_tokens: int = 1400
    verifier_max_output_tokens: int = 1200
    timeout_seconds: int = 60
    max_retries: int = 2
    retry_backoff_seconds: float = 1.5
    context_max_chars: int = 16000
    context_window_chars: int = 30000
    keep_recent_messages: int = 8
    tool_loop_hard_limit: int = 4


def load_executor_model_settings_from_env() -> ExecutorModelSettings:
    return ExecutorModelSettings(
        provider=_env_str("TASKPLANE_LLM_PROVIDER", "openai").lower(),
        executor_model=(
            os.environ.get("TASKPLANE_LLM_EXECUTOR_MODEL")
            or os.environ.get("TASKPLANE_LLM_MODEL")
            or DEFAULT_EXECUTOR_MODEL
        ).strip(),
        verifier_model=(
            os.environ.get("TASKPLANE_LLM_VERIFIER_MODEL")
            or os.environ.get("TASKPLANE_LLM_MODEL")
            or DEFAULT_VERIFIER_MODEL
        ).strip(),
        max_turns=_env_int("TASKPLANE_LLM_EXECUTOR_MAX_TURNS", 18),
        executor_max_output_tokens=_env_int(
            "TASKPLANE_LLM_EXECUTOR_MAX_OUTPUT_TOKENS", 1400
        ),
        verifier_max_output_tokens=_env_int(
            "TASKPLANE_LLM_VERIFIER_MAX_OUTPUT_TOKENS", 1200
        ),
        timeout_seconds=_env_int("TASKPLANE_LLM_TIMEOUT_SECONDS", 60),
        max_retries=_env_int("TASKPLANE_LLM_EXECUTOR_MAX_RETRIES", 2),
        retry_backoff_seconds=_env_float(
            "TASKPLANE_LLM_EXECUTOR_RETRY_BACKOFF_SECONDS", 1.5
        ),
        context_max_chars=_env_int("TASKPLANE_LLM_CONTEXT_MAX_CHARS", 16000),
        context_window_chars=_env_int("TASKPLANE_LLM_CONTEXT_WINDOW_CHARS", 30000),
        keep_recent_messages=_env_int("TASKPLANE_LLM_KEEP_RECENT_MESSAGES", 8),
        tool_loop_hard_limit=_env_int("TASKPLANE_LLM_TOOL_LOOP_LIMIT", 4),
    )


# ---------------------------------------------------------------------------
# OpenCode CLI settings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenCodeSettings:
    model: str = ""
    variant: str = ""
    timeout_seconds: int = 1200
    hard_cap_seconds: int | None = None
    bounded_mode: bool = False


def load_opencode_settings_from_env(
    *,
    bounded_mode: bool = False,
) -> OpenCodeSettings:
    timeout = _env_int("TASKPLANE_OPENCODE_TIMEOUT_SECONDS", 0)
    if timeout <= 0:
        timeout = 300 if bounded_mode else 1200

    hard_cap_raw = (os.environ.get("TASKPLANE_OPENCODE_HARD_CAP_SECONDS") or "").strip()
    hard_cap: int | None = None
    if hard_cap_raw:
        try:
            hard_cap = int(hard_cap_raw)
        except ValueError:
            hard_cap = None

    return OpenCodeSettings(
        model=_env_str("TASKPLANE_OPENCODE_MODEL", ""),
        variant=_env_str("TASKPLANE_OPENCODE_VARIANT", ""),
        timeout_seconds=timeout,
        hard_cap_seconds=hard_cap,
        bounded_mode=bounded_mode,
    )


# ---------------------------------------------------------------------------
# Codex CLI settings
# ---------------------------------------------------------------------------

DEFAULT_CODEX_MODEL = "gpt-5.4-mini"


@dataclass(frozen=True)
class CodexSettings:
    model: str = DEFAULT_CODEX_MODEL
    timeout_seconds: int = 1200


def load_codex_settings_from_env() -> CodexSettings:
    raw = (os.environ.get("TASKPLANE_CODEX_TIMEOUT_SECONDS") or "").strip()
    timeout = 1200
    if raw:
        try:
            timeout = int(raw)
        except ValueError:
            timeout = 1200

    return CodexSettings(
        model=(
            os.environ.get("TASKPLANE_CODEX_MODEL")
            or os.environ.get("TASKPLANE_LLM_EXECUTOR_MODEL")
            or DEFAULT_CODEX_MODEL
        ).strip(),
        timeout_seconds=timeout,
    )


# ---------------------------------------------------------------------------
# Back-compat aliases (for existing code that imports the old names)
# ---------------------------------------------------------------------------

ModelGatewaySettings = ProviderSettings
load_model_gateway_settings_from_env = load_provider_settings_from_env
