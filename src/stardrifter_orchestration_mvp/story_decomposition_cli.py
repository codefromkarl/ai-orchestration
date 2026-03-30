from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .factory import build_postgres_repository
from .protocols import HierarchyRunnerAdapter
from .settings import load_postgres_settings_from_env
from .story_decomposition import StoryDecompositionResult, run_story_decomposition


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_builder: Callable[..., Any] = build_postgres_repository,
    decomposition_runner: HierarchyRunnerAdapter = run_story_decomposition,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)

    result = decomposition_runner(
        repo=args.repo,
        story_issue_number=args.story_issue_number,
        repository=repository,
        workdir=Path(args.workdir).resolve(),
        decomposer_command=args.decomposer_command,
    )
    print(
        f"story {result.story_issue_number} {result.final_execution_status}; "
        f"tasks={result.projectable_task_count} summary={result.summary}"
    )
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stardrifter-orchestration-story-decomposition",
        description="Run AI task decomposition for a decomposing story.",
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--story-issue-number", type=int, required=True)
    parser.add_argument("--workdir", default=".")
    parser.add_argument("--decomposer-command")
    return parser


if __name__ == "__main__":
    entrypoint()
