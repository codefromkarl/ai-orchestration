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
    report_loader: Callable[..., list[dict[str, Any]]] | None = None,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)
    connection = getattr(repository, "_connection", repository)
    rows = (
        report_loader(connection=connection, repo=args.repo)
        if report_loader is not None
        else _load_report_rows(connection=connection, repo=args.repo)
    )

    current_epic = None
    active_epics: set[int] = set()
    for row in rows:
        epic_issue_number = row["epic_issue_number"]
        if row["epic_execution_status"] == "active":
            active_epics.add(epic_issue_number)
        if current_epic != epic_issue_number:
            print(
                f"[Epic #{epic_issue_number}] {row['epic_title']}  ({row['epic_execution_status']})"
            )
            current_epic = epic_issue_number
        if row["story_issue_number"] is not None:
            linkage_notes: list[str] = [
                f"tasks={row.get('story_task_count', 0)}",
                f"active_tasks={row.get('story_active_task_count', 0)}",
            ]
            if (
                row["story_execution_status"] == "decomposing"
                and row.get("story_task_count", 0) == 0
            ):
                linkage_notes.append("awaiting-decomposition")
            elif row["story_execution_status"] in {"active", "planned"} and row.get("story_task_count", 0) == 0:
                linkage_notes.append("no-task-container")
            elif row["story_execution_status"] == "active" and row.get("story_active_task_count", 0) == 0:
                linkage_notes.append("no-active-task")
            print(
                f"  [Story #{row['story_issue_number']}] {row['story_title']}  "
                f"({row['story_execution_status']}; {' '.join(linkage_notes)})"
            )

    print(f"\nrepo={args.repo} active_epics={len(active_epics)} rows={len(rows)}")
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stardrifter-orchestration-governance-report",
        description="Print governance-layer Epic/Story execution report from PostgreSQL.",
    )
    parser.add_argument("--repo", required=True)
    return parser


def _load_report_rows(*, connection: Any, repo: str) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                epic_issue_number,
                epic_title,
                epic_execution_status,
                story_issue_number,
                story_title,
                story_execution_status,
                COALESCE(story_task_count, 0) AS story_task_count,
                COALESCE(story_active_task_count, 0) AS story_active_task_count
            FROM (
                SELECT
                    tree.repo,
                    tree.epic_issue_number,
                    tree.epic_title,
                    tree.epic_execution_status,
                    tree.story_issue_number,
                    tree.story_title,
                    tree.story_execution_status,
                    task_counts.story_task_count,
                    active_task_counts.story_active_task_count
                FROM v_program_tree tree
                LEFT JOIN (
                    SELECT
                        repo,
                        canonical_story_issue_number AS story_issue_number,
                        COUNT(*) AS story_task_count
                    FROM work_item
                    WHERE canonical_story_issue_number IS NOT NULL
                    GROUP BY repo, canonical_story_issue_number
                ) task_counts
                  ON task_counts.repo = tree.repo
                 AND task_counts.story_issue_number = tree.story_issue_number
                LEFT JOIN (
                    SELECT
                        repo,
                        canonical_story_issue_number AS story_issue_number,
                        COUNT(*) AS story_active_task_count
                    FROM v_active_task_queue
                    WHERE canonical_story_issue_number IS NOT NULL
                    GROUP BY repo, canonical_story_issue_number
                ) active_task_counts
                  ON active_task_counts.repo = tree.repo
                 AND active_task_counts.story_issue_number = tree.story_issue_number
            ) report
            WHERE report.repo = %s
            ORDER BY epic_issue_number, story_issue_number
            """,
            (repo,),
        )
        return list(cursor.fetchall())


if __name__ == "__main__":
    entrypoint()
