from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import Any

from .factory import build_postgres_repository
from .projection_sync import load_projection_from_staging, sync_projection_to_control_plane
from .settings import load_postgres_settings_from_env


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_builder: Callable[..., Any] = build_postgres_repository,
    projection_loader: Callable[..., Any] = load_projection_from_staging,
    syncer: Callable[..., None] = sync_projection_to_control_plane,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)
    connection = getattr(repository, "_connection", repository)
    projection = projection_loader(connection=connection, repo=args.repo)
    syncer(connection=connection, repo=args.repo, projection=projection)
    print(
        f"synced {len(projection.work_items)} work items for {args.repo}; "
        f"triage={len(projection.needs_triage_issue_numbers)}"
    )
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stardrifter-orchestration-project",
        description="Project imported GitHub issues into work_item/work_dependency tables.",
    )
    parser.add_argument("--repo", required=True)
    return parser


if __name__ == "__main__":
    entrypoint()
