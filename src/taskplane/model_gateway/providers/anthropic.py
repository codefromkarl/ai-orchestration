from __future__ import annotations

import json
from typing import Any

from ..errors import LLMRequestError
from ..settings import load_model_gateway_settings_from_env
from ..types import ModelTurn, ToolInvocation
from .base import coerce_json_object, http_post_json


def convert_messages_for_anthropic(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    result: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "")
        content = message.get("content")
        if role == "system":
            if isinstance(content, str) and content.strip():
                system_parts.append(content)
            continue
        if role == "tool":
            result.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": str(message.get("tool_call_id") or ""),
                            "content": str(content or ""),
                        }
                    ],
                }
            )
            continue
        if role == "assistant":
            blocks: list[dict[str, Any]] = []
            if isinstance(content, str) and content:
                blocks.append({"type": "text", "text": content})
            for call in message.get("tool_calls") or []:
                function_payload = call.get("function") or {}
                arguments = coerce_json_object(function_payload.get("arguments"))
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(call.get("id") or ""),
                        "name": str(function_payload.get("name") or ""),
                        "input": arguments,
                    }
                )
            if not blocks:
                blocks.append({"type": "text", "text": ""})
            result.append({"role": "assistant", "content": blocks})
            continue

        text_content = str(content or "")
        result.append(
            {
                "role": "user" if role != "assistant" else "assistant",
                "content": [{"type": "text", "text": text_content}],
            }
        )
    return "\n\n".join(system_parts), result


def convert_tools_for_anthropic(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in tools:
        function_payload = tool.get("function") or {}
        converted.append(
            {
                "name": str(function_payload.get("name") or ""),
                "description": str(function_payload.get("description") or ""),
                "input_schema": function_payload.get("parameters")
                or {"type": "object", "properties": {}},
            }
        )
    return converted


class AnthropicModelClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        settings = load_model_gateway_settings_from_env()
        self.base_url = (base_url or settings.anthropic_base_url).rstrip("/")
        self.api_key = (
            api_key if api_key is not None else settings.anthropic_api_key
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
        system_prompt, anthropic_messages = convert_messages_for_anthropic(messages)
        payload = {
            "model": model,
            "system": system_prompt,
            "messages": anthropic_messages,
            "tools": convert_tools_for_anthropic(tools),
            "max_tokens": max_output_tokens,
            "temperature": 0.1,
        }
        data = self._post_json(payload=payload, timeout_seconds=timeout_seconds)
        blocks = data.get("content") or []
        text_parts: list[str] = []
        invocations: list[ToolInvocation] = []
        assistant_tool_calls: list[dict[str, Any]] = []
        for index, block in enumerate(blocks):
            block_type = str(block.get("type") or "")
            if block_type == "text":
                text_parts.append(str(block.get("text") or ""))
                continue
            if block_type != "tool_use":
                continue
            name = str(block.get("name") or "")
            call_id = str(block.get("id") or f"tool_call_{index}")
            arguments = (
                block.get("input") if isinstance(block.get("input"), dict) else {}
            )
            invocations.append(
                ToolInvocation(call_id=call_id, name=name, arguments=arguments)
            )
            assistant_tool_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }
            )
        text = "\n".join(part for part in text_parts if part).strip()
        assistant_message: dict[str, Any] = {"role": "assistant", "content": text}
        if assistant_tool_calls:
            assistant_message["tool_calls"] = assistant_tool_calls
        return ModelTurn(
            text=text,
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
        system_prompt, anthropic_messages = convert_messages_for_anthropic(messages)
        payload = {
            "model": model,
            "system": system_prompt,
            "messages": anthropic_messages,
            "max_tokens": max_output_tokens,
            "temperature": 0,
        }
        data = self._post_json(payload=payload, timeout_seconds=timeout_seconds)
        blocks = data.get("content") or []
        text_parts = [
            str(block.get("text") or "")
            for block in blocks
            if block.get("type") == "text"
        ]
        return "\n".join(part for part in text_parts if part).strip()

    def _post_json(
        self, *, payload: dict[str, Any], timeout_seconds: int
    ) -> dict[str, Any]:
        if not self.api_key:
            raise LLMRequestError(
                "ANTHROPIC_API_KEY is required for LLM executor",
                reason_code="credential_required",
                retryable=False,
            )
        return http_post_json(
            url=f"{self.base_url}/messages",
            payload=payload,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            timeout_seconds=timeout_seconds,
        )
