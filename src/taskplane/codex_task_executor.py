from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

from .contextweaver_indexing import ensure_contextweaver_index_for_checkout
from .execution_protocol import classify_execution_payload
from .opencode_task_executor import (
    ALREADY_SATISFIED_OUTCOME,
    INVALID_RESULT_PAYLOAD_EXIT_CODE,
    NEEDS_DECISION_EXIT_CODE,
    NO_REPO_CHANGE_EXIT_CODE,
    PROGRESS_SIGNAL_KINDS,
    TERMINAL_OUTCOMES,
    TIMEOUT_EXIT_CODE,
    _build_prompt,
    _build_resume_context_from_output,
    _build_timeout_payload,
    _capture_worktree_snapshot,
    _classify_nonzero_exit_payload,
    _compute_changed_paths,
    _emit_execution_result,
    _emit_intermediate_payload,
    _emit_phase,
    _extract_allowed_paths,
    _is_non_terminal_payload,
    _list_dirty_paths,
    _load_hard_cap_seconds,
    _normalize_payload,
    _resolve_git_root,
    _run_monitored_subprocess,
    _summarize_partial_output,
)

DEFAULT_CODEX_MODEL = "gpt-5.4-mini"


def main() -> int:
    work_id = os.environ.get("TASKPLANE_WORK_ID", "").strip()
    dsn = os.environ.get("TASKPLANE_DSN", "").strip()
    project_dir = Path(
        os.environ.get("TASKPLANE_PROJECT_DIR") or Path.cwd()
    ).resolve()
    resume_context = os.environ.get("TASKPLANE_RESUME_CONTEXT", "").strip()
    if not work_id:
        raise SystemExit("TASKPLANE_WORK_ID is required")
    if not dsn:
        raise SystemExit("TASKPLANE_DSN is required")
    return run_controlled_codex_task(
        work_id=work_id,
        dsn=dsn,
        project_dir=project_dir,
        resume_context=resume_context,
    )


def run_controlled_codex_task(
    *,
    work_id: str,
    dsn: str,
    project_dir: Path,
    timeout_seconds: int | None = None,
    resume_context: str = "",
) -> int:
    timeout_seconds = (
        _load_timeout_seconds() if timeout_seconds is None else timeout_seconds
    )
    hard_cap_seconds = _load_hard_cap_seconds(
        timeout_seconds=timeout_seconds,
        bounded_mode=False,
    )
    conn = psycopg.connect(dsn, row_factory=cast(Any, dict_row))
    cur = conn.cursor()
    cur.execute(
        """
        SELECT wi.id, wi.title, wi.lane, wi.wave, wi.complexity, wi.source_issue_number,
               wi.dod_json, gin.body
        FROM work_item wi
        LEFT JOIN github_issue_normalized gin
          ON gin.repo = %s AND gin.issue_number = wi.source_issue_number
        WHERE wi.id = %s
        """,
        ("codefromkarl/stardrifter", work_id),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise SystemExit(f"work item not found: {work_id}")

    _emit_phase(
        "loaded_work_item",
        work_id=work_id,
        source_issue_number=cast(Any, row)["source_issue_number"],
    )
    repo_root = _resolve_git_root(project_dir)
    _emit_phase("resolved_git_root", repo_root=str(repo_root) if repo_root else "")
    if repo_root is None:
        print(
            f"unable to resolve git repository root from {project_dir}",
            file=sys.stderr,
        )
        return NO_REPO_CHANGE_EXIT_CODE

    index_error = ensure_contextweaver_index_for_checkout(
        project_dir,
        explicit_repo="codefromkarl/stardrifter",
    )
    _emit_phase("contextweaver_index", ok=index_error is None, detail=index_error or "")
    if index_error is not None:
        payload = {
            "outcome": "blocked",
            "reason_code": "contextweaver-index-failed",
            "summary": f"contextweaver index failed: {index_error}",
            "decision_required": False,
        }
        _emit_execution_result(payload)
        print(payload["summary"], file=sys.stderr)
        return INVALID_RESULT_PAYLOAD_EXIT_CODE

    before_snapshot = _capture_worktree_snapshot(repo_root)
    preexisting_dirty_paths = _list_dirty_paths(repo_root)
    issue_body = str(cast(dict[str, Any], row).get("body") or "")
    prompt = _build_prompt(
        cast(dict[str, Any], row),
        bounded_mode=False,
        resume_context=resume_context,
    )
    focus_dir = _select_codex_focus_dir(project_dir=project_dir, issue_body=issue_body)

    with tempfile.TemporaryDirectory(prefix="taskplane-codex-exec-") as temp_dir:
        temp_dir_path = Path(temp_dir)
        output_last_message_path = temp_dir_path / "last-message.json"

        _emit_phase(
            "before_codex_run",
            timeout_seconds=timeout_seconds,
            hard_cap_seconds=hard_cap_seconds,
            model=_load_codex_model(),
        )
        completed = _run_monitored_subprocess(
            _build_codex_exec_command(
                focus_dir=focus_dir,
                prompt=prompt,
                output_last_message_path=output_last_message_path,
            ),
            cwd=focus_dir,
            no_progress_timeout_seconds=timeout_seconds,
            hard_cap_seconds=hard_cap_seconds,
        )

        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr)
        if completed.timed_out:
            payload = _build_timeout_payload(
                timeout_seconds=timeout_seconds,
                hard_cap_seconds=hard_cap_seconds,
                timeout_kind=completed.timeout_kind,
                partial_output=_summarize_partial_output(
                    (completed.stdout or "") + (completed.stderr or "")
                ),
            )
            _emit_execution_result(payload)
            print(payload["summary"], file=sys.stderr)
            return TIMEOUT_EXIT_CODE

        _emit_phase("after_codex_run", returncode=completed.returncode)
        raw_stream = (completed.stdout or "") + (completed.stderr or "")
        payload = _extract_codex_payload(
            raw_stream=raw_stream,
            output_last_message_path=output_last_message_path,
        )
        after_snapshot = _capture_worktree_snapshot(repo_root)
        changed_paths = _compute_changed_paths(before_snapshot, after_snapshot)

        if completed.returncode != 0:
            payload = _classify_nonzero_codex_payload(
                raw_stream=raw_stream,
                returncode=completed.returncode,
            )
            _emit_execution_result(payload)
            return completed.returncode

        if payload is None:
            if changed_paths:
                payload = {
                    "outcome": "done",
                    "reason_code": "missing-terminal-payload-with-repo-change",
                    "summary": (
                        "codex changed repository content but did not emit a terminal JSON payload; "
                        "treating the attempt as done and deferring acceptance to verifier and commit safety checks."
                    ),
                    "decision_required": False,
                }
            else:
                payload = _classify_missing_codex_payload(raw_stream)
                _emit_execution_result(payload)
                print(payload["summary"], file=sys.stderr)
                return INVALID_RESULT_PAYLOAD_EXIT_CODE

        execution_kind = classify_execution_payload(payload)
        if execution_kind in PROGRESS_SIGNAL_KINDS:
            _emit_intermediate_payload(payload, kind=execution_kind)
            return 0

        if _is_non_terminal_payload(payload):
            payload = {
                "outcome": "blocked",
                "reason_code": "non_terminal_result_payload",
                "summary": "codex returned a non-terminal payload; it must return done, already_satisfied, needs_decision, or blocked.",
                "decision_required": False,
            }
            _emit_execution_result(payload)
            print(payload["summary"], file=sys.stderr)
            return INVALID_RESULT_PAYLOAD_EXIT_CODE

        payload = _normalize_payload(payload)
        outcome = str(payload.get("outcome") or "").strip().lower()
        if outcome not in TERMINAL_OUTCOMES:
            payload = {
                "outcome": "blocked",
                "reason_code": "unsupported-outcome",
                "summary": f"unsupported outcome in structured payload: {outcome}",
                "decision_required": False,
            }
            _emit_execution_result(payload)
            print(payload["summary"], file=sys.stderr)
            return INVALID_RESULT_PAYLOAD_EXIT_CODE

        if outcome == "done" and not changed_paths:
            payload = {
                **payload,
                "outcome": "blocked",
                "reason_code": "no-repo-change",
                "summary": payload.get("summary")
                or "codex reported done but produced no repository content changes",
                "decision_required": False,
            }
            _emit_execution_result(payload)
            print(
                "codex exited 0 but produced no repository content changes",
                file=sys.stderr,
            )
            return NO_REPO_CHANGE_EXIT_CODE

        payload = {
            **payload,
            "changed_paths": changed_paths,
            "preexisting_dirty_paths": sorted(preexisting_dirty_paths),
            "decision_required": bool(
                payload.get("decision_required") or outcome == "needs_decision"
            ),
        }
        _emit_execution_result(payload)

        if outcome == "done":
            if changed_paths:
                print("changed paths:\n" + "\n".join(changed_paths))
            return 0
        if outcome == ALREADY_SATISFIED_OUTCOME:
            return 0
        if outcome == "needs_decision":
            return NEEDS_DECISION_EXIT_CODE
        return INVALID_RESULT_PAYLOAD_EXIT_CODE


def _load_timeout_seconds() -> int:
    raw = os.environ.get("TASKPLANE_CODEX_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 1200
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit("TASKPLANE_CODEX_TIMEOUT_SECONDS must be an integer") from exc
    if value <= 0:
        raise SystemExit("TASKPLANE_CODEX_TIMEOUT_SECONDS must be positive")
    return value


def _load_codex_model() -> str:
    return (
        os.environ.get("TASKPLANE_CODEX_MODEL")
        or os.environ.get("TASKPLANE_LLM_EXECUTOR_MODEL")
        or DEFAULT_CODEX_MODEL
    ).strip()


def _build_codex_exec_command(
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
        _load_codex_model(),
        "--output-last-message",
        str(output_last_message_path),
        "-C",
        str(focus_dir),
        prompt,
    ]


def _extract_codex_payload(
    *,
    raw_stream: str,
    output_last_message_path: Path,
) -> dict[str, Any] | None:
    payload = _extract_json_payload_from_file(output_last_message_path)
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
        candidate = _extract_json_payload_from_codex_event(event)
        if candidate is not None:
            return candidate
    return None


def _extract_json_payload_from_file(path: Path) -> dict[str, Any] | None:
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


def _extract_json_payload_from_codex_event(event: Any) -> dict[str, Any] | None:
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


def _classify_missing_codex_payload(raw_stream: str) -> dict[str, Any]:
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


def _classify_nonzero_codex_payload(
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
    payload = _classify_nonzero_exit_payload(returncode=returncode)
    payload["summary"] = f"codex exited with code {returncode}"
    return payload


def _select_codex_focus_dir(*, project_dir: Path, issue_body: str) -> Path:
    allowed_paths = _extract_allowed_paths(issue_body)
    if not allowed_paths:
        return project_dir
    for path in allowed_paths:
        candidate = project_dir / Path(path)
        if candidate.is_dir():
            return candidate.resolve()
        if candidate.exists():
            return candidate.parent.resolve()
    return project_dir


if __name__ == "__main__":
    raise SystemExit(main())
