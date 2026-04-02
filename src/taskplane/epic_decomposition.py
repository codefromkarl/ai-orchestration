from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable

from .protocols import IntakeAdapter, invoke_intake
from .repository import EpicDecompositionRepository
from .story_decomposition import (
    DECOMPOSITION_RESULT_MARKER,
    refresh_control_plane_from_github,
)


@dataclass(frozen=True)
class DecompositionExecutionResult:
    success: bool
    outcome: str
    summary: str
    reason_code: str | None = None


@dataclass(frozen=True)
class EpicDecompositionResult:
    epic_issue_number: int
    final_execution_status: str
    projectable_story_count: int
    summary: str


def run_epic_decomposition(
    *,
    repo: str,
    epic_issue_number: int,
    repository: EpicDecompositionRepository,
    workdir: Path | None = None,
    decomposer_command: str | None = None,
    epic_loader: Callable[..., dict[str, Any]] | None = None,
    decomposer: Callable[..., DecompositionExecutionResult] | None = None,
    refresher: IntakeAdapter | None = None,
) -> EpicDecompositionResult:
    connection = getattr(repository, "_connection", repository)
    epic_loader = epic_loader or load_decomposition_epic
    decomposer = decomposer or run_shell_epic_decomposer
    refresher = refresher or refresh_control_plane_from_github

    current_epic = epic_loader(
        connection=connection,
        repo=repo,
        epic_issue_number=epic_issue_number,
    )
    execution = decomposer(
        repo=repo,
        epic_issue_number=epic_issue_number,
        epic=current_epic,
        workdir=(workdir or Path.cwd()).resolve(),
        decomposer_command=decomposer_command,
    )

    if execution.outcome == "needs_epic_refinement":
        repository.set_program_epic_execution_status(
            repo=repo,
            issue_number=epic_issue_number,
            execution_status="needs_story_refinement",
        )
        return EpicDecompositionResult(
            epic_issue_number=epic_issue_number,
            final_execution_status="needs_story_refinement",
            projectable_story_count=int(current_epic.get("epic_story_count") or 0),
            summary=execution.summary,
        )

    if not execution.success or execution.outcome == "blocked":
        repository.set_program_epic_execution_status(
            repo=repo,
            issue_number=epic_issue_number,
            execution_status="blocked",
        )
        return EpicDecompositionResult(
            epic_issue_number=epic_issue_number,
            final_execution_status="blocked",
            projectable_story_count=int(current_epic.get("epic_story_count") or 0),
            summary=execution.summary,
        )

    invoke_intake(refresher, connection=connection, repo=repo)
    refreshed_epic = epic_loader(
        connection=connection,
        repo=repo,
        epic_issue_number=epic_issue_number,
    )
    story_count = int(refreshed_epic.get("epic_story_count") or 0)
    if story_count <= 0:
        repository.set_program_epic_execution_status(
            repo=repo,
            issue_number=epic_issue_number,
            execution_status="blocked",
        )
        return EpicDecompositionResult(
            epic_issue_number=epic_issue_number,
            final_execution_status="blocked",
            projectable_story_count=0,
            summary="decomposer finished but no projectable stories were created",
        )

    active_story_count = int(refreshed_epic.get("active_story_count") or 0)
    if active_story_count <= 0:
        repository.set_program_epic_execution_status(
            repo=repo,
            issue_number=epic_issue_number,
            execution_status="needs_story_refinement",
        )
        return EpicDecompositionResult(
            epic_issue_number=epic_issue_number,
            final_execution_status="needs_story_refinement",
            projectable_story_count=story_count,
            summary=(
                "decomposer created stories but none are active after refresh; "
                "epic needs refinement before activation"
            ),
        )

    repository.set_program_epic_execution_status(
        repo=repo,
        issue_number=epic_issue_number,
        execution_status="active",
    )
    return EpicDecompositionResult(
        epic_issue_number=epic_issue_number,
        final_execution_status="active",
        projectable_story_count=story_count,
        summary=execution.summary,
    )


def load_decomposition_epic(
    *,
    connection: Any,
    repo: str,
    epic_issue_number: int,
) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                e.issue_number AS epic_issue_number,
                e.title AS epic_title,
                e.execution_status,
                e.lane AS epic_lane,
                COALESCE(story_counts.epic_story_count, 0) AS epic_story_count,
                COALESCE(story_counts.active_story_count, 0) AS active_story_count,
                COALESCE(story_counts.decomposing_story_count, 0) AS decomposing_story_count,
                gin.body AS epic_body
            FROM program_epic e
            LEFT JOIN (
                SELECT
                    repo,
                    epic_issue_number,
                    COUNT(*) AS epic_story_count,
                    COUNT(*) FILTER (WHERE execution_status = 'active') AS active_story_count,
                    COUNT(*) FILTER (WHERE execution_status = 'decomposing') AS decomposing_story_count
                FROM program_story
                WHERE epic_issue_number IS NOT NULL
                GROUP BY repo, epic_issue_number
            ) story_counts
              ON story_counts.repo = e.repo
             AND story_counts.epic_issue_number = e.issue_number
            LEFT JOIN github_issue_normalized gin
              ON gin.repo = e.repo
             AND gin.issue_number = e.issue_number
            WHERE e.repo = %s
              AND e.issue_number = %s
            """,
            (repo, epic_issue_number),
        )
        row = cursor.fetchone()
    if row is None:
        raise KeyError(epic_issue_number)
    return dict(row)


def run_shell_epic_decomposer(
    *,
    repo: str,
    epic_issue_number: int,
    epic: dict[str, Any],
    workdir: Path,
    decomposer_command: str | None,
) -> DecompositionExecutionResult:
    command_template = (decomposer_command or "").strip()
    if not command_template:
        return DecompositionExecutionResult(
            success=False,
            outcome="blocked",
            summary="TASKPLANE_EPIC_DECOMPOSER_COMMAND is required",
            reason_code="missing-decomposer-command",
        )

    timeout_seconds = _load_timeout_seconds()
    env = {
        **os.environ,
        "TASKPLANE_EPIC_ISSUE_NUMBER": str(epic_issue_number),
        "TASKPLANE_EPIC_REPO": repo,
        "TASKPLANE_PROJECT_DIR": str(workdir),
    }
    try:
        completed = _run_decomposer_subprocess(
            command_template=command_template,
            project_dir=workdir,
            env=env,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return DecompositionExecutionResult(
            success=False,
            outcome="blocked",
            summary=f"decomposer exceeded timeout after {timeout_seconds} seconds",
            reason_code="timeout",
        )

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
    return DecompositionExecutionResult(
        success=True,
        outcome=str(payload.get("outcome") or ""),
        summary=str(payload.get("summary") or "epic decomposition completed").strip(),
        reason_code=payload.get("reason_code"),
    )


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
        if isinstance(parsed, dict) and parsed.get("outcome") is not None:
            return parsed
    return {}


def _load_timeout_seconds() -> int:
    raw_value = os.environ.get("TASKPLANE_OPENCODE_TIMEOUT_SECONDS", "600").strip()
    try:
        value = int(raw_value)
    except ValueError:
        return 600
    return value if value > 0 else 600
