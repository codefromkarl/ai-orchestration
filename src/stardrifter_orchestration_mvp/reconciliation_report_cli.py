from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import Any

from .factory import build_postgres_repository
from .github_writeback import story_github_writeback, task_github_writeback
from .reconciliation import (
    build_reconciliation_report,
    load_reconciliation_rows,
    repair_reconciliation_drift,
)
from .settings import load_postgres_settings_from_env


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_builder: Callable[..., Any] = build_postgres_repository,
    row_loader: Callable[
        ..., dict[str, list[dict[str, Any]]]
    ] = load_reconciliation_rows,
    report_builder: Callable[
        ..., dict[str, list[dict[str, Any]]]
    ] = build_reconciliation_report,
    repairer: Callable[..., dict[str, int]] = repair_reconciliation_drift,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)
    connection = getattr(repository, "_connection", repository)
    rows = row_loader(
        connection=connection,
        repo=args.repo,
        repo_root=args.repo_root,
        worktree_root=args.worktree_root,
    )
    report = report_builder(task_rows=rows["task_rows"], story_rows=rows["story_rows"])

    print(
        f"repo={args.repo} task_drift={len(report['task_drift'])} story_drift={len(report['story_drift'])}"
    )
    if args.apply_safe_repairs:
        repair_summary = repairer(
            report=report,
            repo=args.repo,
            task_repair=task_github_writeback,
            story_repair=story_github_writeback,
        )
        print(
            "repaired "
            f"task={repair_summary['task_repaired']} "
            f"story={repair_summary['story_repaired']} "
            f"skipped_task={repair_summary['task_skipped']} "
            f"skipped_story={repair_summary['story_skipped']}"
        )
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stardrifter-orchestration-reconciliation-report",
        description="Report DB/GitHub/PR drift and optionally repair safe GitHub status drift.",
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--repo-root")
    parser.add_argument("--worktree-root")
    parser.add_argument("--apply-safe-repairs", action="store_true")
    return parser


if __name__ == "__main__":
    entrypoint()
