"""
Scheduling loop for stardrifter-orchestration-mvp.

This module contains the main supervisor scheduling logic.
"""

from __future__ import annotations

from typing import Any

# Backward compatibility exports - these are needed for test monkeypatching
from .epic_runner import run_epic_iteration
from .epic_scheduler import select_story_batch
from .global_coordinator import GlobalCoordinator
from .job_launcher import (
    ManagedProcess,
    aggregate_story_paths,
    build_decomposition_command,
    build_epic_decomposition_command,
    build_story_command,
    insert_execution_job,
)
from .repository import PostgresControlPlaneRepository
from .schedulers.task_scheduler import scheduling_paths, paths_conflict_with_any


def run_supervisor_iteration(
    *,
    connection: Any,
    repo: str,
    dsn: str,
    project_dir: Any,
    log_dir: Any,
    worktree_root: Any | None,
    promotion_repo_root: Any | None = None,
    max_parallel_jobs: int,
    epic_story_batch_size: int = 1,
    launcher=None,
    running_processes: dict[int, ManagedProcess] | None = None,
    pid_exists=None,
    global_coordinator: GlobalCoordinator | None = None,
    session_manager: Any | None = None,
    wakeup_dispatcher: Any | None = None,
) -> int:
    """
    Run supervisor iteration with optional global coordination support.

    Args:
        connection: Database connection
        repo: Repository name
        dsn: Database connection string
        project_dir: Project directory path
        log_dir: Log directory path
        worktree_root: Optional worktree root directory
        promotion_repo_root: Optional promotion repository root
        max_parallel_jobs: Maximum number of parallel jobs
        epic_story_batch_size: Batch size for epic story selection
        launcher: Function to launch managed processes
        running_processes: Dictionary of running processes
        pid_exists: Function to check if PID exists
        global_coordinator: Optional GlobalCoordinator for multi-repo orchestration

    Returns:
        Number of jobs launched
    """
    from .process_manager import reconcile_finished_jobs
    from .repository import PostgresControlPlaneRepository

    running_processes = running_processes or {}
    repository = PostgresControlPlaneRepository(connection)
    repository.sync_ready_states()

    reconcile_finished_jobs(
        connection=connection,
        repo=repo,
        running_processes=running_processes,
        pid_exists_fn=pid_exists or _pid_exists,
        global_coordinator=global_coordinator,
    )

    if session_manager is not None and wakeup_dispatcher is not None:
        from .session_runtime_loop import process_session_wakeups

        process_session_wakeups(
            session_manager=session_manager,
            wakeup_dispatcher=wakeup_dispatcher,
        )

    running_jobs = _load_running_jobs(connection=connection, repo=repo)
    running_story_issue_numbers = {
        row["story_issue_number"]
        for row in running_jobs
        if row.get("story_issue_number") is not None
        and str(row.get("job_kind") or "") != "epic_decomposition"
    }
    running_epic_issue_numbers = {
        row["story_issue_number"]
        for row in running_jobs
        if row.get("story_issue_number") is not None
        and str(row.get("job_kind") or "") == "epic_decomposition"
    }

    # If global coordinator is enabled, check for global capacity
    if global_coordinator is not None:
        global_coordinator.update_heartbeat(repo)
        remaining_capacity = max(0, max_parallel_jobs - len(running_jobs))
    else:
        remaining_capacity = max(0, max_parallel_jobs - len(running_jobs))

    if remaining_capacity <= 0:
        return 0

    launched = 0
    running_claim_paths = _load_active_claim_paths(connection=connection, repo=repo)

    # Launch epic decomposition jobs
    for row in _load_epic_decomposition_candidates(connection=connection, repo=repo):
        epic_issue_number = row["epic_issue_number"]
        if (
            epic_issue_number in running_epic_issue_numbers
            or launched >= remaining_capacity
        ):
            continue
        if global_coordinator is not None and not global_coordinator.acquire_agent_slot(
            repo
        ):
            continue

        command = build_epic_decomposition_command(
            dsn=dsn,
            repo=repo,
            epic_issue_number=epic_issue_number,
            project_dir=project_dir,
        )
        log_path = log_dir / f"epic-{epic_issue_number}-decomposition.log"
        process = launcher(command, log_path)

        insert_execution_job(
            connection=connection,
            repo=repo,
            job_kind="epic_decomposition",
            story_issue_number=epic_issue_number,
            work_id=None,
            worker_name=f"supervisor-epic-{epic_issue_number}",
            pid=process.pid,
            command=command,
            log_path=str(log_path),
        )

        running_processes[process.pid] = process
        running_epic_issue_numbers.add(epic_issue_number)
        launched += 1

    if launched >= remaining_capacity:
        return launched

    # Launch story decomposition jobs
    for row in _load_decomposition_candidates(connection=connection, repo=repo):
        story_issue_number = row["story_issue_number"]
        if (
            story_issue_number in running_story_issue_numbers
            or launched >= remaining_capacity
        ):
            continue
        if global_coordinator is not None and not global_coordinator.acquire_agent_slot(
            repo
        ):
            continue

        command = build_decomposition_command(
            dsn=dsn,
            repo=repo,
            story_issue_number=story_issue_number,
            project_dir=project_dir,
        )
        log_path = log_dir / f"story-{story_issue_number}-decomposition.log"
        process = launcher(command, log_path)

        insert_execution_job(
            connection=connection,
            repo=repo,
            job_kind="story_decomposition",
            story_issue_number=story_issue_number,
            work_id=None,
            worker_name=f"supervisor-story-{story_issue_number}",
            pid=process.pid,
            command=command,
            log_path=str(log_path),
        )

        running_processes[process.pid] = process
        running_story_issue_numbers.add(story_issue_number)
        launched += 1

    if launched >= remaining_capacity:
        return launched

    # Select and launch story execution jobs via epic iteration
    selected_story_issue_numbers, epic_issue_by_story_issue_number = (
        _select_story_candidates_via_epic_iteration(
            connection=connection,
            repo=repo,
            repository=repository,
            running_story_issue_numbers=running_story_issue_numbers,
            available_capacity=remaining_capacity - launched,
            epic_story_batch_size=epic_story_batch_size,
        )
    )
    story_wave_by_issue_number = _load_story_allowed_waves(
        repository=repository,
        repo=repo,
        story_issue_numbers=selected_story_issue_numbers,
        epic_issue_by_story_issue_number=epic_issue_by_story_issue_number,
    )

    if not selected_story_issue_numbers:
        story_completion_candidates = _load_story_completion_candidates(
            connection=connection,
            repo=repo,
        )
        epic_issue_by_story_issue_number = {
            int(row["story_issue_number"]): int(row["epic_issue_number"])
            for row in story_completion_candidates
            if row.get("story_issue_number") is not None
            and row.get("epic_issue_number") is not None
        }
        selected_story_issue_numbers = _select_story_completion_candidates(
            repo=repo,
            repository=repository,
            story_completion_candidates=story_completion_candidates,
            running_story_issue_numbers=running_story_issue_numbers,
            available_capacity=remaining_capacity - launched,
            epic_story_batch_size=epic_story_batch_size,
        )
        story_wave_by_issue_number = _load_story_allowed_waves(
            repository=repository,
            repo=repo,
            story_issue_numbers=selected_story_issue_numbers,
            epic_issue_by_story_issue_number=epic_issue_by_story_issue_number,
        )

    for story_issue_number in selected_story_issue_numbers:
        if global_coordinator is not None and not global_coordinator.acquire_agent_slot(
            repo
        ):
            continue

        command = build_story_command(
            dsn=dsn,
            story_issue_number=story_issue_number,
            allowed_waves=story_wave_by_issue_number.get(story_issue_number, ()),
            project_dir=project_dir,
            worktree_root=worktree_root,
            promotion_repo_root=promotion_repo_root,
        )
        log_path = log_dir / f"story-{story_issue_number}.log"
        process = launcher(command, log_path)

        insert_execution_job(
            connection=connection,
            repo=repo,
            job_kind="story_worker",
            story_issue_number=story_issue_number,
            parent_epic_issue_number=epic_issue_by_story_issue_number.get(
                story_issue_number
            ),
            work_id=None,
            launch_backend="supervisor",
            worker_name=f"supervisor-story-{story_issue_number}",
            pid=process.pid,
            command=command,
            log_path=str(log_path),
        )

        running_processes[process.pid] = process
        running_story_issue_numbers.add(story_issue_number)
        launched += 1

    if launched >= remaining_capacity:
        return launched

    # Launch task execution jobs
    task_candidates = _load_task_candidates(connection=connection, repo=repo)
    story_paths_by_issue = aggregate_story_paths(task_candidates)
    selected_tasks = _select_task_candidates(
        candidates=task_candidates,
        dependencies=_load_task_dependencies(connection=connection, repo=repo),
        occupied_paths=running_claim_paths,
        max_parallel=remaining_capacity - launched,
    )

    selected_paths: list[str] = []
    for row in selected_tasks:
        story_issue_number = row.get("canonical_story_issue_number")
        if story_issue_number is None or launched >= remaining_capacity:
            continue
        if story_issue_number in running_story_issue_numbers:
            continue

        story_paths = story_paths_by_issue.get(
            story_issue_number,
            scheduling_paths(row.get("planned_paths") or []),
        )
        if paths_conflict_with_any(story_paths, selected_paths):
            continue

        command = build_story_command(
            dsn=dsn,
            story_issue_number=story_issue_number,
            allowed_waves=story_wave_by_issue_number.get(story_issue_number, ()),
            project_dir=project_dir,
            worktree_root=worktree_root,
            promotion_repo_root=promotion_repo_root,
        )
        log_path = log_dir / f"story-{story_issue_number}.log"
        process = launcher(command, log_path)

        insert_execution_job(
            connection=connection,
            repo=repo,
            job_kind="story_worker",
            story_issue_number=story_issue_number,
            work_id=None,
            worker_name=f"supervisor-story-{story_issue_number}",
            pid=process.pid,
            command=command,
            log_path=str(log_path),
        )

        running_processes[process.pid] = process
        running_story_issue_numbers.add(story_issue_number)
        selected_paths.extend(story_paths)
        launched += 1

    return launched


# =============================================================================
# Data Loading Functions
# =============================================================================


def _load_running_jobs(*, connection: Any, repo: str) -> list[dict[str, Any]]:
    """Load running jobs from database."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, pid, job_kind, story_issue_number, work_id, status
            FROM execution_job
            WHERE repo = %s
              AND status = 'running'
            ORDER BY id
            """,
            (repo,),
        )
        return list(cursor.fetchall())


def _load_decomposition_candidates(
    *, connection: Any, repo: str
) -> list[dict[str, Any]]:
    """Load story decomposition candidates."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT story_issue_number
            FROM v_story_decomposition_queue
            WHERE repo = %s
            ORDER BY story_issue_number
            """,
            (repo,),
        )
        return list(cursor.fetchall())


def _load_epic_decomposition_candidates(
    *, connection: Any, repo: str
) -> list[dict[str, Any]]:
    """Load epic decomposition candidates."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT epic_issue_number
            FROM v_epic_decomposition_queue
            WHERE repo = %s
            ORDER BY epic_issue_number
            """,
            (repo,),
        )
        return list(cursor.fetchall())


def _load_task_candidates(*, connection: Any, repo: str) -> list[dict[str, Any]]:
    """Load task candidates."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                id AS work_id,
                canonical_story_issue_number,
                source_issue_number,
                task_type,
                blocking_mode,
                status,
                COALESCE(dod_json->'planned_paths', '[]'::jsonb) AS planned_paths
            FROM v_active_task_queue
            WHERE repo = %s
              AND status IN ('ready', 'pending')
            """,
            (repo,),
        )
        return list(cursor.fetchall())


def _load_story_completion_candidates(
    *, connection: Any, repo: str
) -> list[dict[str, Any]]:
    """Load story completion candidates."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                ps.issue_number AS story_issue_number,
                ps.epic_issue_number
            FROM program_story ps
            WHERE ps.repo = %s
              AND ps.execution_status NOT IN ('done', 'gated')
              AND EXISTS (
                  SELECT 1
                  FROM work_item wi
                  WHERE wi.repo = ps.repo
                    AND wi.canonical_story_issue_number = ps.issue_number
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM work_item wi
                  WHERE wi.repo = ps.repo
                    AND wi.canonical_story_issue_number = ps.issue_number
                    AND wi.status NOT IN ('done', 'blocked')
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM work_item wi
                  WHERE wi.repo = ps.repo
                    AND wi.canonical_story_issue_number = ps.issue_number
                    AND wi.status = 'blocked'
              )
            ORDER BY ps.issue_number
            """,
            (repo,),
        )
        return list(cursor.fetchall())


def _load_task_dependencies(*, connection: Any, repo: str) -> list[dict[str, Any]]:
    """Load task dependencies."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                wd.work_id,
                wd.depends_on_work_id,
                dep.status AS dependency_status,
                dep.blocking_mode AS dependency_blocking_mode
            FROM work_dependency wd
            JOIN work_item wi
              ON wi.id = wd.work_id
            JOIN work_item dep
              ON dep.id = wd.depends_on_work_id
            WHERE wi.repo = %s
            ORDER BY wd.work_id, wd.depends_on_work_id
            """,
            (repo,),
        )
        return list(cursor.fetchall())


def _load_active_claim_paths(*, connection: Any, repo: str) -> list[str]:
    """Load active claim paths."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT wc.claimed_paths
            FROM work_claim wc
            JOIN work_item wi
              ON wi.id = wc.work_id
            WHERE wi.repo = %s
              AND (wc.lease_expires_at IS NULL OR wc.lease_expires_at > NOW())
            """,
            (repo,),
        )
        rows = cursor.fetchall()

    occupied: list[str] = []
    for row in rows:
        occupied.extend(scheduling_paths(row.get("claimed_paths") or []))
    return occupied


# =============================================================================
# Story Selection Functions
# =============================================================================


def _select_story_candidates_via_epic_iteration(
    *,
    connection: Any,
    repo: str,
    repository,
    running_story_issue_numbers: set[int],
    available_capacity: int,
    epic_story_batch_size: int = 1,
    epic_iteration_runner=None,
) -> tuple[list[int], dict[int, int]]:
    """Select story candidates via epic iteration."""
    from .schedulers.story_scheduler import (
        select_story_candidates_via_epic_iteration as scheduler_select,
    )

    return scheduler_select(
        connection=connection,
        repo=repo,
        repository=repository,
        running_story_issue_numbers=running_story_issue_numbers,
        available_capacity=available_capacity,
        epic_story_batch_size=epic_story_batch_size,
        epic_iteration_runner=epic_iteration_runner,
    )


def _select_story_completion_candidates(
    *,
    repo: str,
    repository,
    story_completion_candidates: list[dict[str, Any]],
    running_story_issue_numbers: set[int],
    available_capacity: int,
    epic_story_batch_size: int = 1,
) -> list[int]:
    """Select story completion candidates."""
    from .schedulers.story_scheduler import (
        select_story_completion_candidates as scheduler_select,
    )

    return scheduler_select(
        repo=repo,
        repository=repository,
        story_completion_candidates=story_completion_candidates,
        running_story_issue_numbers=running_story_issue_numbers,
        available_capacity=available_capacity,
        epic_story_batch_size=epic_story_batch_size,
    )


def _load_story_allowed_waves(
    *,
    repository,
    repo: str,
    story_issue_numbers: list[int],
    epic_issue_by_story_issue_number: dict[int, int],
) -> dict[int, tuple[str, ...]]:
    story_wave_by_issue_number: dict[int, tuple[str, ...]] = {}
    if not story_issue_numbers:
        return story_wave_by_issue_number

    stories_by_epic: dict[int, list[Any]] = {}
    for epic_issue_number in sorted(set(epic_issue_by_story_issue_number.values())):
        stories_by_epic[epic_issue_number] = repository.list_program_stories_for_epic(
            repo=repo,
            epic_issue_number=epic_issue_number,
        )

    for story_issue_number in story_issue_numbers:
        epic_issue_number = epic_issue_by_story_issue_number.get(story_issue_number)
        if epic_issue_number is None:
            continue
        story = next(
            (
                candidate
                for candidate in stories_by_epic.get(epic_issue_number, [])
                if getattr(candidate, "issue_number", None) == story_issue_number
            ),
            None,
        )
        active_wave = getattr(story, "active_wave", None) if story is not None else None
        if active_wave:
            story_wave_by_issue_number[story_issue_number] = (str(active_wave),)

    return story_wave_by_issue_number


# =============================================================================
# Task Selection Functions
# =============================================================================


def _select_task_candidates(
    *,
    candidates: list[dict[str, Any]],
    dependencies: list[dict[str, Any]],
    occupied_paths: list[str],
    max_parallel: int = 4,
) -> list[dict[str, Any]]:
    """Select task candidates with dependency and conflict resolution."""
    from .schedulers.task_scheduler import select_task_candidates

    return select_task_candidates(
        candidates=candidates,
        dependencies=dependencies,
        occupied_paths=occupied_paths,
        max_parallel=max_parallel,
    )


# =============================================================================
# Helper Functions
# =============================================================================


def _pid_exists(pid: int) -> bool:
    """Check if a process exists."""
    from .process_manager import pid_exists

    return pid_exists(pid)


def _derive_terminal_state_for_job(
    *,
    connection: Any,
    row: dict[str, Any],
) -> tuple[int | None, str]:
    """Derive terminal state for a finished job."""
    job_kind = str(row.get("job_kind") or "")
    work_id = row.get("work_id")
    story_issue_number = row.get("story_issue_number")

    with connection.cursor() as cursor:
        if job_kind == "task_worker" and work_id is not None:
            cursor.execute(
                """
                SELECT status
                FROM work_item
                WHERE id = %s
                """,
                (work_id,),
            )
            current = cursor.fetchone()
            status = str((current or {}).get("status") or "")
            if status == "done":
                return 0, "succeeded"
            if status == "blocked":
                return 1, "failed"

        if job_kind == "story_worker" and story_issue_number is not None:
            cursor.execute(
                """
                SELECT status
                FROM work_item
                WHERE canonical_story_issue_number = %s
                """,
                (story_issue_number,),
            )
            statuses = [str(candidate["status"]) for candidate in cursor.fetchall()]
            if statuses and all(status == "done" for status in statuses):
                return 0, "succeeded"
            if any(status == "blocked" for status in statuses):
                return 1, "failed"

        if job_kind == "story_decomposition" and story_issue_number is not None:
            cursor.execute(
                """
                SELECT execution_status
                FROM program_story
                WHERE issue_number = %s
                """,
                (story_issue_number,),
            )
            current = cursor.fetchone()
            status = str((current or {}).get("execution_status") or "")
            if status == "active":
                return 0, "succeeded"
            if status in {"blocked", "needs_story_refinement"}:
                return 1, "failed"

        if job_kind == "epic_decomposition" and story_issue_number is not None:
            cursor.execute(
                """
                SELECT execution_status
                FROM program_epic
                WHERE issue_number = %s
                """,
                (story_issue_number,),
            )
            current = cursor.fetchone()
            status = str((current or {}).get("execution_status") or "")
            if status == "active":
                return 0, "succeeded"
            if status in {"blocked", "needs_story_refinement"}:
                return 1, "failed"

    return 1, "failed"
