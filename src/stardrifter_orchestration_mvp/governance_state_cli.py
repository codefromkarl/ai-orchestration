from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import Any

from .factory import build_postgres_repository
from .settings import load_postgres_settings_from_env


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_builder: Callable[..., Any] = build_postgres_repository,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)

    if args.kind == "epic":
        if args.propagate:
            repository.set_program_epic_execution_status_with_propagation(
                repo=args.repo,
                issue_number=args.issue_number,
                execution_status=args.execution_status,
            )
        else:
            repository.set_program_epic_execution_status(
                repo=args.repo,
                issue_number=args.issue_number,
                execution_status=args.execution_status,
            )
    else:
        if args.propagate:
            repository.set_program_story_execution_status_with_propagation(
                repo=args.repo,
                issue_number=args.issue_number,
                execution_status=args.execution_status,
            )
        else:
            repository.set_program_story_execution_status(
                repo=args.repo,
                issue_number=args.issue_number,
                execution_status=args.execution_status,
            )

    print(f"updated {args.kind} #{args.issue_number} -> {args.execution_status}")
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stardrifter-orchestration-governance-state",
        description="Update governance-layer execution status for an epic or story.",
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--kind", choices=("epic", "story"), required=True)
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument(
        "--execution-status",
        choices=(
            "backlog",
            "planned",
            "decomposing",
            "active",
            "gated",
            "done",
            "blocked",
            "needs_story_refinement",
        ),
        required=True,
    )
    parser.add_argument("--propagate", action="store_true")
    return parser


if __name__ == "__main__":
    entrypoint()
