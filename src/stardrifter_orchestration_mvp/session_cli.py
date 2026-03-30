"""CLI entry point for running long sessions."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .policy_engine import evaluate_policy
from .session_manager import InMemorySessionManager
from .session_runtime_loop import (
    ExecutorResult,
    run_session_to_completion,
)
from .strategy_executor import apply_strategy_to_executor_kwargs, resolve_strategy
from .wakeup_dispatcher import InMemoryWakeupDispatcher


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stardrifter-session",
        description="Run a long session with checkpoint/wait lifecycle",
    )
    parser.add_argument(
        "--work-id",
        required=True,
        help="Work item ID to execute",
    )
    parser.add_argument(
        "--dsn",
        default=os.environ.get("STARDRIFTER_ORCHESTRATION_DSN", ""),
        help="PostgreSQL DSN (or set STARDRIFTER_ORCHESTRATION_DSN)",
    )
    parser.add_argument(
        "--project-dir",
        default=os.environ.get("STARDRIFTER_PROJECT_DIR", "."),
        help="Project directory",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=50,
        help="Maximum session iterations",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1200,
        help="Executor timeout in seconds",
    )
    parser.add_argument(
        "--context",
        default="",
        help="Initial context summary for the session",
    )
    parser.add_argument(
        "--phase",
        default="researching",
        help="Initial execution phase",
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Output results as JSON",
    )
    return parser


def _make_opencode_executor(
    *,
    work_id: str,
    dsn: str,
    project_dir: Path,
    timeout: int,
) -> Any:
    from .executor_adapter import run_opencode_executor

    def executor_fn(**kwargs: Any) -> ExecutorResult:
        resume_context = kwargs.get("resume_context", "")
        env = os.environ.copy()
        env["STARDRIFTER_WORK_ID"] = work_id
        env["STARDRIFTER_ORCHESTRATION_DSN"] = dsn
        env["STARDRIFTER_PROJECT_DIR"] = str(project_dir)
        if resume_context:
            env["STARDRIFTER_RESUME_CONTEXT"] = resume_context

        cmd = [
            sys.executable,
            "-m",
            "stardrifter_orchestration_mvp.opencode_task_executor",
        ]

        return run_opencode_executor(
            command=cmd,
            project_dir=project_dir,
            timeout_seconds=timeout,
            env=env,
        )

    return executor_fn


def main() -> int:
    args = _build_parser().parse_args()

    if not args.dsn:
        print("Error: --dsn or STARDRIFTER_ORCHESTRATION_DSN required", file=sys.stderr)
        return 1

    project_dir = Path(args.project_dir).resolve()
    if not project_dir.exists():
        print(f"Error: project dir not found: {project_dir}", file=sys.stderr)
        return 1

    try:
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(args.dsn, row_factory=dict_row)
        from .session_manager_postgres import PostgresSessionManager

        session_manager = PostgresSessionManager(conn)
        backend = "postgresql"
    except Exception:
        session_manager = InMemorySessionManager()
        backend = "inmemory"
        print(
            "Warning: PostgreSQL unavailable, using in-memory backend", file=sys.stderr
        )

    wakeup_dispatcher = InMemoryWakeupDispatcher()
    session = session_manager.create_session(
        work_id=args.work_id,
        current_phase=args.phase,
        context_summary=args.context or None,
    )

    executor_fn = _make_opencode_executor(
        work_id=args.work_id,
        dsn=args.dsn,
        project_dir=project_dir,
        timeout=args.timeout,
    )

    result = run_session_to_completion(
        session_id=session.id,
        session_manager=session_manager,
        wakeup_dispatcher=wakeup_dispatcher,
        executor_fn=executor_fn,
        policy_engine_fn=evaluate_policy,
        max_iterations=args.max_iterations,
    )

    checkpoints = session_manager.list_checkpoints(session.id)
    final_session = session_manager.get_session(session.id)

    output = {
        "session_id": session.id,
        "work_id": args.work_id,
        "backend": backend,
        "final_status": result.final_status,
        "iterations": result.iterations,
        "session_status": final_session.status if final_session else "unknown",
        "checkpoints": [
            {
                "phase": c.phase,
                "phase_index": c.phase_index,
                "summary": c.summary,
                "next_action": c.next_action_hint,
            }
            for c in checkpoints
        ],
    }

    if args.json_output:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"Session: {session.id}")
        print(f"Backend: {backend}")
        print(f"Status: {result.final_status}")
        print(f"Iterations: {result.iterations}")
        print(f"Checkpoints ({len(checkpoints)}):")
        for i, ckpt in enumerate(checkpoints, 1):
            print(f"  [{i}] {ckpt.phase}: {ckpt.summary}")
            if ckpt.next_action_hint:
                print(f"      next: {ckpt.next_action_hint}")

    if hasattr(session_manager, "_connection"):
        try:
            session_manager._connection.close()
        except Exception:
            pass

    return 0 if result.final_status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
