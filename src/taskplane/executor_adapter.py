from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .execution_protocol import (
    EXECUTION_CHECKPOINT_MARKER,
    EXECUTION_RESULT_MARKER,
    EXECUTION_RETRY_INTENT_MARKER,
    EXECUTION_WAIT_MARKER,
    classify_execution_payload,
)
from .session_runtime_loop import ExecutorResult


ALL_MARKERS = (
    EXECUTION_RESULT_MARKER,
    EXECUTION_CHECKPOINT_MARKER,
    EXECUTION_WAIT_MARKER,
    EXECUTION_RETRY_INTENT_MARKER,
)

TIMEOUT_EXIT_CODE = 124


def _parse_markers(raw: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for line in raw.splitlines():
        for marker in ALL_MARKERS:
            if line.startswith(marker):
                try:
                    payload = json.loads(line[len(marker) :])
                    if isinstance(payload, dict):
                        results.append(payload)
                except json.JSONDecodeError:
                    pass
                break
    return results


def _extract_json_from_text_events(raw: str) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for line in raw.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "text":
            continue
        part = event.get("part")
        if not isinstance(part, dict):
            continue
        text = str(part.get("text") or "").strip()
        if not text or not text.startswith("{"):
            continue
        try:
            candidate = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and (
            "outcome" in candidate or "execution_kind" in candidate
        ):
            best = candidate
    return best


def parse_executor_output(
    stdout: str,
    stderr: str,
    returncode: int,
) -> ExecutorResult:
    combined = f"{stdout}\n{stderr}"
    marker_payloads = _parse_markers(combined)
    if marker_payloads:
        payload = marker_payloads[-1]
        kind = classify_execution_payload(payload)
        return ExecutorResult(
            success=kind in {"terminal", "checkpoint", "wait", "retry_intent"},
            payload=payload,
            exit_code=returncode,
        )
    text_payload = _extract_json_from_text_events(combined)
    if text_payload is not None:
        kind = classify_execution_payload(text_payload)
        return ExecutorResult(
            success=kind in {"terminal", "checkpoint", "wait", "retry_intent"},
            payload=text_payload,
            exit_code=returncode,
        )
    if returncode == TIMEOUT_EXIT_CODE:
        return ExecutorResult(
            success=False,
            payload={
                "outcome": "blocked",
                "reason_code": "timeout",
                "summary": f"executor timed out (exit {returncode})",
            },
            exit_code=returncode,
        )
    if returncode != 0:
        return ExecutorResult(
            success=False,
            payload={
                "outcome": "blocked",
                "reason_code": "opencode-exit-nonzero",
                "summary": f"opencode exited with code {returncode}",
            },
            exit_code=returncode,
        )
    return ExecutorResult(
        success=False,
        payload={},
        exit_code=returncode,
    )


def run_opencode_executor(
    *,
    command: list[str],
    project_dir: Path,
    timeout_seconds: int = 1200,
    env: dict[str, str] | None = None,
) -> ExecutorResult:
    try:
        completed = subprocess.run(
            command,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
            env=env,
        )
        return parse_executor_output(
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            returncode=completed.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        return ExecutorResult(
            success=False,
            payload={
                "outcome": "blocked",
                "reason_code": "timeout",
                "summary": f"executor exceeded {timeout_seconds}s timeout",
            },
            exit_code=TIMEOUT_EXIT_CODE,
        )
    except Exception as exc:
        return ExecutorResult(
            success=False,
            payload={
                "outcome": "blocked",
                "reason_code": "executor-error",
                "summary": f"executor launch failed: {exc}",
            },
            exit_code=-1,
        )
