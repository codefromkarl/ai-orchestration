from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import shutil
import time
from typing import Any, Callable, Sequence

import psycopg
from psycopg.rows import dict_row

from .models import ExecutionGuardrailContext, VerificationEvidence
from .repository.postgres import PostgresControlPlaneRepository
from .session_manager_postgres import PostgresSessionManager
from .session_runtime_loop import fire_wakeup_for_event
from .supervisor_cli import main as supervisor_main
from .wakeup_dispatcher import PostgresWakeupDispatcher
from .worker import ExecutionResult, WorkerSessionRuntime, run_worker_cycle


@dataclass(frozen=True)
class LiveAcceptanceConfig:
    dsn: str
    repo: str
    project_dir: Path
    log_dir: Path
    worktree_root: Path
    story_issue_number: int
    work_id: str
    suppress_work_id: str | None
    allowed_waves: tuple[str, ...]
    executor_command: str
    verifier_command: str
    phase_wait_seconds: float
    reconcile_wait_seconds: float
    supervisor_passes: int
    story_force_shell_executor: bool
    run_log_dir: Path
    run_planned_path: str
    run_started_at: datetime


@dataclass(frozen=True)
class LiveAcceptanceResult:
    success: bool
    work_status: str
    session_status: str | None
    wakeup_status: str | None
    execution_job_status: str | None
    log_dir: Path
    planned_path: str
    details: dict[str, Any]


@dataclass(frozen=True)
class _WorkItemSnapshot:
    status: str
    blocked_reason: str | None
    decision_required: bool
    next_eligible_at: Any | None
    dod_json: dict[str, Any]


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Callable[[LiveAcceptanceConfig], LiveAcceptanceResult] | None = None,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    run_started_at = datetime.now(UTC)
    run_slug = _slugify(args.work_id)
    run_stamp = run_started_at.strftime("%Y%m%dT%H%M%SZ")
    run_log_dir = Path(args.log_dir).resolve() / f"live-acceptance-{run_slug}-{run_stamp}"
    run_planned_path = f"examples/taskplane-live-acceptance/{run_slug}-{run_stamp}.md"
    config = LiveAcceptanceConfig(
        dsn=args.dsn,
        repo=args.repo,
        project_dir=Path(args.project_dir).resolve(),
        log_dir=Path(args.log_dir).resolve(),
        worktree_root=Path(args.worktree_root).resolve(),
        story_issue_number=args.story_issue_number,
        work_id=args.work_id,
        suppress_work_id=args.suppress_work_id,
        allowed_waves=tuple(args.allowed_wave) or ("Wave0",),
        executor_command=args.executor_command or _default_final_executor_command(),
        verifier_command=args.verifier_command or "true",
        phase_wait_seconds=float(args.phase_wait_seconds),
        reconcile_wait_seconds=float(args.reconcile_wait_seconds),
        supervisor_passes=int(args.supervisor_passes),
        story_force_shell_executor=bool(args.story_force_shell_executor),
        run_log_dir=run_log_dir,
        run_planned_path=run_planned_path,
        run_started_at=run_started_at,
    )
    effective_runner = runner or run_live_acceptance
    result = effective_runner(config)
    print(
        f"success={str(result.success).lower()} "
        f"work_status={result.work_status} "
        f"session_status={result.session_status or 'none'} "
        f"wakeup_status={result.wakeup_status or 'none'} "
        f"execution_job_status={result.execution_job_status or 'none'} "
        f"log_dir={result.log_dir}"
    )
    return 0 if result.success else 1


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskplane-live-acceptance",
        description="Run a no-pollution live orchestration acceptance check against a real PostgreSQL backlog task.",
    )
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--worktree-root", required=True)
    parser.add_argument("--story-issue-number", type=int, required=True)
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--suppress-work-id")
    parser.add_argument("--allowed-wave", action="append", default=[])
    parser.add_argument("--executor-command")
    parser.add_argument("--verifier-command")
    parser.add_argument("--phase-wait-seconds", type=float, default=5.0)
    parser.add_argument("--reconcile-wait-seconds", type=float, default=2.0)
    parser.add_argument("--supervisor-passes", type=int, default=2)
    parser.add_argument(
        "--story-force-shell-executor",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    return parser


def _default_final_executor_command() -> str:
    payload = json.dumps(
        {
            "outcome": "already_satisfied",
            "summary": "live acceptance completed without repo mutation",
        },
        ensure_ascii=False,
    )
    return (
        "python3 - <<'PY'\n"
        f"print('TASKPLANE_EXECUTION_RESULT_JSON={payload}')\n"
        "PY"
    )


def run_live_acceptance(
    config: LiveAcceptanceConfig,
    *,
    connect_fn: Callable[..., Any] = psycopg.connect,
    supervisor_runner: Callable[..., int] = supervisor_main,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> LiveAcceptanceResult:
    target_snapshot: _WorkItemSnapshot | None = None
    suppress_snapshot: _WorkItemSnapshot | None = None
    original_story_status: str | None = None
    details: dict[str, Any] = {
        "repo": config.repo,
        "story_issue_number": config.story_issue_number,
        "work_id": config.work_id,
        "suppress_work_id": config.suppress_work_id,
    }
    try:
        target_snapshot, suppress_snapshot, original_story_status = _prepare_acceptance_state(
            config,
            connect_fn=connect_fn,
        )
        _create_wait_and_fire_wakeup(config, connect_fn=connect_fn)
        for pass_index in range(config.supervisor_passes):
            _run_supervisor_pass(
                config,
                supervisor_runner=supervisor_runner,
            )
            sleep_fn(
                config.phase_wait_seconds
                if pass_index == 0
                else config.reconcile_wait_seconds
            )
        result = _collect_result(config, connect_fn=connect_fn)
        details.update(result.details)
        return LiveAcceptanceResult(
            success=result.success,
            work_status=result.work_status,
            session_status=result.session_status,
            wakeup_status=result.wakeup_status,
            execution_job_status=result.execution_job_status,
            log_dir=result.log_dir,
            planned_path=result.planned_path,
            details=details,
        )
    finally:
        _restore_acceptance_state(
            config,
            target_snapshot=target_snapshot,
            suppress_snapshot=suppress_snapshot,
            original_story_status=original_story_status,
            connect_fn=connect_fn,
        )


def _prepare_acceptance_state(
    config: LiveAcceptanceConfig,
    *,
    connect_fn: Callable[..., Any],
) -> tuple[_WorkItemSnapshot, _WorkItemSnapshot | None, str]:
    with connect_fn(config.dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            target = _fetch_work_item_row(
                cur,
                repo=config.repo,
                work_id=config.work_id,
            )
            if target is None:
                raise RuntimeError(f"target work item not found: {config.work_id}")
            if int(target.get("canonical_story_issue_number") or 0) != config.story_issue_number:
                raise RuntimeError(
                    f"target {config.work_id} does not belong to story {config.story_issue_number}"
                )
            if _has_preexisting_runtime_state(cur, work_id=config.work_id):
                raise RuntimeError(
                    f"target {config.work_id} already has claims/session/linkage; choose a cleaner task"
                )
            cur.execute(
                """
                SELECT execution_status
                FROM program_story
                WHERE repo = %s AND issue_number = %s
                """,
                (config.repo, config.story_issue_number),
            )
            story_row = cur.fetchone()
            if story_row is None:
                raise RuntimeError(
                    f"program_story not found: {config.repo}#{config.story_issue_number}"
                )
            original_story_status = str(story_row.get("execution_status") or "")

            target_snapshot = _WorkItemSnapshot(
                status=str(target.get("status") or ""),
                blocked_reason=target.get("blocked_reason"),
                decision_required=bool(target.get("decision_required") or False),
                next_eligible_at=target.get("next_eligible_at"),
                dod_json=dict(target.get("dod_json") or {}),
            )

            suppress_snapshot = None
            if config.suppress_work_id:
                suppress = _fetch_work_item_row(
                    cur,
                    repo=config.repo,
                    work_id=config.suppress_work_id,
                )
                if suppress is None:
                    raise RuntimeError(
                        f"suppress work item not found: {config.suppress_work_id}"
                    )
                suppress_snapshot = _WorkItemSnapshot(
                    status=str(suppress.get("status") or ""),
                    blocked_reason=suppress.get("blocked_reason"),
                    decision_required=bool(suppress.get("decision_required") or False),
                    next_eligible_at=suppress.get("next_eligible_at"),
                    dod_json=dict(suppress.get("dod_json") or {}),
                )

            updated_dod = dict(target_snapshot.dod_json)
            updated_dod["planned_paths"] = [config.run_planned_path]
            cur.execute(
                """
                UPDATE work_item
                SET status = 'pending',
                    blocked_reason = NULL,
                    decision_required = FALSE,
                    next_eligible_at = NULL,
                    dod_json = %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    json.dumps(updated_dod, ensure_ascii=False),
                    config.work_id,
                ),
            )
            if config.suppress_work_id:
                cur.execute(
                    """
                    UPDATE work_item
                    SET status = 'blocked',
                        blocked_reason = 'suppressed-for-live-acceptance',
                        decision_required = FALSE,
                        next_eligible_at = NULL,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (config.suppress_work_id,),
                )
            cur.execute(
                """
                UPDATE program_story
                SET execution_status = 'active',
                    updated_at = NOW()
                WHERE repo = %s AND issue_number = %s
                """,
                (config.repo, config.story_issue_number),
            )
        conn.commit()
    return target_snapshot, suppress_snapshot, original_story_status


def _create_wait_and_fire_wakeup(
    config: LiveAcceptanceConfig,
    *,
    connect_fn: Callable[..., Any],
) -> None:
    repository_conn = connect_fn(config.dsn, row_factory=dict_row)
    runtime_conn = connect_fn(config.dsn, row_factory=dict_row)
    try:
        repository = PostgresControlPlaneRepository(repository_conn)
        session_manager = PostgresSessionManager(runtime_conn)
        wakeup_dispatcher = PostgresWakeupDispatcher(runtime_conn)
        runtime = WorkerSessionRuntime(
            session_manager=session_manager,
            wakeup_dispatcher=wakeup_dispatcher,
            allow_wait_suspension=True,
        )
        repository.sync_ready_states()
        context = ExecutionGuardrailContext(
            allowed_waves=set(config.allowed_waves),
            frozen_prefixes=("docs/authority/",),
        )
        result = run_worker_cycle(
            repository=repository,
            context=context,
            worker_name=f"live-acceptance-wait-{_slugify(config.work_id)}",
            executor=lambda work_item, workspace_path=None, execution_context=None: ExecutionResult(
                success=True,
                summary="live acceptance wait phase",
                result_payload_json={
                    "execution_kind": "wait",
                    "wait_type": "external_event",
                    "summary": "waiting for live acceptance wakeup",
                    "resume_hint": "resume after live acceptance wakeup",
                },
            ),
            verifier=lambda work_item, workspace_path=None, execution_context=None: VerificationEvidence(
                work_id=work_item.id,
                check_type="pytest",
                command="pytest -q",
                passed=True,
                output_digest="ok",
            ),
            work_item_ids=[config.work_id],
            session_runtime=runtime,
        )
        if result.claimed_work_id != config.work_id:
            raise RuntimeError(
                f"failed to claim target work item during wait phase: {config.work_id}"
            )
        sessions = session_manager.list_active_sessions_for_work(config.work_id)
        if not sessions:
            raise RuntimeError(
                f"wait phase did not create a session for {config.work_id}"
            )
        session_id = sessions[0].id
        fired = fire_wakeup_for_event(
            wakeup_dispatcher=wakeup_dispatcher,
            session_manager=session_manager,
            session_id=session_id,
            wake_type="external_event",
            event_data={"source": "taskplane.live_acceptance_cli"},
        )
        runtime_conn.commit()
        if not fired:
            raise RuntimeError(
                f"failed to fire wakeup for session {session_id}"
            )
    finally:
        repository_conn.close()
        runtime_conn.close()


def _run_supervisor_pass(
    config: LiveAcceptanceConfig,
    *,
    supervisor_runner: Callable[..., int],
) -> None:
    argv = [
        "--dsn",
        config.dsn,
        "--repo",
        config.repo,
        "--project-dir",
        str(config.project_dir),
        "--log-dir",
        str(config.run_log_dir),
        "--worktree-root",
        str(config.worktree_root),
        "--poll-interval",
        "1",
        "--max-parallel-jobs",
        "1",
        "--story-executor-command",
        config.executor_command,
        "--story-verifier-command",
        config.verifier_command,
    ]
    if config.story_force_shell_executor:
        argv.append("--story-force-shell-executor")
    supervisor_runner(argv, run_once=True)


def _collect_result(
    config: LiveAcceptanceConfig,
    *,
    connect_fn: Callable[..., Any],
) -> LiveAcceptanceResult:
    with connect_fn(config.dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, blocked_reason, decision_required
                FROM work_item
                WHERE id = %s
                """,
                (config.work_id,),
            )
            work_row = cur.fetchone() or {}
            cur.execute(
                """
                SELECT status
                FROM execution_session
                WHERE work_id = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (config.work_id,),
            )
            session_row = cur.fetchone() or {}
            cur.execute(
                """
                SELECT status
                FROM execution_wakeup
                WHERE work_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (config.work_id,),
            )
            wakeup_row = cur.fetchone() or {}
            cur.execute(
                """
                SELECT status
                FROM execution_job
                WHERE repo = %s
                  AND log_path LIKE %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (config.repo, f"{config.run_log_dir}/%"),
            )
            job_row = cur.fetchone() or {}
    work_status = str(work_row.get("status") or "")
    session_status = (
        str(session_row.get("status") or "") if session_row else None
    ) or None
    wakeup_status = (
        str(wakeup_row.get("status") or "") if wakeup_row else None
    ) or None
    execution_job_status = (
        str(job_row.get("status") or "") if job_row else None
    ) or None
    success = work_status == "done" and session_status == "completed"
    return LiveAcceptanceResult(
        success=success,
        work_status=work_status,
        session_status=session_status,
        wakeup_status=wakeup_status,
        execution_job_status=execution_job_status,
        log_dir=config.run_log_dir,
        planned_path=config.run_planned_path,
        details={
            "blocked_reason": work_row.get("blocked_reason"),
            "decision_required": bool(work_row.get("decision_required") or False),
        },
    )


def _restore_acceptance_state(
    config: LiveAcceptanceConfig,
    *,
    target_snapshot: _WorkItemSnapshot | None,
    suppress_snapshot: _WorkItemSnapshot | None,
    original_story_status: str | None,
    connect_fn: Callable[..., Any],
) -> None:
    if target_snapshot is None:
        return
    with connect_fn(config.dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM work_claim WHERE work_id = %s",
                (config.work_id,),
            )
            if config.suppress_work_id:
                cur.execute(
                    "DELETE FROM work_claim WHERE work_id = %s",
                    (config.suppress_work_id,),
                )
            cur.execute(
                """
                SELECT id
                FROM execution_session
                WHERE work_id = %s
                  AND created_at >= %s
                """,
                (config.work_id, config.run_started_at),
            )
            session_ids = [str(row["id"]) for row in cur.fetchall()]
            if session_ids:
                cur.execute(
                    "DELETE FROM policy_resolution WHERE session_id = ANY(%s)",
                    (session_ids,),
                )
                cur.execute(
                    "DELETE FROM execution_checkpoint WHERE session_id = ANY(%s)",
                    (session_ids,),
                )
                cur.execute(
                    "DELETE FROM execution_wakeup WHERE session_id = ANY(%s)",
                    (session_ids,),
                )
                cur.execute(
                    "DELETE FROM execution_session WHERE id = ANY(%s)",
                    (session_ids,),
                )
            cur.execute(
                """
                DELETE FROM execution_wakeup
                WHERE work_id = %s
                  AND created_at >= %s
                """,
                (config.work_id, config.run_started_at),
            )
            cur.execute(
                """
                DELETE FROM execution_run
                WHERE work_id = %s
                  AND started_at >= %s
                """,
                (config.work_id, config.run_started_at),
            )
            cur.execute(
                """
                DELETE FROM work_commit_link
                WHERE work_id = %s
                  AND created_at >= %s
                """,
                (config.work_id, config.run_started_at),
            )
            cur.execute(
                """
                DELETE FROM pull_request_link
                WHERE work_id = %s
                  AND created_at >= %s
                """,
                (config.work_id, config.run_started_at),
            )
            cur.execute(
                """
                DELETE FROM execution_job
                WHERE repo = %s
                  AND log_path LIKE %s
                """,
                (config.repo, f"{config.run_log_dir}/%"),
            )
            cur.execute(
                """
                UPDATE work_item
                SET status = %s,
                    blocked_reason = %s,
                    decision_required = %s,
                    next_eligible_at = %s,
                    dod_json = %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    target_snapshot.status,
                    target_snapshot.blocked_reason,
                    target_snapshot.decision_required,
                    target_snapshot.next_eligible_at,
                    json.dumps(target_snapshot.dod_json, ensure_ascii=False),
                    config.work_id,
                ),
            )
            if config.suppress_work_id and suppress_snapshot is not None:
                cur.execute(
                    """
                    UPDATE work_item
                    SET status = %s,
                        blocked_reason = %s,
                        decision_required = %s,
                        next_eligible_at = %s,
                        dod_json = %s::jsonb,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        suppress_snapshot.status,
                        suppress_snapshot.blocked_reason,
                        suppress_snapshot.decision_required,
                        suppress_snapshot.next_eligible_at,
                        json.dumps(suppress_snapshot.dod_json, ensure_ascii=False),
                        config.suppress_work_id,
                    ),
                )
            if original_story_status is not None:
                cur.execute(
                    """
                    UPDATE program_story
                    SET execution_status = %s,
                        updated_at = NOW()
                    WHERE repo = %s AND issue_number = %s
                    """,
                    (
                        original_story_status,
                        config.repo,
                        config.story_issue_number,
                    ),
                )
        conn.commit()
    shutil.rmtree(config.run_log_dir, ignore_errors=True)


def _fetch_work_item_row(
    cursor: Any,
    *,
    repo: str,
    work_id: str,
) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT id,
               repo,
               status,
               blocked_reason,
               decision_required,
               next_eligible_at,
               canonical_story_issue_number,
               dod_json
        FROM work_item
        WHERE repo = %s AND id = %s
        """,
        (repo, work_id),
    )
    row = cursor.fetchone()
    return dict(row) if row is not None else None


def _has_preexisting_runtime_state(cursor: Any, *, work_id: str) -> bool:
    checks = [
        ("SELECT 1 FROM work_claim WHERE work_id = %s LIMIT 1", (work_id,)),
        ("SELECT 1 FROM execution_session WHERE work_id = %s LIMIT 1", (work_id,)),
        ("SELECT 1 FROM execution_wakeup WHERE work_id = %s LIMIT 1", (work_id,)),
        ("SELECT 1 FROM work_commit_link WHERE work_id = %s LIMIT 1", (work_id,)),
        ("SELECT 1 FROM pull_request_link WHERE work_id = %s LIMIT 1", (work_id,)),
    ]
    for sql, params in checks:
        cursor.execute(sql, params)
        if cursor.fetchone() is not None:
            return True
    return False


def _slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-") or "live-acceptance"


if __name__ == "__main__":
    entrypoint()
