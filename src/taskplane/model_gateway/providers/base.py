from __future__ import annotations

import json
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from ..errors import LLMRequestError


def classify_http_error(status_code: int) -> tuple[str, bool]:
    if status_code in {401, 403}:
        return "credential_required", False
    if status_code in {408, 429, 500, 502, 503, 504}:
        return "upstream_api_error", True
    return "upstream_api_error", False


def json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def trim_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...[truncated]"


def http_post_json(
    *,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: int,
) -> dict[str, Any]:
    request = urllib_request.Request(
        url,
        data=json_dump(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **headers,
        },
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        reason_code, retryable = classify_http_error(exc.code)
        raise LLMRequestError(
            trim_text(f"LLM API HTTP {exc.code}: {raw}", 900),
            status_code=exc.code,
            reason_code=reason_code,
            retryable=retryable,
        ) from exc
    except urllib_error.URLError as exc:
        raise LLMRequestError(
            f"LLM API network error: {exc}",
            reason_code="resource_temporarily_unavailable",
            retryable=True,
        ) from exc
    except TimeoutError as exc:
        raise LLMRequestError(
            f"LLM API timeout: {exc}",
            reason_code="timeout",
            retryable=True,
        ) from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise LLMRequestError(
            f"LLM API returned invalid JSON: {trim_text(body, 400)}",
            reason_code="invalid-result-payload",
            retryable=False,
        ) from exc
    if not isinstance(data, dict):
        raise LLMRequestError(
            "LLM API returned non-object response",
            reason_code="invalid-result-payload",
            retryable=False,
        )
    return data


def coerce_json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    text = raw.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}
