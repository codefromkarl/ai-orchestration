from __future__ import annotations

from typing import Any

from ..errors import LLMRequestError
from ..settings import load_model_gateway_settings_from_env
from ..types import ModelTurn, ToolInvocation
from .base import coerce_json_object, http_post_json


class OpenAIModelClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        settings = load_model_gateway_settings_from_env()
        self.base_url = (base_url or settings.openai_base_url).rstrip("/")
        self.api_key = (
            api_key if api_key is not None else settings.openai_api_key
        ).strip()

    def complete_with_tools(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_seconds: int,
        max_output_tokens: int,
    ) -> ModelTurn:
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.1,
            "max_tokens": max_output_tokens,
        }
        data = self._post_json(
            "/chat/completions",
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = str(message.get("content") or "")
        tool_calls_raw = message.get("tool_calls") or []
        invocations: list[ToolInvocation] = []
        for index, call in enumerate(tool_calls_raw):
            function_payload = call.get("function") or {}
            name = str(function_payload.get("name") or "")
            call_id = str(call.get("id") or f"tool_call_{index}")
            arguments = coerce_json_object(function_payload.get("arguments"))
            invocations.append(
                ToolInvocation(call_id=call_id, name=name, arguments=arguments)
            )
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": content,
        }
        if tool_calls_raw:
            assistant_message["tool_calls"] = tool_calls_raw
        return ModelTurn(
            text=content,
            tool_calls=tuple(invocations),
            assistant_message=assistant_message,
        )

    def complete_text(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        timeout_seconds: int,
        max_output_tokens: int,
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_output_tokens,
        }
        data = self._post_json(
            "/chat/completions",
            payload=payload,
            timeout_seconds=timeout_seconds,
        )
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return str(message.get("content") or "").strip()

    def _post_json(
        self,
        path: str,
        *,
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise LLMRequestError(
                "OPENAI_API_KEY is required for LLM executor",
                reason_code="credential_required",
                retryable=False,
            )
        return http_post_json(
            url=f"{self.base_url}{path}",
            payload=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout_seconds=timeout_seconds,
        )
