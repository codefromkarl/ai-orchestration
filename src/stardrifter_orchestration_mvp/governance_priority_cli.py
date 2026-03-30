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
    snapshot_loader: Callable[..., dict[str, list[dict[str, Any]]]] | None = None,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)
    connection = getattr(repository, "_connection", repository)
    snapshot = (
        snapshot_loader(connection=connection, repo=args.repo)
        if snapshot_loader is not None
        else _load_priority_snapshot(connection=connection, repo=args.repo)
    )

    _print_priority_snapshot(repo=args.repo, snapshot=snapshot)
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stardrifter-orchestration-governance-priority",
        description="Print execution priority recommendations from the governance control plane.",
    )
    parser.add_argument("--repo", required=True)
    return parser


def _load_priority_snapshot(
    *,
    connection: Any,
    repo: str,
) -> dict[str, list[dict[str, Any]]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                wi.source_issue_number,
                wi.title,
                wi.task_type,
                wi.blocking_mode,
                wi.status,
                wi.canonical_story_issue_number AS story_issue_number,
                s.title AS story_title,
                e.issue_number AS epic_issue_number,
                e.title AS epic_title
            FROM v_active_task_queue wi
            JOIN program_story s
              ON s.repo = wi.repo
             AND s.issue_number = wi.canonical_story_issue_number
            JOIN program_epic e
              ON e.repo = s.repo
             AND e.issue_number = s.epic_issue_number
            WHERE wi.repo = %s
              AND wi.status <> 'done'
            ORDER BY
                CASE wi.task_type
                    WHEN 'governance' THEN 0
                    WHEN 'core_path' THEN 1
                    WHEN 'cross_cutting' THEN 2
                    ELSE 3
                END,
                CASE wi.blocking_mode
                    WHEN 'hard' THEN 0
                    ELSE 1
                END,
                wi.source_issue_number
            """,
            (repo,),
        )
        active_tasks = list(cursor.fetchall())

        cursor.execute(
            """
            SELECT
                repo,
                epic_issue_number,
                epic_title,
                story_issue_number,
                story_title,
                execution_status,
                story_task_count
            FROM v_story_decomposition_queue
            WHERE repo = %s
            ORDER BY story_issue_number
            """,
            (repo,),
        )
        decomposition_queue = list(cursor.fetchall())

        cursor.execute(
            """
            SELECT
                repo,
                epic_issue_number,
                epic_title,
                execution_status,
                epic_story_count
            FROM v_epic_decomposition_queue
            WHERE repo = %s
            ORDER BY epic_issue_number
            """,
            (repo,),
        )
        epic_decomposition_queue = list(cursor.fetchall())

        cursor.execute(
            """
            SELECT
                tree.story_issue_number,
                tree.story_title,
                tree.epic_issue_number,
                tree.epic_title,
                tree.story_execution_status
            FROM v_program_tree tree
            WHERE tree.repo = %s
              AND tree.epic_execution_status = 'active'
              AND tree.story_execution_status = 'needs_story_refinement'
            ORDER BY tree.story_issue_number
            """,
            (repo,),
        )
        refinement_queue = list(cursor.fetchall())

        cursor.execute(
            """
            SELECT
                e.issue_number,
                e.title,
                e.execution_status,
                COUNT(ped.depends_on_epic_issue_number) FILTER (
                    WHERE dep.execution_status = 'done'
                ) AS done_dependency_count,
                COUNT(ped.depends_on_epic_issue_number) FILTER (
                    WHERE dep.execution_status = 'active'
                ) AS active_dependency_count,
                COUNT(ped.depends_on_epic_issue_number) FILTER (
                    WHERE dep.execution_status NOT IN ('active', 'done')
                ) AS blocked_dependency_count,
                ARRAY_REMOVE(
                    ARRAY_AGG(
                        CASE
                            WHEN dep.execution_status = 'active'
                            THEN format('#%%s(active)', dep.issue_number)
                        END
                        ORDER BY dep.issue_number
                    ),
                    NULL
                ) AS active_dependencies,
                ARRAY_REMOVE(
                    ARRAY_AGG(
                        CASE
                            WHEN dep.execution_status NOT IN ('active', 'done')
                            THEN format('#%%s(%%s)', dep.issue_number, dep.execution_status::text)
                        END
                        ORDER BY dep.issue_number
                    ),
                    NULL
                ) AS blocked_dependencies
            FROM program_epic e
            LEFT JOIN program_epic_dependency ped
              ON ped.repo = e.repo
             AND ped.epic_issue_number = e.issue_number
            LEFT JOIN program_epic dep
              ON dep.repo = ped.repo
             AND dep.issue_number = ped.depends_on_epic_issue_number
            WHERE e.repo = %s
              AND e.program_status = 'approved'
              AND e.execution_status = 'gated'
            GROUP BY e.issue_number, e.title, e.execution_status
            ORDER BY
                COUNT(ped.depends_on_epic_issue_number) FILTER (
                    WHERE dep.execution_status NOT IN ('active', 'done')
                ),
                e.issue_number
            """,
            (repo,),
        )
        gated_epics = list(cursor.fetchall())

        cursor.execute(
            """
            SELECT issue_number, title, execution_status
            FROM program_epic
            WHERE repo = %s
              AND program_status = 'approved'
              AND execution_status = 'planned'
            ORDER BY issue_number
            """,
            (repo,),
        )
        planned_epics = list(cursor.fetchall())

    return {
        "active_tasks": active_tasks,
        "decomposition_queue": decomposition_queue,
        "epic_decomposition_queue": epic_decomposition_queue,
        "refinement_queue": refinement_queue,
        "gated_epics": gated_epics,
        "planned_epics": planned_epics,
    }


def _print_priority_snapshot(
    *,
    repo: str,
    snapshot: dict[str, list[dict[str, Any]]],
) -> None:
    active_tasks = snapshot.get("active_tasks", [])
    decomposition_queue = snapshot.get("decomposition_queue", [])
    epic_decomposition_queue = snapshot.get("epic_decomposition_queue", [])
    refinement_queue = snapshot.get("refinement_queue", [])
    gated_epics = snapshot.get("gated_epics", [])
    planned_epics = snapshot.get("planned_epics", [])

    print("[Priority Now]")
    rank = 1
    for row in active_tasks:
        print(
            f"{rank}. execute task #{row['source_issue_number']} {row['title']}  "
            f"(epic=#{row['epic_issue_number']} story=#{row['story_issue_number']} "
            f"type={row['task_type']} blocking={row['blocking_mode']} status={row['status']})"
        )
        rank += 1
    for row in decomposition_queue:
        print(
            f"{rank}. split story #{row['story_issue_number']} {row['story_title']}  "
            f"(epic=#{row['epic_issue_number']} status={row['execution_status']} "
            f"tasks={row['story_task_count']} reason=awaiting-task-decomposition)"
        )
        rank += 1
    for row in epic_decomposition_queue:
        print(
            f"{rank}. split epic #{row['epic_issue_number']} {row['epic_title']}  "
            f"(status={row['execution_status']} stories={row['epic_story_count']} "
            f"reason=awaiting-story-decomposition)"
        )
        rank += 1
    for row in refinement_queue:
        print(
            f"{rank}. refine story #{row['story_issue_number']} {row['story_title']}  "
            f"(epic=#{row['epic_issue_number']} status={row['story_execution_status']} "
            f"reason=story-boundary-invalid)"
        )
        rank += 1
    if rank == 1:
        print("none")

    print("\n[Priority Next]")
    ready_after_current = [
        row for row in gated_epics if int(row["blocked_dependency_count"] or 0) == 0
    ]
    blocked_chain = [
        row for row in gated_epics if int(row["blocked_dependency_count"] or 0) > 0
    ]
    if ready_after_current:
        for row in ready_after_current:
            deps = ", ".join(row.get("active_dependencies") or []) or "none"
            print(
                f"- activate epic #{row['issue_number']} {row['title']}  "
                f"(waiting_on_active={deps})"
            )
    else:
        print("none")

    print("\n[Blocked Chain]")
    if blocked_chain:
        for row in blocked_chain:
            blockers = ", ".join(row.get("blocked_dependencies") or []) or "none"
            print(
                f"- epic #{row['issue_number']} {row['title']}  "
                f"(blocked_by={blockers})"
            )
    else:
        print("none")

    print("\n[Planned In Tree]")
    if planned_epics:
        for row in planned_epics:
            print(f"- epic #{row['issue_number']} {row['title']}  (planned)")
    else:
        print("none")

    print(
        "\n"
        f"repo={repo} active_tasks={len(active_tasks)} "
        f"decomposition_queue={len(decomposition_queue)} "
        f"refinement_queue={len(refinement_queue)} "
        f"ready_after_current={len(ready_after_current)} "
        f"planned_epics={len(planned_epics)}"
    )


if __name__ == "__main__":
    entrypoint()
