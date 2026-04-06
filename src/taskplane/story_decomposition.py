from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Callable

from .fallback_templates import default_fallback_payload_for_story
from .contextatlas_indexing import ensure_contextatlas_index_for_checkout

from .github_sync import fetch_issues_via_gh, persist_issue_import_batch
from .governance_sync import (
    build_program_governance_projection,
    sync_program_governance_to_control_plane,
)
from .projection_sync import (
    _load_normalized_issues,
    load_projection_from_staging,
    sync_projection_to_control_plane,
)
from .protocols import IntakeAdapter, invoke_intake
from .repository import StoryDecompositionRepository


DECOMPOSITION_RESULT_MARKER = "TASKPLANE_DECOMPOSITION_RESULT_JSON="


@dataclass(frozen=True)
class DecompositionExecutionResult:
    success: bool
    outcome: str
    summary: str
    reason_code: str | None = None


@dataclass(frozen=True)
class StoryDecompositionResult:
    story_issue_number: int
    final_execution_status: str
    projectable_task_count: int
    summary: str
    reason_code: str | None = None


def run_story_decomposition(
    *,
    repo: str,
    story_issue_number: int,
    repository: StoryDecompositionRepository,
    workdir: Path | None = None,
    decomposer_command: str | None = None,
    story_loader: Callable[..., dict[str, Any]] | None = None,
    decomposer: Callable[..., DecompositionExecutionResult] | None = None,
    refresher: IntakeAdapter | None = None,
    fallback_generator: Callable[..., bool] | None = None,
) -> StoryDecompositionResult:
    connection = getattr(repository, "_connection", repository)
    story_loader = story_loader or load_decomposition_story
    decomposer = decomposer or run_shell_story_decomposer
    refresher = refresher or refresh_control_plane_from_github
    fallback_generator = fallback_generator or _default_story_task_fallback_generator

    current_story = story_loader(
        connection=connection,
        repo=repo,
        story_issue_number=story_issue_number,
    )
    execution = decomposer(
        repo=repo,
        story_issue_number=story_issue_number,
        story=current_story,
        workdir=(workdir or Path.cwd()).resolve(),
        decomposer_command=decomposer_command,
    )

    if execution.outcome == "needs_story_refinement":
        repository.set_program_story_execution_status(
            repo=repo,
            issue_number=story_issue_number,
            execution_status="needs_story_refinement",
        )
        return StoryDecompositionResult(
            story_issue_number=story_issue_number,
            final_execution_status="needs_story_refinement",
            projectable_task_count=int(current_story.get("story_task_count") or 0),
            summary=execution.summary,
            reason_code=_normalize_reason_code(execution.reason_code),
        )

    if not execution.success or execution.outcome == "blocked":
        repository.set_program_story_execution_status(
            repo=repo,
            issue_number=story_issue_number,
            execution_status="blocked",
        )
        return StoryDecompositionResult(
            story_issue_number=story_issue_number,
            final_execution_status="blocked",
            projectable_task_count=int(current_story.get("story_task_count") or 0),
            summary=execution.summary,
            reason_code=_normalize_reason_code(execution.reason_code),
        )

    refreshed_story, task_count, execution = (
        _refresh_story_until_projectable_or_exhausted(
            connection=connection,
            repo=repo,
            story_issue_number=story_issue_number,
            story=current_story,
            workdir=(workdir or Path.cwd()).resolve(),
            decomposer_command=decomposer_command,
            story_loader=story_loader,
            decomposer=decomposer,
            refresher=refresher,
            execution=execution,
        )
    )
    if task_count <= 0:
        fallback_generated = fallback_generator(
            repo=repo,
            story_issue_number=story_issue_number,
            story=refreshed_story,
            workdir=(workdir or Path.cwd()).resolve(),
        )
        if fallback_generated:
            invoke_intake(refresher, connection=connection, repo=repo)
            refreshed_story = story_loader(
                connection=connection,
                repo=repo,
                story_issue_number=story_issue_number,
            )
            task_count = int(refreshed_story.get("story_task_count") or 0)
        if task_count <= 0:
            repository.set_program_story_execution_status(
                repo=repo,
                issue_number=story_issue_number,
                execution_status="needs_story_refinement",
            )
            return StoryDecompositionResult(
                story_issue_number=story_issue_number,
                final_execution_status="needs_story_refinement",
                projectable_task_count=task_count,
                summary=(
                    "decomposer finished but no projectable tasks were created; "
                    + (
                        "fallback task generation attempted but story still needs refinement"
                        if fallback_generated
                        else "story needs refinement or fallback task generation"
                    )
                ),
                reason_code="zero_projectable_tasks_after_retry",
            )

    if (
        _requires_core_path_task(refreshed_story)
        and int(refreshed_story.get("core_task_count") or 0) <= 0
    ):
        repository.set_program_story_execution_status(
            repo=repo,
            issue_number=story_issue_number,
            execution_status="needs_story_refinement",
        )
        return StoryDecompositionResult(
            story_issue_number=story_issue_number,
            final_execution_status="needs_story_refinement",
            projectable_task_count=task_count,
            summary="decomposer created doc-only tasks for implementation-oriented story",
            reason_code="implementation_story_missing_core_tasks",
        )

    if refreshed_story.get("execution_status") != "active":
        repository.set_program_story_execution_status(
            repo=repo,
            issue_number=story_issue_number,
            execution_status="active",
        )
    return StoryDecompositionResult(
        story_issue_number=story_issue_number,
        final_execution_status="active",
        projectable_task_count=task_count,
        summary=execution.summary,
        reason_code=_normalize_reason_code(execution.reason_code),
    )


def _refresh_story_until_projectable_or_exhausted(
    *,
    connection: Any,
    repo: str,
    story_issue_number: int,
    story: dict[str, Any],
    workdir: Path,
    decomposer_command: str | None,
    story_loader: Callable[..., dict[str, Any]],
    decomposer: Callable[..., DecompositionExecutionResult],
    refresher: IntakeAdapter,
    execution: DecompositionExecutionResult,
) -> tuple[dict[str, Any], int, DecompositionExecutionResult]:
    invoke_intake(refresher, connection=connection, repo=repo)
    refreshed_story = story_loader(
        connection=connection,
        repo=repo,
        story_issue_number=story_issue_number,
    )
    task_count = int(refreshed_story.get("story_task_count") or 0)
    if task_count > 0:
        return refreshed_story, task_count, execution
    if not _should_retry_zero_projectable_outcome(execution):
        return refreshed_story, task_count, execution

    retry_execution = decomposer(
        repo=repo,
        story_issue_number=story_issue_number,
        story=refreshed_story,
        workdir=workdir,
        decomposer_command=decomposer_command,
    )
    if retry_execution.outcome == "needs_story_refinement" or (
        not retry_execution.success or retry_execution.outcome == "blocked"
    ):
        return refreshed_story, task_count, retry_execution

    invoke_intake(refresher, connection=connection, repo=repo)
    refreshed_story = story_loader(
        connection=connection,
        repo=repo,
        story_issue_number=story_issue_number,
    )
    task_count = int(refreshed_story.get("story_task_count") or 0)
    return refreshed_story, task_count, retry_execution


def _should_retry_zero_projectable_outcome(
    execution: DecompositionExecutionResult,
) -> bool:
    if execution.outcome != "decomposed" or not execution.success:
        return False
    reason_code = _normalize_reason_code(execution.reason_code)
    return reason_code in {
        None,
        "no_projectable_tasks_generated",
        "zero_projectable_tasks",
        "no_projectable_tasks",
        "invalid-task-payload",
    }


def _normalize_reason_code(reason_code: str | None) -> str | None:
    normalized = str(reason_code or "").strip()
    return normalized or None


def _summarize_partial_output(output: str, *, max_chars: int = 240) -> str:
    text = " ".join(line.strip() for line in output.splitlines() if line.strip())
    text = text.strip()
    if not text:
        return ""
    return text[:max_chars]


def load_decomposition_story(
    *,
    connection: Any,
    repo: str,
    story_issue_number: int,
) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                s.issue_number AS story_issue_number,
                s.title AS story_title,
                s.execution_status,
                COALESCE(task_counts.story_task_count, 0) AS story_task_count,
                COALESCE(task_counts.core_task_count, 0) AS core_task_count,
                COALESCE(task_counts.documentation_task_count, 0) AS documentation_task_count,
                COALESCE(task_counts.governance_task_count, 0) AS governance_task_count,
                gin.body AS story_body
            FROM program_story s
            LEFT JOIN (
                SELECT
                    repo,
                    canonical_story_issue_number AS story_issue_number,
                    COUNT(*) AS story_task_count,
                    COUNT(*) FILTER (WHERE task_type = 'core_path') AS core_task_count,
                    COUNT(*) FILTER (WHERE task_type = 'documentation') AS documentation_task_count,
                    COUNT(*) FILTER (WHERE task_type = 'governance') AS governance_task_count
                FROM work_item
                WHERE canonical_story_issue_number IS NOT NULL
                GROUP BY repo, canonical_story_issue_number
            ) task_counts
              ON task_counts.repo = s.repo
             AND task_counts.story_issue_number = s.issue_number
            LEFT JOIN github_issue_normalized gin
              ON gin.repo = s.repo
             AND gin.issue_number = s.issue_number
            WHERE s.repo = %s
              AND s.issue_number = %s
            """,
            (repo, story_issue_number),
        )
        row = cursor.fetchone()
    if row is None:
        raise KeyError(story_issue_number)
    return dict(row)


def run_shell_story_decomposer(
    *,
    repo: str,
    story_issue_number: int,
    story: dict[str, Any],
    workdir: Path,
    decomposer_command: str | None,
) -> DecompositionExecutionResult:
    command_template = (decomposer_command or "").strip()
    project_dir = workdir.resolve()
    timeout_seconds = _load_timeout_seconds()
    if not command_template:
        return DecompositionExecutionResult(
            success=False,
            outcome="blocked",
            summary="TASKPLANE_DECOMPOSER_COMMAND is required",
            reason_code="missing-decomposer-command",
        )
    index_error = ensure_contextatlas_index_for_checkout(
        project_dir,
        explicit_repo=repo,
    )
    if index_error is not None:
        return DecompositionExecutionResult(
            success=False,
            outcome="blocked",
            summary=f"contextatlas index failed: {index_error}",
            reason_code="contextatlas-index-failed",
        )
    env = os.environ.copy()
    env.update(
        {
            "TASKPLANE_STORY_ISSUE_NUMBER": str(story_issue_number),
            "TASKPLANE_STORY_TITLE": str(story.get("story_title") or ""),
            "TASKPLANE_STORY_REPO": repo,
            "TASKPLANE_PROJECT_DIR": str(project_dir),
        }
    )
    started_at = time.perf_counter()
    try:
        completed = _run_decomposer_subprocess(
            command_template=command_template,
            project_dir=project_dir,
            env=env,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        _ = max(0, int((time.perf_counter() - started_at) * 1000))
        diagnostic = _summarize_partial_output(
            str(getattr(exc, "stdout", "") or getattr(exc, "output", "") or "")
            + str(getattr(exc, "stderr", "") or "")
        )
        return DecompositionExecutionResult(
            success=False,
            outcome="blocked",
            summary=(
                f"decomposer exceeded timeout after {timeout_seconds} seconds"
                + (f"; partial output: {diagnostic}" if diagnostic else "")
            ),
            reason_code="timeout",
        )
    _ = max(0, int((time.perf_counter() - started_at) * 1000))
    payload = _extract_decomposition_payload(
        (completed.stdout or "") + (completed.stderr or "")
    )
    if completed.returncode != 0:
        return DecompositionExecutionResult(
            success=False,
            outcome="blocked",
            summary=payload.get("summary")
            or f"decomposer exited with code {completed.returncode}",
            reason_code=payload.get("reason_code") or "decomposer-exit-nonzero",
        )
    if not payload:
        return DecompositionExecutionResult(
            success=False,
            outcome="blocked",
            summary="decomposer did not emit a valid payload",
            reason_code="invalid-result-payload",
        )
    outcome = str(payload.get("outcome") or "decomposed").strip().lower()
    if outcome not in {"decomposed", "blocked", "needs_story_refinement"}:
        return DecompositionExecutionResult(
            success=False,
            outcome="blocked",
            summary=f"unsupported outcome in decomposition payload: {outcome}",
            reason_code="unsupported-outcome",
        )
    return DecompositionExecutionResult(
        success=outcome == "decomposed",
        outcome=outcome,
        summary=str(payload.get("summary") or "story decomposition completed").strip(),
        reason_code=str(payload.get("reason_code") or "") or None,
    )


def _load_timeout_seconds() -> int:
    raw = os.environ.get("TASKPLANE_OPENCODE_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 1200
    try:
        value = int(raw)
    except ValueError:
        return 1200
    if value <= 0:
        return 1200
    return value


def _run_decomposer_subprocess(
    *,
    command_template: str,
    project_dir: Path,
    env: dict[str, str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command_template,
        shell=True,
        cwd=str(project_dir),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )


def refresh_control_plane_from_github(*, connection: Any, repo: str) -> None:
    raw_issues = fetch_issues_via_gh(repo=repo, limit=200)
    persist_issue_import_batch(connection=connection, repo=repo, raw_issues=raw_issues)
    issues = _load_normalized_issues(connection=connection, repo=repo)
    governance_projection = build_program_governance_projection(
        repo=repo, issues=issues
    )
    sync_program_governance_to_control_plane(
        connection=connection,
        repo=repo,
        projection=governance_projection,
    )
    task_projection = load_projection_from_staging(connection=connection, repo=repo)
    sync_projection_to_control_plane(
        connection=connection,
        repo=repo,
        projection=task_projection,
    )


def _extract_decomposition_payload(output: str) -> dict[str, Any]:
    candidates: list[str] = []
    for line in output.splitlines():
        if line.startswith(DECOMPOSITION_RESULT_MARKER):
            candidates.append(line[len(DECOMPOSITION_RESULT_MARKER) :].strip())
    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _requires_core_path_task(story: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            str(story.get("story_title") or ""),
            str(story.get("story_body") or ""),
        ]
    ).lower()
    doc_markers = [
        "文档",
        "知识蒸馏",
        "spec",
        "reference",
        "readme",
        "doc",
        "verification closure",
    ]
    if any(marker in haystack for marker in doc_markers):
        return False
    implementation_markers = [
        "入库",
        "实现",
        "runtime",
        "geometry",
        "coordinate",
        "protocol",
        "bridge",
        "rewrite",
        "projection",
        "simulation",
        "定义",
        "conversion",
        "authoring_conversion.py",
        "unit test",
        "单元测试",
    ]
    return any(marker in haystack for marker in implementation_markers)


def _noop_story_task_fallback_generator(**_: Any) -> bool:
    return False


def _default_story_task_fallback_generator(
    *,
    repo: str,
    story_issue_number: int,
    story: dict[str, Any],
    workdir: Path,
) -> bool:
    if not _fallback_enabled():
        return False
    story_body = str(story.get("story_body") or "")
    if "Candidate Tasks" not in story_body or "开放问题" not in story_body:
        return False

    payload = _build_default_fallback_payload(
        story_issue_number=story_issue_number,
        story=story,
    )
    if payload is None:
        return False

    from .opencode_story_decomposer import _create_task_issues_from_payload

    _create_task_issues_from_payload(
        repo=repo,
        story_issue_number=story_issue_number,
        story_row={
            "issue_number": story_issue_number,
            "title": str(story.get("story_title") or ""),
        },
        payload=payload,
        project_dir=workdir,
    )
    return True


def _fallback_enabled() -> bool:
    raw = os.environ.get("TASKPLANE_ENABLE_DEFAULT_DECOMPOSITION_FALLBACK", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _build_default_fallback_payload(
    *,
    story_issue_number: int,
    story: dict[str, Any],
) -> dict[str, Any] | None:
    story_title = str(story.get("story_title") or "").strip()
    lane_match = re.search(r"\[Story\]\[(\d+)-", story_title)
    if lane_match is None:
        return None
    lane = lane_match.group(1)
    return default_fallback_payload_for_story(
        lane=lane,
        story_issue_number=story_issue_number,
        implementation_story=_requires_core_path_task(story),
    )
