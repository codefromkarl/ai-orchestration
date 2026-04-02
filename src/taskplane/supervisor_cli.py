"""
Supervisor CLI module for taskplane.

This module provides the command-line interface for the supervisor loop.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .scheduling_loop import run_supervisor_iteration


def main() -> int:
    """Main entry point for the supervisor CLI."""
    args = _build_parser().parse_args()
    log_dir = Path(args.log_dir).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    project_dir = Path(args.project_dir).resolve()
    worktree_root = Path(args.worktree_root).resolve() if args.worktree_root else None
    promotion_repo_root = (
        Path(args.promotion_repo_root).resolve() if args.promotion_repo_root else None
    )
    running_processes: dict[int, ManagedProcess] = {}

    while True:
        with psycopg.connect(args.dsn, row_factory=dict_row) as conn:
            launched = run_supervisor_iteration(
                connection=conn,
                repo=args.repo,
                dsn=args.dsn,
                project_dir=project_dir,
                log_dir=log_dir,
                worktree_root=worktree_root,
                promotion_repo_root=promotion_repo_root,
                max_parallel_jobs=args.max_parallel_jobs,
                epic_story_batch_size=args.epic_story_batch_size,
                launcher=_launch_managed_process,
                running_processes=running_processes,
            )
        if launched == 0:
            time.sleep(args.poll_interval)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the supervisor CLI."""
    parser = argparse.ArgumentParser(
        prog="taskplane-supervisor",
        description="Run the orchestration supervisor loop and monitor background jobs.",
    )
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--repo", default="codefromkarl/stardrifter")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--worktree-root")
    parser.add_argument("--promotion-repo-root")
    parser.add_argument("--poll-interval", type=int, default=15)
    parser.add_argument("--max-parallel-jobs", type=int, default=2)
    parser.add_argument("--epic-story-batch-size", type=int, default=1)
    return parser


def _launch_managed_process(command: str, log_path: Path) -> ManagedProcess:
    """Launch a managed subprocess."""
    from .process_manager import launch_managed_process as launch

    return launch(command, log_path)


class ManagedProcess:
    """Protocol-like class for managed subprocess."""

    pid: int

    def poll(self) -> int | None:
        """Check if process has completed."""
        ...


def entrypoint() -> None:
    """Entry point that raises SystemExit."""
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
