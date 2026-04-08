from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .adapters import build_task_executor, build_task_verifier
from .cli import DEFAULT_VERIFIER_COMMAND, _default_executor
from .factory import build_postgres_repository
from .git_committer import build_git_committer, build_git_story_integrator
from .models import ExecutionGuardrailContext, VerificationEvidence, WorkItem
from .settings import load_postgres_settings_from_env
from .settings import load_taskplane_config, TaskplaneConfig
from .cli import _executor_name_to_command
from .story_runner import load_story_work_item_ids, run_story_until_settled
from .worker import ExecutionResult
from .workspace import WorkspaceManager


def main(
    argv: Sequence[str] | None = None,
    *,
    config_loader: Callable[[], TaskplaneConfig] = load_taskplane_config,
    repository_builder: Callable[..., Any] = build_postgres_repository,
    story_loader: Callable[..., list[str]] = load_story_work_item_ids,
    story_runner: Callable[..., Any] = run_story_until_settled,
    executor_builder: Callable[
        ..., Callable[[WorkItem], ExecutionResult]
    ] = build_task_executor,
    verifier_builder: Callable[
        ..., Callable[[WorkItem], VerificationEvidence]
    ] = build_task_verifier,
    story_verifier_builder: Callable[..., object] = build_task_verifier,
    committer_builder: Callable[..., object] = build_git_committer,
    story_integrator_builder: Callable[..., object] = build_git_story_integrator,
    session_runtime_builder: Callable[[str], tuple[Any, Any] | None] | None = None,
    execution_job_finalizer: Callable[..., None] | None = None,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    config = config_loader()
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)
    runtime_builder = session_runtime_builder or _build_postgres_session_runtime
    runtime_components = runtime_builder(settings.dsn)
    session_manager = None
    wakeup_dispatcher = None
    if runtime_components is not None:
        session_manager, wakeup_dispatcher = runtime_components
    context = ExecutionGuardrailContext(
        allowed_waves=set(args.allowed_wave),
        frozen_prefixes=tuple(args.frozen_prefix) or ("docs/authority/",),
    )
    workdir = Path(args.workdir).resolve()
    resolved_repo = str(args.repo or "").strip() or _resolve_repo_for_story_workdir(
        config=config,
        workdir=workdir,
    )
    workspace_manager = None
    if args.worktree_root:
        workspace_manager = WorkspaceManager(
            repo_root=workdir,
            worktree_root=Path(args.worktree_root).resolve(),
        )
    executor = _default_executor
    resolved_executor_command = (
        args.executor_command
        or _resolve_story_default_executor_command(
            config=config,
            repo=resolved_repo,
        )
    )
    if resolved_executor_command:
        executor = executor_builder(
            command_template=resolved_executor_command,
            workdir=workdir,
            dsn=settings.dsn,
        )
    verifier_command = args.verifier_command or DEFAULT_VERIFIER_COMMAND
    verifier = verifier_builder(
        command_template=verifier_command,
        workdir=workdir,
        check_type=args.verifier_check_type,
    )
    committer = committer_builder(workdir=workdir)
    story_verifier = None
    if args.story_verifier_command:
        story_verifier = story_verifier_builder(
            command_template=args.story_verifier_command,
            workdir=workdir,
            check_type=args.story_verifier_check_type,
        )
    story_integrator = None
    if args.worktree_root:
        ignored_dirty_path_prefixes = _relative_ignored_prefixes(
            repo_root=workdir,
            candidate_path=Path(args.worktree_root).resolve(),
        )
        promotion_repo_root = (
            Path(args.promotion_repo_root).resolve()
            if args.promotion_repo_root
            else None
        )
        story_integrator = story_integrator_builder(
            repo_root=workdir,
            ignored_dirty_path_prefixes=ignored_dirty_path_prefixes,
            promotion_repo_root=promotion_repo_root,
        )
    story_work_item_ids = story_loader(
        repository=repository,
        story_issue_number=args.story_issue_number,
        repo=resolved_repo or args.repo,
    )
    result = story_runner(
        story_issue_number=args.story_issue_number,
        story_work_item_ids=story_work_item_ids,
        repository=repository,
        context=context,
        worker_name=args.worker_name,
        executor=executor,
        verifier=verifier,
        story_verifier=story_verifier,
        committer=committer,
        story_integrator=story_integrator,
        workspace_manager=workspace_manager,
        session_manager=session_manager,
        wakeup_dispatcher=wakeup_dispatcher,
        dsn=settings.dsn,
    )
    if execution_job_finalizer is None:
        execution_job_finalizer = _finalize_execution_job
    if result.story_complete:
        print(f"story {args.story_issue_number} complete")
    else:
        merge_hint = (
            f" merge_blocked={result.merge_blocked_reason}"
            if result.merge_blocked_reason
            else ""
        )
        print(
            f"story {args.story_issue_number} incomplete; "
            f"blocked={len(result.blocked_work_item_ids)} "
            f"remaining={len(result.remaining_work_item_ids)}"
            f"{merge_hint}"
        )
    execution_job_pid = _load_execution_job_pid_from_env()
    if execution_job_finalizer is not None and execution_job_pid is not None:
        execution_job_finalizer(
            dsn=settings.dsn,
            repo=resolved_repo,
            story_issue_number=args.story_issue_number,
            worker_name=args.worker_name,
            pid=execution_job_pid,
            story_complete=result.story_complete,
            blocked_work_item_ids=list(result.blocked_work_item_ids),
        )
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskplane-story",
        description="Drain all projected work items under a story until completion or blockage.",
    )
    parser.add_argument("--story-issue-number", type=int, required=True)
    parser.add_argument("--repo")
    parser.add_argument("--worker-name", default="story-runner")
    parser.add_argument("--allowed-wave", action="append", default=[])
    parser.add_argument("--frozen-prefix", action="append", default=[])
    parser.add_argument("--workdir", default=".")
    parser.add_argument("--worktree-root")
    parser.add_argument("--promotion-repo-root")
    parser.add_argument("--executor-command")
    parser.add_argument("--verifier-command")
    parser.add_argument("--verifier-check-type", default="pytest")
    parser.add_argument("--story-verifier-command")
    parser.add_argument("--story-verifier-check-type", default="pytest")
    return parser


def _build_postgres_session_runtime(dsn: str) -> tuple[Any, Any] | None:
    try:
        import psycopg
        from psycopg.rows import dict_row

        from .session_manager_postgres import PostgresSessionManager
        from .wakeup_dispatcher import PostgresWakeupDispatcher

        connection = psycopg.connect(dsn, row_factory=dict_row)
        return (
            PostgresSessionManager(connection),
            PostgresWakeupDispatcher(connection),
        )
    except Exception:
        return None


def _relative_ignored_prefixes(
    *, repo_root: Path, candidate_path: Path
) -> tuple[str, ...]:
    try:
        relative = candidate_path.relative_to(repo_root)
    except ValueError:
        return ()
    relative_text = str(relative).strip()
    if not relative_text:
        return ()
    return (relative_text.rstrip("/") + "/",)


if __name__ == "__main__":
    entrypoint()


def _resolve_repo_for_story_workdir(
    *, config: TaskplaneConfig, workdir: Path
) -> str | None:
    normalized = str(workdir.resolve())
    for repo, mapped_workdir in config.console_repo_workdirs.items():
        if str(Path(mapped_workdir).resolve()) == normalized:
            return repo
    return None


def _resolve_story_default_executor_command(
    *, config: TaskplaneConfig, repo: str | None
) -> str | None:
    if not repo:
        return None
    executor_name = (config.workflow_repo_default_executor.get(repo) or "").strip()
    if not executor_name:
        return None
    return _executor_name_to_command(executor_name)


def _load_execution_job_pid_from_env() -> int | None:
    raw_pid = os.environ.get("TASKPLANE_EXECUTION_JOB_PID", "").strip()
    if not raw_pid:
        return None
    try:
        return int(raw_pid)
    except ValueError:
        return None


def _finalize_execution_job(
    *,
    dsn: str,
    repo: str,
    story_issue_number: int,
    worker_name: str,
    pid: int,
    story_complete: bool,
    blocked_work_item_ids: list[str],
) -> None:
    if not repo.strip():
        return

    final_status = "succeeded" if story_complete else "failed"
    exit_code = 0 if story_complete else 1

    try:
        import psycopg

        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE execution_job
                    SET status = %s,
                        exit_code = %s,
                        finished_at = NOW()
                    WHERE repo = %s
                      AND pid = %s
                      AND job_kind = 'story_worker'
                      AND story_issue_number = %s
                      AND worker_name = %s
                      AND status = 'running'
                    """,
                    (
                        final_status,
                        exit_code,
                        repo,
                        pid,
                        story_issue_number,
                        worker_name,
                    ),
                )
    except Exception:
        return
