from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import selectors
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from io import TextIOBase
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

from .execution_protocol import (
    EXECUTION_CHECKPOINT_MARKER,
    EXECUTION_RESULT_MARKER,
    EXECUTION_RETRY_INTENT_MARKER,
    EXECUTION_WAIT_MARKER,
    classify_execution_payload,
)
from .contextweaver_indexing import ensure_contextweaver_index_for_checkout

NO_REPO_CHANGE_EXIT_CODE = 3
INVALID_RESULT_PAYLOAD_EXIT_CODE = 4
NEEDS_DECISION_EXIT_CODE = 5
TIMEOUT_EXIT_CODE = 124
ALREADY_SATISFIED_OUTCOME = "already_satisfied"
TERMINAL_OUTCOMES = {"done", "blocked", "needs_decision", ALREADY_SATISFIED_OUTCOME}
NON_TERMINAL_REASON_CODES = {
    "awaiting_background_context",
    "awaiting_background_research",
    "waiting_for_context_gathering",
    "research_in_progress",
    "context_gathering_in_progress",
}
PAUSED_REASON_CODES = {
    "awaiting_user_input",
    "ask_next_step",
    "awaiting_next_step",
    "paused_for_input",
}
PROGRESS_SIGNAL_KINDS = {"checkpoint", "wait", "retry_intent"}


@dataclass
class MonitoredSubprocessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    timeout_kind: str | None = None
    elapsed_seconds: float = 0.0
    progress_signal_count: int = 0
    last_progress_kind: str | None = None


@dataclass(frozen=True)
class ResultPayloadExtraction:
    payload: dict | None
    terminal_payload_count: int
    distinct_terminal_payload_count: int
    marker_terminal_payload_count: int
    observed_event_types: tuple[str, ...] = ()


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
    return run_controlled_opencode_task(
        work_id=work_id,
        dsn=dsn,
        project_dir=project_dir,
        resume_context=resume_context,
    )


def run_controlled_opencode_task(
    *,
    work_id: str,
    dsn: str,
    project_dir: Path,
    bounded_mode: bool | None = None,
    timeout_seconds: int | None = None,
    resume_context: str = "",
) -> int:
    bounded_mode = (
        _is_bounded_mode_enabled() if bounded_mode is None else bool(bounded_mode)
    )
    timeout_seconds = (
        _load_timeout_seconds(bounded_mode=bounded_mode)
        if timeout_seconds is None
        else timeout_seconds
    )
    hard_cap_seconds = _load_hard_cap_seconds(
        timeout_seconds=timeout_seconds,
        bounded_mode=bounded_mode,
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
        bounded_mode=bounded_mode,
        resume_context=resume_context,
    )
    focus_dir = _select_opencode_focus_dir(
        project_dir=project_dir, issue_body=issue_body
    )
    _emit_phase(
        "before_opencode_run",
        timeout_seconds=timeout_seconds,
        hard_cap_seconds=hard_cap_seconds,
        bounded_mode=bounded_mode,
    )
    completed = _run_monitored_subprocess(
        _build_opencode_run_command(focus_dir=focus_dir, prompt=prompt),
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
    _emit_phase("after_opencode_run", returncode=completed.returncode)

    raw_stream = (completed.stdout or "") + (completed.stderr or "")
    payload_details = _extract_result_payload_details(raw_stream)
    payload = payload_details.payload
    after_snapshot = _capture_worktree_snapshot(repo_root)
    changed_paths = _compute_changed_paths(before_snapshot, after_snapshot)
    if completed.returncode != 0:
        _emit_execution_result(
            _classify_nonzero_exit_payload(returncode=completed.returncode)
        )
        return completed.returncode
    if payload is None:
        payload = _build_salvaged_done_payload(changed_paths=changed_paths)
        if payload is None:
            malformed_stream_payload = _classify_malformed_stream_payload(raw_stream)
            if malformed_stream_payload is not None:
                _emit_execution_result(malformed_stream_payload)
                print(malformed_stream_payload["summary"], file=sys.stderr)
                return INVALID_RESULT_PAYLOAD_EXIT_CODE
            wait_hint = _extract_wait_hint(completed.stdout or "")
            if wait_hint is not None:
                resume_hint = str(wait_hint.get("resume_hint") or "").strip()
                _emit_execution_result(
                    {
                        "outcome": "blocked",
                        "reason_code": "needs_decomposition",
                        "summary": f"opencode delegated to subagent; task too complex for single run. resume_hint: {resume_hint}"[
                            :480
                        ],
                        "decision_required": False,
                    }
                )
                print(
                    "opencode emitted wait payload with resume_hint; treating as needs_decomposition",
                    file=sys.stderr,
                )
                return INVALID_RESULT_PAYLOAD_EXIT_CODE
            upstream_api_error_payload = _classify_upstream_api_error_payload(raw_stream)
            if upstream_api_error_payload is not None:
                _emit_execution_result(upstream_api_error_payload)
                print(upstream_api_error_payload["summary"], file=sys.stderr)
                return INVALID_RESULT_PAYLOAD_EXIT_CODE
            missing_terminal_payload = _classify_missing_terminal_payload(raw_stream)
            if missing_terminal_payload is not None:
                _emit_execution_result(missing_terminal_payload)
                print(missing_terminal_payload["summary"], file=sys.stderr)
                return INVALID_RESULT_PAYLOAD_EXIT_CODE
            _emit_execution_result(
                {
                    "outcome": "blocked",
                    "reason_code": "invalid-result-payload",
                    "summary": "opencode did not emit a valid structured result payload",
                    "decision_required": False,
                }
            )
            print(
                "opencode exited 0 but did not emit a valid structured result payload",
                file=sys.stderr,
            )
            return INVALID_RESULT_PAYLOAD_EXIT_CODE
    multiple_terminal_payload = _classify_multiple_terminal_payload(payload_details)
    if multiple_terminal_payload is not None:
        _emit_execution_result(multiple_terminal_payload)
        print(multiple_terminal_payload["summary"], file=sys.stderr)
        return INVALID_RESULT_PAYLOAD_EXIT_CODE

    execution_kind = classify_execution_payload(payload)
    if execution_kind in {"checkpoint", "wait", "retry_intent"}:
        _emit_intermediate_payload(payload, kind=execution_kind)
        return 0
    if _is_non_terminal_payload(payload):
        payload = {
            "outcome": "blocked",
            "reason_code": "non_terminal_result_payload",
            "summary": "opencode returned a non-terminal payload; it must return done, already_satisfied, needs_decision, or blocked.",
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
            or "opencode reported done but produced no repository content changes",
            "decision_required": False,
        }
        _emit_execution_result(payload)
        print(
            "opencode exited 0 but produced no repository content changes",
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
            print(
                "changed paths:\n" + "\n".join(changed_paths),
            )
        return 0
    if outcome == ALREADY_SATISFIED_OUTCOME:
        return 0
    if outcome == "needs_decision":
        return NEEDS_DECISION_EXIT_CODE
    if outcome == "blocked":
        return INVALID_RESULT_PAYLOAD_EXIT_CODE
    return INVALID_RESULT_PAYLOAD_EXIT_CODE


def _format_resume_context_section(resume_context: str) -> str:
    if not resume_context:
        return ""
    return (
        "13.5. 这是上一轮执行的进度摘要（请基于此继续，不要重复已完成的工作）：\n"
        f"{resume_context}\n\n"
    )


def _build_prompt(
    row: dict, *, bounded_mode: bool = False, resume_context: str = ""
) -> str:
    source_issue_number = row.get("source_issue_number")
    issue_body = (row.get("body") or "").strip()
    dod_json = _normalize_dod_json(row.get("dod_json"))
    story_issue_numbers = dod_json.get("story_issue_numbers", [])
    story_text = ", ".join(f"#{number}" for number in story_issue_numbers) or "无"
    goal_section = _extract_markdown_section(issue_body, {"目标", "Goal"})
    allowed_modify = _extract_markdown_section(issue_body, {"修改范围", "Scope"})
    verification_section = _extract_markdown_section(
        issue_body, {"验证方式", "Verification"}
    )
    dod_section = _extract_markdown_section(
        issue_body, {"验收标准 (DoD)", "验收标准", "DoD"}
    )
    references_section = _extract_markdown_section(issue_body, {"参考", "References"})
    mode_clause = (
        "15. 当前为 bounded implementation mode：不要进行背景研究、不要做开放式仓库探索、不要尝试多阶段计划；只围绕允许修改范围完成最小必要实现，并快速给出终态 JSON。\n"
        if bounded_mode
        else ""
    )
    return (
        f"你正在执行 GitHub Issue #{source_issue_number}。\n"
        f"Work ID: {row['id']}\n"
        f"标题: {row['title']}\n"
        f"Lane: {row['lane']}\n"
        f"Wave: {row['wave']}\n"
        f"Complexity: {row['complexity']}\n"
        f"上级 Story: {story_text}\n\n"
        "要求：\n"
        "1. 在仓库内直接完成该 issue 所要求的最小必要变更。\n"
        "2. 严格遵守 AGENTS.md、CONTRIBUTING.md、冻结边界和 owner 规则。\n"
        "3. 不要提交 commit，不要创建 PR。\n"
        "4. 不要向人类提问，不要等待交互输入；如果需要人类决策，直接返回结构化 needs_decision 结果并退出。\n"
        "5. 如果仓库当前状态已经满足 issue 的 DoD，不要返回 blocked，也不要等待更多研究，直接返回 already_satisfied。\n"
        "6. 你可以输出两种 JSON：\n"
        "   - 终态 JSON（terminal）：outcome 为 done/already_satisfied/blocked/needs_decision\n"
        '     格式: {"outcome":"done|already_satisfied|blocked|needs_decision","summary":"...","reason_code":"...","decision_required":true|false}\n'
        "   - 检查点 JSON（checkpoint）：用于分步完成时暂存进度\n"
        '     格式: {"execution_kind":"checkpoint","phase":"researching|implementing|verifying|repairing","summary":"...","artifacts":{},"next_action_hint":"..."}\n'
        "   - 等待 JSON（wait）：当需要等待外部工具或子结果时使用\n"
        '     格式: {"execution_kind":"wait","wait_type":"tool_result|subagent_result|timer","summary":"...","resume_hint":"..."}\n'
        "7. 优先只阅读、修改和验证当前任务明确允许的路径；不要在整个仓库范围内做宽泛探索，除非任务正文明确要求。\n"
        f"8. 任务目标（若有）如下：\n{goal_section or '未显式提供，按标题和 Story 语义推断最小目标。'}\n"
        f"9. 允许修改范围（若有）如下：\n{allowed_modify or '未显式提供，按任务正文最小必要范围处理。'}\n"
        f"10. 验收标准（若有）如下：\n{dod_section or '未显式提供，至少满足任务标题和验证方式。'}\n"
        f"11. 验证方式（若有）如下：\n{verification_section or '未显式提供，使用最小必要验证。'}\n"
        f"12. 参考（若有）如下：\n{references_section or '未显式提供。'}\n"
        "13. 不要重复全文复述 issue，也不要因为仓库大就全量扫描；先按允许修改范围与验证目标直接进入实现。\n"
        f"{mode_clause}"
        f"{_format_resume_context_section(resume_context)}"
        "14. 最终只输出一个 JSON 对象，不要输出 Markdown 代码块，不要输出 JSON 之外的最终总结。\n\n"
        f"仅供必要参考的任务正文片段如下：\n{goal_section or ''}\n{allowed_modify or ''}\n{dod_section or ''}\n{verification_section or ''}\n{references_section or ''}\n"
    )


def _normalize_dod_json(raw_dod_json: Any) -> dict[str, Any]:
    if isinstance(raw_dod_json, dict):
        return raw_dod_json
    if isinstance(raw_dod_json, list):
        normalized_items = [
            str(item).strip() for item in raw_dod_json if str(item).strip()
        ]
        return {"checklist": normalized_items}
    return {}


def _build_opencode_run_command(*, focus_dir: Path, prompt: str) -> list[str]:
    command = [
        "opencode",
        "run",
        "--format",
        "json",
        "--dir",
        str(focus_dir),
    ]
    configured_model = os.environ.get("TASKPLANE_OPENCODE_MODEL", "").strip()
    if configured_model:
        command.extend(["--model", configured_model])
    configured_variant = os.environ.get("TASKPLANE_OPENCODE_VARIANT", "").strip()
    if configured_variant:
        command.extend(["--variant", configured_variant])
    command.append(prompt)
    return command


def _extract_markdown_section(body: str, headings: set[str]) -> str:
    pattern = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(body or ""))
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        if heading not in headings:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        return body[start:end].strip()
    return ""


def _extract_allowed_paths(issue_body: str) -> list[str]:
    allowed_modify = _extract_markdown_section(issue_body, {"修改范围", "Scope"})
    paths: list[str] = []
    for line in allowed_modify.splitlines():
        stripped = line.strip().lstrip("-*•").strip().strip("`")
        if not stripped or "/" not in stripped:
            continue
        candidate = stripped.rstrip("/")
        if candidate.endswith("/*"):
            candidate = candidate[:-2]
        paths.append(candidate)
    return paths


def _select_opencode_focus_dir(*, project_dir: Path, issue_body: str) -> Path:
    allowed_paths = _extract_allowed_paths(issue_body)
    if not allowed_paths:
        return project_dir
    for path in allowed_paths:
        candidate = project_dir / Path(path)
        if candidate.is_dir():
            return candidate.resolve()
        if candidate.exists():
            return candidate.parent.resolve()
    for path in allowed_paths:
        parts = Path(path).parts
        if len(parts) >= 2:
            candidate = project_dir / Path(*parts[:2])
            if candidate.is_dir():
                return candidate.resolve()
    return project_dir


def _load_timeout_seconds(*, bounded_mode: bool = False) -> int:
    raw = os.environ.get("TASKPLANE_OPENCODE_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 300 if bounded_mode else 1200
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(
            "TASKPLANE_OPENCODE_TIMEOUT_SECONDS must be an integer"
        ) from exc
    if value <= 0:
        raise SystemExit("TASKPLANE_OPENCODE_TIMEOUT_SECONDS must be positive")
    return value


def _load_hard_cap_seconds(*, timeout_seconds: int, bounded_mode: bool) -> int:
    raw = os.environ.get("TASKPLANE_OPENCODE_HARD_CAP_SECONDS", "").strip()
    if not raw:
        multiplier = 3 if bounded_mode else 1
        return max(timeout_seconds, timeout_seconds * multiplier)
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(
            "TASKPLANE_OPENCODE_HARD_CAP_SECONDS must be an integer"
        ) from exc
    if value <= 0:
        raise SystemExit("TASKPLANE_OPENCODE_HARD_CAP_SECONDS must be positive")
    if value < timeout_seconds:
        raise SystemExit(
            "TASKPLANE_OPENCODE_HARD_CAP_SECONDS must be >= TASKPLANE_OPENCODE_TIMEOUT_SECONDS"
        )
    return value


def _is_bounded_mode_enabled() -> bool:
    return os.environ.get("TASKPLANE_BOUNDED_EXECUTOR", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _resolve_git_root(project_dir: Path) -> Path | None:
    completed = subprocess.run(
        ["git", "-C", str(project_dir), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    output = (completed.stdout or "").strip()
    if not output:
        return None
    return Path(output).resolve()


def _capture_worktree_snapshot(repo_root: Path) -> dict[str, str]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"failed to list git worktree paths under {repo_root}")

    snapshot: dict[str, str] = {}
    raw_output = completed.stdout.decode("utf-8", errors="surrogateescape")
    for relative_path in sorted({item for item in raw_output.split("\0") if item}):
        snapshot[relative_path] = _fingerprint_path(repo_root / relative_path)
    return snapshot


def _compute_changed_paths(
    before_snapshot: dict[str, str],
    after_snapshot: dict[str, str],
) -> list[str]:
    changed_paths: list[str] = []
    for relative_path in sorted(set(before_snapshot) | set(after_snapshot)):
        if before_snapshot.get(relative_path) != after_snapshot.get(relative_path):
            changed_paths.append(relative_path)
    return changed_paths


def _fingerprint_path(path: Path) -> str:
    if not path.exists():
        return "<deleted>"
    if path.is_dir():
        return "<directory>"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


def _list_dirty_paths(repo_root: Path) -> set[str]:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"failed to read git status under {repo_root}")
    dirty_paths: set[str] = set()
    for line in (completed.stdout or "").splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        dirty_paths.add(path)
    return dirty_paths


def _extract_result_payload(raw_stream: str) -> dict | None:
    return _extract_result_payload_details(raw_stream).payload


def _extract_result_payload_details(raw_stream: str) -> ResultPayloadExtraction:
    candidates: list[tuple[str, bool]] = []
    observed_event_types: list[str] = []
    for line in raw_stream.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(EXECUTION_RESULT_MARKER):
            candidates.append(
                (stripped[len(EXECUTION_RESULT_MARKER) :].strip(), True)
            )
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
        text_candidate = _extract_json_from_text_event(event)
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

    return ResultPayloadExtraction(
        payload=payload,
        terminal_payload_count=len(terminal_payloads),
        distinct_terminal_payload_count=len(distinct_terminal_payloads),
        marker_terminal_payload_count=len(marker_terminal_payloads),
        observed_event_types=tuple(observed_event_types),
    )


def _classify_multiple_terminal_payload(details: ResultPayloadExtraction) -> dict | None:
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


def _classify_malformed_stream_payload(raw_stream: str) -> dict | None:
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


def _classify_missing_terminal_payload(raw_stream: str) -> dict | None:
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


def _classify_upstream_api_error_payload(raw_stream: str) -> dict | None:
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


def _extract_wait_hint(raw_stream: str) -> dict | None:
    for line in raw_stream.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        text_candidate = _extract_json_from_text_event(event)
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


def _extract_json_from_text_event(event: Any) -> str | None:
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


def _emit_execution_result(payload: dict) -> None:
    print(f"{EXECUTION_RESULT_MARKER}{json.dumps(payload, ensure_ascii=False)}")


def _emit_intermediate_payload(payload: dict, *, kind: str) -> None:
    if kind == "checkpoint":
        marker = EXECUTION_CHECKPOINT_MARKER
    elif kind == "wait":
        marker = EXECUTION_WAIT_MARKER
    else:
        marker = EXECUTION_RESULT_MARKER
    print(f"{marker}{json.dumps(payload, ensure_ascii=False)}")


def _emit_phase(phase: str, **fields: Any) -> None:
    details = " ".join(
        f"{key}={value}" for key, value in fields.items() if value not in (None, "")
    )
    suffix = f" {details}" if details else ""
    print(f"TRACE executor phase={phase}{suffix}", file=sys.stderr)


def _build_timeout_payload(
    *,
    timeout_seconds: int,
    hard_cap_seconds: int | None = None,
    timeout_kind: str | None = None,
    partial_output: str = "",
) -> dict:
    if timeout_kind == "hard_cap" and hard_cap_seconds is not None:
        summary = f"opencode exceeded hard cap after {hard_cap_seconds} seconds"
    else:
        summary = f"opencode exceeded timeout after {timeout_seconds} seconds"
    if partial_output:
        summary = f"{summary}; partial output: {partial_output}"
    payload: dict[str, Any] = {
        "outcome": "blocked",
        "reason_code": "timeout",
        "summary": summary,
        "decision_required": False,
    }
    resume_context = _build_resume_context_from_output(partial_output)
    if resume_context:
        payload["resume_context"] = resume_context
    return payload


def _build_resume_context_from_output(output: str, *, max_chars: int = 1200) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return ""
    context = "\n".join(lines)
    if len(context) > max_chars:
        context = context[-max_chars:]
    return context


def _summarize_partial_output(output: str, *, max_chars: int = 240) -> str:
    text = " ".join(line.strip() for line in output.splitlines() if line.strip())
    text = text.strip()
    if not text:
        return ""
    return text[:max_chars]


def _build_salvaged_done_payload(*, changed_paths: list[str]) -> dict[str, Any] | None:
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


def _is_non_terminal_payload(payload: dict) -> bool:
    kind = classify_execution_payload(payload)
    if kind in {"checkpoint", "wait", "retry_intent"}:
        return False
    reason_code = str(payload.get("reason_code") or "").strip().lower()
    summary = str(payload.get("summary") or "").strip().lower()
    if reason_code in NON_TERMINAL_REASON_CODES:
        return True
    disallowed_summary_markers = (
        "background context",
        "background research",
        "context gathering",
        "still in flight",
        "awaiting background",
        "waiting for context",
    )
    return any(marker in summary for marker in disallowed_summary_markers)


def _normalize_payload(payload: dict) -> dict:
    reason_code = str(payload.get("reason_code") or "").strip().lower()
    if reason_code in PAUSED_REASON_CODES:
        return {
            **payload,
            "outcome": "needs_decision",
            "decision_required": True,
        }
    return payload


def _classify_nonzero_exit_payload(*, returncode: int) -> dict:
    if returncode in {130, 143}:
        return {
            "outcome": "blocked",
            "reason_code": "interrupted_retryable",
            "summary": "opencode was interrupted before reaching a terminal result",
            "decision_required": False,
        }
    return {
        "outcome": "blocked",
        "reason_code": "tooling_error",
        "summary": f"opencode exited with code {returncode}",
        "decision_required": False,
    }


def _run_monitored_subprocess(
    command: list[str],
    *,
    cwd: Path | None,
    no_progress_timeout_seconds: float,
    hard_cap_seconds: float,
) -> MonitoredSubprocessResult:
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    selector = selectors.DefaultSelector()
    stdout_buffer: list[str] = []
    stderr_buffer: list[str] = []
    partial_lines: dict[int, str] = {}
    progress_signal_count = 0
    last_progress_kind: str | None = None
    start = time.monotonic()
    no_progress_deadline = start + no_progress_timeout_seconds
    hard_cap_deadline = start + hard_cap_seconds

    try:
        if process.stdout is not None:
            selector.register(process.stdout, selectors.EVENT_READ, data="stdout")
        if process.stderr is not None:
            selector.register(process.stderr, selectors.EVENT_READ, data="stderr")

        while True:
            now = time.monotonic()
            if now >= hard_cap_deadline:
                process.kill()
                _drain_remaining_streams(
                    selector=selector,
                    stdout_buffer=stdout_buffer,
                    stderr_buffer=stderr_buffer,
                    partial_lines=partial_lines,
                )
                process.wait()
                return MonitoredSubprocessResult(
                    returncode=TIMEOUT_EXIT_CODE,
                    stdout="".join(stdout_buffer),
                    stderr="".join(stderr_buffer),
                    timed_out=True,
                    timeout_kind="hard_cap",
                    elapsed_seconds=time.monotonic() - start,
                    progress_signal_count=progress_signal_count,
                    last_progress_kind=last_progress_kind,
                )
            if now >= no_progress_deadline:
                process.kill()
                _drain_remaining_streams(
                    selector=selector,
                    stdout_buffer=stdout_buffer,
                    stderr_buffer=stderr_buffer,
                    partial_lines=partial_lines,
                )
                process.wait()
                return MonitoredSubprocessResult(
                    returncode=TIMEOUT_EXIT_CODE,
                    stdout="".join(stdout_buffer),
                    stderr="".join(stderr_buffer),
                    timed_out=True,
                    timeout_kind="no_progress",
                    elapsed_seconds=time.monotonic() - start,
                    progress_signal_count=progress_signal_count,
                    last_progress_kind=last_progress_kind,
                )

            if process.poll() is not None and not selector.get_map():
                break

            timeout = max(0.01, min(no_progress_deadline, hard_cap_deadline) - now)
            events = selector.select(timeout)
            if not events:
                if process.poll() is not None:
                    break
                continue
            for key, _ in events:
                stream = cast(TextIOBase, key.fileobj)
                chunk = stream.readline()
                if chunk == "":
                    try:
                        selector.unregister(stream)
                    except Exception:
                        pass
                    continue
                stream_name = key.data
                if stream_name == "stdout":
                    stdout_buffer.append(chunk)
                else:
                    stderr_buffer.append(chunk)
                progress_kind = _detect_progress_signal_from_chunk(
                    chunk,
                    partial_lines=partial_lines,
                    stream_key=id(stream),
                )
                if progress_kind is not None:
                    progress_signal_count += 1
                    last_progress_kind = progress_kind
                    no_progress_deadline = min(
                        time.monotonic() + no_progress_timeout_seconds,
                        hard_cap_deadline,
                    )

        _drain_remaining_streams(
            selector=selector,
            stdout_buffer=stdout_buffer,
            stderr_buffer=stderr_buffer,
            partial_lines=partial_lines,
        )
        return MonitoredSubprocessResult(
            returncode=process.wait(),
            stdout="".join(stdout_buffer),
            stderr="".join(stderr_buffer),
            timed_out=False,
            elapsed_seconds=time.monotonic() - start,
            progress_signal_count=progress_signal_count,
            last_progress_kind=last_progress_kind,
        )
    finally:
        selector.close()
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()


def _drain_remaining_streams(
    *,
    selector: selectors.BaseSelector,
    stdout_buffer: list[str],
    stderr_buffer: list[str],
    partial_lines: dict[int, str],
) -> None:
    while selector.get_map():
        events = selector.select(0)
        if not events:
            break
        for key, _ in events:
            stream = cast(TextIOBase, key.fileobj)
            chunk = stream.readline()
            if chunk == "":
                try:
                    selector.unregister(stream)
                except Exception:
                    pass
                continue
            if key.data == "stdout":
                stdout_buffer.append(chunk)
            else:
                stderr_buffer.append(chunk)
            _detect_progress_signal_from_chunk(
                chunk,
                partial_lines=partial_lines,
                stream_key=id(stream),
            )


def _detect_progress_signal_from_chunk(
    chunk: str,
    *,
    partial_lines: dict[int, str],
    stream_key: int,
) -> str | None:
    buffer = partial_lines.get(stream_key, "") + chunk
    lines = buffer.splitlines(keepends=True)
    if lines and not lines[-1].endswith(("\n", "\r")):
        partial_lines[stream_key] = lines.pop()
    else:
        partial_lines.pop(stream_key, None)
    for raw_line in lines:
        progress_kind = _extract_progress_signal_kind(raw_line.strip())
        if progress_kind is not None:
            return progress_kind
    return None


def _extract_progress_signal_kind(line: str) -> str | None:
    if not line:
        return None
    for marker, kind in (
        (EXECUTION_CHECKPOINT_MARKER, "checkpoint"),
        (EXECUTION_WAIT_MARKER, "wait"),
        (EXECUTION_RETRY_INTENT_MARKER, "retry_intent"),
    ):
        if line.startswith(marker):
            try:
                payload = json.loads(line[len(marker) :])
            except json.JSONDecodeError:
                return None
            return kind if classify_execution_payload(payload) == kind else None
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(event, dict):
        return None

    opencode_event_types = {
        "step_start": "step_start",
        "step_finish": "step_finish",
        "message_start": "message_start",
        "tool_start": "tool_start",
        "tool_finish": "tool_finish",
        "file_edit": "file_edit",
        "shell": "shell",
    }
    event_type = event.get("type")
    if isinstance(event_type, str) and event_type in opencode_event_types:
        return opencode_event_types[event_type]

    if event.get("type") != "text":
        return None
    part = event.get("part")
    if not isinstance(part, dict):
        return None
    text = str(part.get("text") or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    kind = (
        classify_execution_payload(payload) if isinstance(payload, dict) else "unknown"
    )
    return kind if kind in PROGRESS_SIGNAL_KINDS else None


if __name__ == "__main__":
    raise SystemExit(main())
