from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import Any

from .factory import build_postgres_repository
from .github_sync import fetch_issues_via_gh, persist_issue_import_batch
from .settings import load_postgres_settings_from_env


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_builder: Callable[..., Any] = build_postgres_repository,
    fetcher: Callable[..., list[dict]] = fetch_issues_via_gh,
    persister: Callable[..., None] = persist_issue_import_batch,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)
    raw_issues = fetcher(repo=args.repo, limit=args.limit)
    connection = getattr(repository, "_connection", repository)
    persister(connection=connection, repo=args.repo, raw_issues=raw_issues)
    print(f"imported {len(raw_issues)} issues from {args.repo}")
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskplane-import",
        description="Import GitHub issues into the PostgreSQL orchestration control plane.",
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--limit", type=int, default=200)
    return parser


if __name__ == "__main__":
    entrypoint()
