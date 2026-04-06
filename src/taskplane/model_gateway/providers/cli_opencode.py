from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..settings import OpenCodeSettings

from ...execution_protocol import EXECUTION_RESULT_MARKER


def build_opencode_run_command(
    *, focus_dir: Path, prompt: str, settings: OpenCodeSettings | None = None
) -> list[str]:
    command = [
        "opencode",
        "run",
        "--format",
        "json",
        "--dir",
        str(focus_dir),
    ]
    model = ""
    variant = ""
    if settings is not None:
        model = settings.model
        variant = settings.variant
    else:
        model = os.environ.get("TASKPLANE_OPENCODE_MODEL", "").strip()
        variant = os.environ.get("TASKPLANE_OPENCODE_VARIANT", "").strip()
    if model:
        command.extend(["--model", model])
    if variant:
        command.extend(["--variant", variant])
    command.append(prompt)
    return command


def extract_result_payload(
    raw_stream: str, *, extraction_cls: Callable[..., Any]
) -> dict | None:
    return extract_result_payload_details(
        raw_stream, extraction_cls=extraction_cls
    ).payload


def extract_result_payload_details(
    raw_stream: str, *, extraction_cls: Callable[..., Any]
) -> Any:
    candidates: list[tuple[str, bool]] = []
    observed_event_types: list[str] = []
    for line in raw_stream.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(EXECUTION_RESULT_MARKER):
            candidates.append((stripped[len(EXECUTION_RESULT_MARKER) :].strip(), True))
            continue
        if not stripped.startswith("{") or not stripped.endswith("}"):
            continue
        candidates.append((stripped, False))
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            event_type = str(event.get("type") or "").strip()
            if event_type and event_type not in observed_event_types:
                observed_event_types.append(event_type)
        text_candidate = extract_json_from_text_event(event)
        if text_candidate:
            candidates.append((text_candidate, False))

    terminal_payloads: list[dict] = []
    marker_terminal_payloads: list[dict] = []
    distinct_terminal_payloads: set[str] = set()
    payload: dict | None = None
    marker_payload: dict | None = None
    for candidate, from_marker in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "outcome" in parsed:
            terminal_payloads.append(parsed)
            distinct_terminal_payloads.add(
                json.dumps(parsed, sort_keys=True, ensure_ascii=False)
            )
            payload = parsed
            if from_marker:
                marker_terminal_payloads.append(parsed)
                marker_payload = parsed
    if marker_payload is not None:
        payload = marker_payload

    return extraction_cls(
        payload=payload,
        terminal_payload_count=len(terminal_payloads),
        distinct_terminal_payload_count=len(distinct_terminal_payloads),
        marker_terminal_payload_count=len(marker_terminal_payloads),
        observed_event_types=tuple(observed_event_types),
    )


def classify_multiple_terminal_payload(details: Any) -> dict | None:
    if details.distinct_terminal_payload_count <= 1:
        return None
    return {
        "outcome": "blocked",
        "reason_code": "multiple-terminal-payloads",
        "summary": "opencode emitted conflicting terminal payloads in a single run",
        "decision_required": False,
        "terminal_payload_count": details.terminal_payload_count,
        "distinct_terminal_payload_count": details.distinct_terminal_payload_count,
        "marker_terminal_payload_count": details.marker_terminal_payload_count,
        "observed_event_types": list(details.observed_event_types),
    }


def classify_malformed_stream_payload(raw_stream: str) -> dict | None:
    lowered = raw_stream.lower()
    markers = (
        "json parsing failed",
        "json parse error",
        "json decode error",
        "failed to parse json",
        "unexpected end of json input",
        "unexpected end-of-input",
        "unterminated string",
        "expecting value",
        "expecting ',' delimiter",
        "extra data",
        "unexpected non-whitespace character after json",
        "unexpected identifier",
        "expected '}'",
        "expected '}\"",
    )
    if not any(marker in lowered for marker in markers):
        return None
    return {
        "outcome": "blocked",
        "reason_code": "interrupted_retryable",
        "summary": "opencode emitted malformed JSON event/output; treating as retryable stream corruption",
        "decision_required": False,
    }


def classify_missing_terminal_payload(raw_stream: str) -> dict | None:
    saw_event_stream = False
    for line in raw_stream.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        event_type = str(parsed.get("type") or "").strip().lower()
        if not event_type:
            continue
        if event_type in {
            "text",
            "error",
            "step_start",
            "step_finish",
            "tool_use",
            "tool_result",
            "assistant",
            "message_start",
            "message_stop",
            "content_block_start",
            "content_block_stop",
            "content_block_delta",
        }:
            saw_event_stream = True
            continue
        if event_type.startswith("step_") or event_type.startswith("tool_"):
            saw_event_stream = True
    if not saw_event_stream:
        return None
    return {
        "outcome": "blocked",
        "reason_code": "missing-terminal-payload",
        "summary": "opencode emitted event stream but did not emit a terminal structured result payload",
        "decision_required": False,
    }


def classify_upstream_api_error_payload(raw_stream: str) -> dict | None:
    upstream_markers = (
        "apierror",
        "insufficient quota",
        "insufficient_quota",
        "quota exceeded",
        "credit balance",
        "payment required",
        "rate limit",
        "too many requests",
        "api key",
        "authentication",
        "auth failed",
        "套餐已经到期",
        "额度用完",
        "充值",
    )
    for line in raw_stream.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        if str(parsed.get("type") or "").strip().lower() != "error":
            continue
        error = parsed.get("error")
        if not isinstance(error, dict):
            continue
        fragments: list[str] = []
        name = str(error.get("name") or "").strip()
        if name:
            fragments.append(name)
        top_level_message = error.get("message")
        if isinstance(top_level_message, str) and top_level_message.strip():
            fragments.append(top_level_message.strip())
        data = error.get("data")
        if isinstance(data, dict):
            data_message = data.get("message")
            if isinstance(data_message, str) and data_message.strip():
                fragments.append(data_message.strip())
        elif isinstance(data, str) and data.strip():
            fragments.append(data.strip())
        combined = " ".join(fragments).lower()
        if not combined:
            continue
        if any(marker in combined for marker in upstream_markers):
            return {
                "outcome": "blocked",
                "reason_code": "upstream_api_error",
                "summary": "opencode failed due to upstream API error before producing a terminal payload",
                "decision_required": False,
            }
    return None


def extract_wait_hint(raw_stream: str) -> dict | None:
    for line in raw_stream.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        text_candidate = extract_json_from_text_event(event)
        if not text_candidate:
            continue
        try:
            inner = json.loads(text_candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(inner, dict):
            continue
        if inner.get("execution_kind") == "wait" and inner.get("resume_hint"):
            return inner
    return None


def extract_json_from_text_event(event: Any) -> str | None:
    if not isinstance(event, dict) or event.get("type") != "text":
        return None
    part = event.get("part")
    if not isinstance(part, dict):
        return None
    text = part.get("text")
    if not isinstance(text, str):
        return None
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    match = re.search(r"(\{.*\})", text, re.S)
    if match is None:
        return None
    candidate = match.group(1).strip()
    if candidate.startswith("{") and candidate.endswith("}"):
        return candidate
    return None


def build_salvaged_done_payload(*, changed_paths: list[str]) -> dict[str, Any] | None:
    if not changed_paths:
        return None
    return {
        "outcome": "done",
        "reason_code": "missing-terminal-payload-with-repo-change",
        "summary": (
            "opencode changed repository content but did not emit a terminal JSON payload; "
            "treating the attempt as done and deferring acceptance to verifier and commit safety checks."
        ),
        "decision_required": False,
    }
