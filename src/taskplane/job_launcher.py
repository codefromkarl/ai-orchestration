"""
Job launcher and command building utilities.

This module handles:
- Building command strings for different job types
- Process launching and management
- Execution job insertion
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
from pathlib import Path
from typing import Any, Protocol


class ManagedProcess(Protocol):
    """Protocol for a managed subprocess."""

    pid: int

    def poll(self) -> int | None:
        """Check if the process has completed."""
        ...


def build_decomposition_command(
    *,
    dsn: str,
    repo: str,
    story_issue_number: int,
    project_dir: Path,
) -> str:
    """
    Build command for story decomposition.

    Args:
        dsn: Database connection string
        repo: Repository name
        story_issue_number: Story issue number to decompose
        project_dir: Project directory

    Returns:
        Shell command string
    """
    return (
        f"export TASKPLANE_DSN={shlex.quote(dsn)}; "
        "export TASKPLANE_OPENCODE_TIMEOUT_SECONDS=180; "
        "unset GITHUB_TOKEN; "
        "python3 -m taskplane.story_decomposition_cli "
        f"--repo {shlex.quote(repo)} "
        f"--story-issue-number {story_issue_number} "
        f"--workdir {shlex.quote(str(project_dir))} "
        "--decomposer-command "
        f"{shlex.quote('python3 -m taskplane.opencode_story_decomposer')}"
    )


def build_epic_decomposition_command(
    *,
    dsn: str,
    repo: str,
    epic_issue_number: int,
    project_dir: Path,
) -> str:
    """
    Build command for epic decomposition.

    Args:
        dsn: Database connection string
        repo: Repository name
        epic_issue_number: Epic issue number to decompose
        project_dir: Project directory

    Returns:
        Shell command string
    """
    return (
        f"export TASKPLANE_DSN={shlex.quote(dsn)}; "
        "export TASKPLANE_OPENCODE_TIMEOUT_SECONDS=180; "
        "unset GITHUB_TOKEN; "
        "python3 -m taskplane.epic_decomposition_cli "
        f"--repo {shlex.quote(repo)} "
        f"--epic-issue-number {epic_issue_number} "
        f"--workdir {shlex.quote(str(project_dir))} "
        "--decomposer-command "
        f"{shlex.quote('python3 -m taskplane.opencode_epic_decomposer')}"
    )


def build_story_command(
    *,
    dsn: str,
    repo: str | None = None,
    story_issue_number: int,
    allowed_waves: tuple[str, ...] = (),
    project_dir: Path,
    worktree_root: Path | None,
    promotion_repo_root: Path | None,
    executor_command: str | None = None,
    verifier_command: str | None = None,
    force_shell_executor: bool | None = None,
) -> str:
    """
    Build command for story execution.

    Args:
        dsn: Database connection string
        story_issue_number: Story issue number to execute
        project_dir: Project directory
        worktree_root: Optional worktree root directory
        promotion_repo_root: Optional promotion repository root

    Returns:
        Shell command string
    """
    normalized_allowed_waves = tuple(
        wave for wave in allowed_waves if isinstance(wave, str) and wave.strip()
    ) or (
        "unassigned",
        "Wave0",
        "1",
        "2",
        "3",
        "wave-1",
        "wave-2",
        "wave-3",
        "wave-4",
        "Wave-INT",
        "wave-int",
    )

    resolved_executor_command = (
        executor_command
        if executor_command is not None
        else (
            os.environ.get("TASKPLANE_STORY_EXECUTOR_COMMAND")
            or "python3 -m taskplane.codex_task_executor"
        )
    ).strip()
    resolved_verifier_command = (
        verifier_command
        if verifier_command is not None
        else (
            os.environ.get("TASKPLANE_STORY_VERIFIER_COMMAND")
            or "python3 -m taskplane.task_verifier"
        )
    ).strip()
    resolved_force_shell_executor = (
        force_shell_executor
        if force_shell_executor is not None
        else os.environ.get("TASKPLANE_STORY_FORCE_SHELL_EXECUTOR", "").strip().lower()
        in {"1", "true", "yes"}
    )

    env_prefix = (
        f"export TASKPLANE_DSN={shlex.quote(dsn)}; "
        "export TASKPLANE_EXECUTION_JOB_PID=$$; "
        "export TASKPLANE_OPENCODE_TIMEOUT_SECONDS=1800; "
        "export TASKPLANE_CODEX_TIMEOUT_SECONDS=1800; "
        "unset GITHUB_TOKEN; "
    )
    if resolved_force_shell_executor:
        env_prefix += "export TASKPLANE_FORCE_SHELL_EXECUTOR=1; "

    command = (
        env_prefix + "python3 -m taskplane.story_runner_cli "
        f"--story-issue-number {story_issue_number} "
        f"--worker-name {shlex.quote(f'supervisor-story-{story_issue_number}')} "
        f"--workdir {shlex.quote(str(project_dir))} "
    )
    if repo is not None and repo.strip():
        command += f"--repo {shlex.quote(repo.strip())} "

    for wave in normalized_allowed_waves:
        command += f"--allowed-wave {shlex.quote(wave)} "

    if worktree_root is not None:
        command += f"--worktree-root {shlex.quote(str(worktree_root))} "

    if promotion_repo_root is not None:
        command += f"--promotion-repo-root {shlex.quote(str(promotion_repo_root))} "

    command += (
        "--executor-command "
        f"{shlex.quote(resolved_executor_command)} "
        "--verifier-command "
        f"{shlex.quote(resolved_verifier_command)}"
    )

    return command


def insert_execution_job(
    *,
    connection: Any,
    repo: str,
    job_kind: str,
    story_issue_number: int | None,
    parent_epic_issue_number: int | None = None,
    work_id: str | None,
    launch_backend: str | None = None,
    worker_name: str,
    pid: int,
    command: str,
    log_path: str,
    orchestrator_session_id: str | None = None,
) -> None:
    """
    Insert a new execution job record.

    Args:
        connection: Database connection
        repo: Repository name
        job_kind: Type of job
        story_issue_number: Associated story issue number
        parent_epic_issue_number: Parent epic issue number
        work_id: Associated work item ID
        launch_backend: Backend that launched this job
        worker_name: Name of the worker
        pid: Process ID
        command: Command being executed
        log_path: Path to log file
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO execution_job (
                repo,
                job_kind,
                status,
                story_issue_number,
                parent_epic_issue_number,
                launch_backend,
                work_id,
                worker_name,
                pid,
                command,
                log_path,
                orchestrator_session_id
            )
            VALUES (%s, %s, 'running', %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                repo,
                job_kind,
                story_issue_number,
                parent_epic_issue_number,
                launch_backend,
                work_id,
                worker_name,
                pid,
                command,
                log_path,
                orchestrator_session_id,
            ),
        )
    connection.commit()


def launch_managed_process(command: str, log_path: Path) -> ManagedProcess:
    """
    Launch a managed subprocess.

    Args:
        command: Shell command to execute
        log_path: Path to write stdout/stderr

    Returns:
        ManagedProcess instance
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8")

    return subprocess.Popen(
        ["bash", "-lc", command],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
        text=True,
    )


def terminate_process_group(pid: int) -> None:
    """Terminate a process group."""
    os.killpg(pid, signal.SIGTERM)


def pid_exists(pid: int) -> bool:
    """
    Check if a process exists.

    Handles zombie processes correctly.

    Args:
        pid: Process ID to check

    Returns:
        True if process exists and is not a zombie
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

    # Check if it's a zombie
    status_path = Path(f"/proc/{pid}/status")
    try:
        status_text = status_path.read_text()
    except OSError:
        return True

    for line in status_text.splitlines():
        if not line.startswith("State:"):
            continue
        if "\tZ" in line or "(zombie)" in line:
            return False
        break

    return True


def aggregate_story_paths(
    candidates: list[dict[str, Any]],
) -> dict[int, list[str]]:
    """
    Aggregate planned paths grouped by story issue number.

    Args:
        candidates: List of task candidate rows

    Returns:
        Dictionary mapping story issue numbers to path lists
    """
    story_paths: dict[int, list[str]] = {}

    for row in candidates:
        story_issue_number = row.get("canonical_story_issue_number")
        if story_issue_number is None:
            continue

        paths = story_paths.setdefault(story_issue_number, [])

        for candidate_path in _scheduling_paths(row.get("planned_paths") or []):
            if candidate_path not in paths:
                paths.append(candidate_path)

    return story_paths


def _scheduling_paths(raw_paths: list[str]) -> list[str]:
    """
    Normalize paths for scheduling purposes.

    - Strips whitespace and trailing slashes
    - Truncates at wildcard patterns
    - Filters empty paths

    Args:
        raw_paths: Raw path strings

    Returns:
        List of normalized paths
    """
    normalized: list[str] = []

    for raw_path in raw_paths:
        path = str(raw_path or "").strip().rstrip("/")
        if not path:
            continue
        if "*" in path:
            path = path.split("*", 1)[0].rstrip("/")
        normalized.append(path)

    return [path for path in normalized if path]
