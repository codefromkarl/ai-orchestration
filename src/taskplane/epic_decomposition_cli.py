from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .epic_decomposition import EpicDecompositionResult, run_epic_decomposition
from .factory import build_postgres_repository
from .settings import load_postgres_settings_from_env


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_builder: Callable[..., Any] = build_postgres_repository,
    decomposition_runner: Callable[..., EpicDecompositionResult] = run_epic_decomposition,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)
    result = decomposition_runner(
        repo=args.repo,
        epic_issue_number=args.epic_issue_number,
        repository=repository,
        workdir=Path(args.workdir).resolve(),
        decomposer_command=args.decomposer_command,
    )
    print(
        f"epic={result.epic_issue_number} status={result.final_execution_status} "
        f"stories={result.projectable_story_count} summary={result.summary}"
    )
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskplane-epic-decomposition",
        description="Run AI story decomposition for an epic with no stories.",
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--epic-issue-number", type=int, required=True)
    parser.add_argument("--workdir", default=".")
    parser.add_argument("--decomposer-command")
    return parser


if __name__ == "__main__":
    entrypoint()
