from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..normalization import classify_nonzero_exit_payload

DEFAULT_CODEX_MODEL = "gpt-5.4-mini"


def load_codex_model() -> str:
    return (
        os.environ.get("TASKPLANE_CODEX_MODEL")
        or os.environ.get("TASKPLANE_LLM_EXECUTOR_MODEL")
        or DEFAULT_CODEX_MODEL
    ).strip()


def build_codex_exec_command(
    *,
    focus_dir: Path,
    prompt: str,
    output_last_message_path: Path,
) -> list[str]:
    return [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        "danger-full-access",
        "--skip-git-repo-check",
        "--ephemeral",
        "--model",
        load_codex_model(),
        "--output-last-message",
        str(output_last_message_path),
        "-C",
        str(focus_dir),
        prompt,
    ]


def extract_codex_payload(
    *,
    raw_stream: str,
    output_last_message_path: Path,
) -> dict[str, Any] | None:
    payload = extract_json_payload_from_file(output_last_message_path)
    if payload is not None:
        return payload

    for line in raw_stream.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        candidate = extract_json_payload_from_codex_event(event)
        if candidate is not None:
            return candidate
    return None


def extract_json_payload_from_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def extract_json_payload_from_codex_event(event: Any) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    if event.get("type") != "item.completed":
        return None
    item = event.get("item")
    if not isinstance(item, dict):
        return None
    if item.get("type") != "agent_message":
        return None
    text = str(item.get("text") or "").strip()
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def classify_missing_codex_payload(raw_stream: str) -> dict[str, Any]:
    saw_event_stream = False
    for line in raw_stream.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        event_type = str(parsed.get("type") or "").strip().lower()
        if event_type in {
            "thread.started",
            "turn.started",
            "turn.completed",
            "item.completed",
        }:
            saw_event_stream = True
            continue
    summary = (
        "codex emitted event stream but did not emit a terminal structured result payload"
        if saw_event_stream
        else "codex did not emit a valid structured result payload"
    )
    return {
        "outcome": "blocked",
        "reason_code": "missing-terminal-payload",
        "summary": summary,
        "decision_required": False,
    }


def classify_nonzero_codex_payload(
    *, raw_stream: str, returncode: int
) -> dict[str, Any]:
    lowered = raw_stream.lower()
    if "usage limit" in lowered or "get more access now" in lowered:
        return {
            "outcome": "blocked",
            "reason_code": "upstream_api_error",
            "summary": "codex failed due to upstream usage limit before producing a terminal payload",
            "decision_required": False,
        }
    payload = classify_nonzero_exit_payload(returncode=returncode, tool_name="codex")
    payload["summary"] = f"codex exited with code {returncode}"
    return payload
