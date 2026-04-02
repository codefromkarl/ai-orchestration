from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import Any

from .factory import build_postgres_repository
from .governance_sync import (
    build_program_governance_projection,
    sync_program_governance_to_control_plane,
)
from .projection_sync import _load_normalized_issues
from .settings import load_postgres_settings_from_env


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_builder: Callable[..., Any] = build_postgres_repository,
    issues_loader: Callable[..., Any] = _load_normalized_issues,
    projection_builder: Callable[..., Any] = build_program_governance_projection,
    syncer: Callable[..., None] = sync_program_governance_to_control_plane,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)
    connection = getattr(repository, "_connection", repository)
    issues = issues_loader(connection=connection, repo=args.repo)
    projection = projection_builder(repo=args.repo, issues=issues)
    syncer(connection=connection, repo=args.repo, projection=projection)
    print(
        f"synced {len(projection.epics)} epics and {len(projection.stories)} stories for {args.repo}"
    )
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskplane-governance-sync",
        description="Project imported GitHub issues into governance-layer program_epic/program_story tables.",
    )
    parser.add_argument("--repo", required=True)
    return parser


if __name__ == "__main__":
    entrypoint()
