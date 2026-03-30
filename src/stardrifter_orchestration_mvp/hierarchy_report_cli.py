from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import Any

from .factory import build_postgres_repository
from .hierarchy_report import HierarchyTree, build_hierarchy_tree, format_hierarchy_tree
from .projection_sync import _load_normalized_issues
from .settings import load_postgres_settings_from_env


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_builder: Callable[..., Any] = build_postgres_repository,
    issues_loader: Callable[..., Any] = _load_normalized_issues,
    tree_builder: Callable[..., HierarchyTree] = build_hierarchy_tree,
    formatter: Callable[[HierarchyTree], str] = format_hierarchy_tree,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)
    connection = getattr(repository, "_connection", repository)

    issues = issues_loader(connection=connection, repo=args.repo)
    tree = tree_builder(issues)
    output = formatter(tree)
    if output:
        print(output)
    print(
        f"\nrepo={args.repo} "
        f"epics={len(tree.epics)} "
        f"orphan_stories={len(tree.orphan_stories)} "
        f"orphan_tasks={len(tree.orphan_tasks)}"
    )
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stardrifter-orchestration-hierarchy",
        description="Print Epic -> Story -> Task hierarchy for imported GitHub issues.",
    )
    parser.add_argument("--repo", required=True, help="GitHub repo slug, e.g. owner/repo")
    return parser


if __name__ == "__main__":
    entrypoint()
