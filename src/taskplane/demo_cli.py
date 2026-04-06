from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import Any

from .settings import load_postgres_settings_from_env


def main(
    argv: Sequence[str] | None = None,
    *,
    connector: Callable[[str], Any] | None = None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command != "seed":
        parser.error("a subcommand is required")

    settings = load_postgres_settings_from_env()
    connection_factory = connector or _default_connector
    connection = connection_factory(settings.dsn)
    try:
        seed_demo_repository(connection, repo=args.repo, reset=args.reset)
        connection.commit()
    finally:
        close = getattr(connection, "close", None)
        if callable(close):
            close()

    print(f"seeded demo repo {args.repo}")
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def seed_demo_repository(connection: Any, *, repo: str, reset: bool = False) -> None:
    if reset:
        _reset_repo(connection, repo=repo)

    snapshot_id = _insert_snapshot_batch(connection, repo=repo)
    issues = _build_demo_issues(repo=repo)

    for issue in issues:
        _insert_snapshot_issue(connection, snapshot_id=snapshot_id, issue=issue)
        _insert_normalized_issue(connection, snapshot_id=snapshot_id, issue=issue)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO program_epic (
                repo, issue_number, title, lane, program_status, execution_status, active_wave, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (repo, issue_number) DO UPDATE SET
                title = EXCLUDED.title,
                lane = EXCLUDED.lane,
                program_status = EXCLUDED.program_status,
                execution_status = EXCLUDED.execution_status,
                active_wave = EXCLUDED.active_wave,
                notes = EXCLUDED.notes,
                updated_at = NOW()
            """,
            (
                repo,
                101,
                "Demo Epic · 首次引导链路",
                "Lane demo",
                "approved",
                "active",
                "wave-demo",
                "用于本地演示 Taskplane 的最小治理链路。",
            ),
        )
        cursor.execute(
            """
            INSERT INTO program_story (
                repo, issue_number, epic_issue_number, title, lane, complexity,
                program_status, execution_status, active_wave, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (repo, issue_number) DO UPDATE SET
                epic_issue_number = EXCLUDED.epic_issue_number,
                title = EXCLUDED.title,
                lane = EXCLUDED.lane,
                complexity = EXCLUDED.complexity,
                program_status = EXCLUDED.program_status,
                execution_status = EXCLUDED.execution_status,
                active_wave = EXCLUDED.active_wave,
                notes = EXCLUDED.notes,
                updated_at = NOW()
            """,
            (
                repo,
                102,
                101,
                "Demo Story · 控制台启动和检查",
                "Lane demo",
                "medium",
                "approved",
                "active",
                "wave-demo",
                "覆盖启动、诊断和控制台检查的基本流程。",
            ),
        )
        cursor.execute(
            """
            INSERT INTO epic_execution_state (
                repo, epic_issue_number, status,
                completed_story_issue_numbers_json,
                blocked_story_issue_numbers_json,
                remaining_story_issue_numbers_json,
                verification_status,
                verification_reason_code,
                verification_summary
            ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s)
            ON CONFLICT (repo, epic_issue_number) DO UPDATE SET
                status = EXCLUDED.status,
                completed_story_issue_numbers_json = EXCLUDED.completed_story_issue_numbers_json,
                blocked_story_issue_numbers_json = EXCLUDED.blocked_story_issue_numbers_json,
                remaining_story_issue_numbers_json = EXCLUDED.remaining_story_issue_numbers_json,
                verification_status = EXCLUDED.verification_status,
                verification_reason_code = EXCLUDED.verification_reason_code,
                verification_summary = EXCLUDED.verification_summary,
                updated_at = NOW()
            """,
            (
                repo,
                101,
                "awaiting_operator",
                "[]",
                "[102]",
                "[]",
                "failed",
                "demo_setup_pending",
                "运行 doctor 后即可继续。",
            ),
        )
        cursor.execute(
            """
            INSERT INTO work_item (
                id, repo, title, lane, wave, status, complexity,
                source_issue_number, canonical_story_issue_number,
                task_type, blocking_mode, blocked_reason, dod_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (id) DO UPDATE SET
                repo = EXCLUDED.repo,
                title = EXCLUDED.title,
                lane = EXCLUDED.lane,
                wave = EXCLUDED.wave,
                status = EXCLUDED.status,
                complexity = EXCLUDED.complexity,
                source_issue_number = EXCLUDED.source_issue_number,
                canonical_story_issue_number = EXCLUDED.canonical_story_issue_number,
                task_type = EXCLUDED.task_type,
                blocking_mode = EXCLUDED.blocking_mode,
                blocked_reason = EXCLUDED.blocked_reason,
                dod_json = EXCLUDED.dod_json,
                updated_at = NOW()
            """,
            (
                "demo-task-103",
                repo,
                "执行 taskplane-doctor 并确认本地配置",
                "Lane demo",
                "wave-demo",
                "blocked",
                "low",
                103,
                102,
                "governance",
                "soft",
                "需要先创建 taskplane.toml 并启动本地依赖。",
                '{"steps":["cp taskplane.toml.example taskplane.toml","taskplane-dev up","taskplane-doctor --repo demo/taskplane"]}',
            ),
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskplane-demo",
        description="Seed or manage local Taskplane demo data.",
    )
    subparsers = parser.add_subparsers(dest="command")
    seed_parser = subparsers.add_parser(
        "seed",
        help="Insert a small demo repo with one epic, one story, and one blocked task.",
    )
    seed_parser.add_argument("--repo", default="demo/taskplane")
    seed_parser.add_argument("--reset", action="store_true")
    return parser


def _default_connector(dsn: str) -> Any:
    import psycopg

    return psycopg.connect(dsn)


def _reset_repo(connection: Any, *, repo: str) -> None:
    statements = (
        "DELETE FROM github_issue_relation WHERE repo = %s",
        "DELETE FROM github_issue_completion_audit WHERE repo = %s",
        "DELETE FROM github_issue_normalized WHERE repo = %s",
        "DELETE FROM github_issue_snapshot WHERE repo = %s",
        "DELETE FROM github_issue_import_batch WHERE repo = %s",
        "DELETE FROM epic_execution_state WHERE repo = %s",
        "DELETE FROM program_story_dependency WHERE repo = %s",
        "DELETE FROM program_epic_dependency WHERE repo = %s",
        "DELETE FROM program_story WHERE repo = %s",
        "DELETE FROM program_epic WHERE repo = %s",
        "DELETE FROM work_item WHERE repo = %s",
    )
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement, (repo,))


def _insert_snapshot_batch(connection: Any, *, repo: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO github_issue_import_batch (repo)
            VALUES (%s)
            RETURNING id
            """,
            (repo,),
        )
        row = cursor.fetchone()
    if not row:
        raise RuntimeError("failed to create github_issue_import_batch")
    return int(row[0])


def _insert_snapshot_issue(connection: Any, *, snapshot_id: int, issue: dict[str, Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO github_issue_snapshot (batch_id, repo, issue_number, raw_json)
            VALUES (%s, %s, %s, %s::jsonb)
            """,
            (
                snapshot_id,
                issue["repo"],
                issue["issue_number"],
                issue["raw_json"],
            ),
        )


def _insert_normalized_issue(connection: Any, *, snapshot_id: int, issue: dict[str, Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO github_issue_normalized (
                repo, issue_number, title, body, url, github_state, import_state,
                issue_kind, lane, complexity, status_label,
                explicit_parent_issue_numbers,
                explicit_story_dependency_issue_numbers,
                explicit_task_dependency_issue_numbers,
                anomaly_codes,
                source_snapshot_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s
            )
            ON CONFLICT (repo, issue_number) DO UPDATE SET
                title = EXCLUDED.title,
                body = EXCLUDED.body,
                url = EXCLUDED.url,
                github_state = EXCLUDED.github_state,
                import_state = EXCLUDED.import_state,
                issue_kind = EXCLUDED.issue_kind,
                lane = EXCLUDED.lane,
                complexity = EXCLUDED.complexity,
                status_label = EXCLUDED.status_label,
                explicit_parent_issue_numbers = EXCLUDED.explicit_parent_issue_numbers,
                explicit_story_dependency_issue_numbers = EXCLUDED.explicit_story_dependency_issue_numbers,
                explicit_task_dependency_issue_numbers = EXCLUDED.explicit_task_dependency_issue_numbers,
                anomaly_codes = EXCLUDED.anomaly_codes,
                source_snapshot_id = EXCLUDED.source_snapshot_id,
                updated_at = NOW()
            """,
            (
                issue["repo"],
                issue["issue_number"],
                issue["title"],
                issue["body"],
                issue["url"],
                "OPEN",
                "imported",
                issue["issue_kind"],
                "Lane demo",
                issue["complexity"],
                issue["status_label"],
                issue["parents_json"],
                "[]",
                "[]",
                "[]",
                snapshot_id,
            ),
        )


def _build_demo_issues(*, repo: str) -> list[dict[str, Any]]:
    return [
        {
            "repo": repo,
            "issue_number": 101,
            "title": "Demo Epic · 首次引导链路",
            "body": "Taskplane demo epic for onboarding.",
            "url": f"https://example.invalid/{repo}/issues/101",
            "issue_kind": "epic",
            "complexity": "medium",
            "status_label": "active",
            "parents_json": "[]",
            "raw_json": '{"number":101,"title":"Demo Epic · 首次引导链路"}',
        },
        {
            "repo": repo,
            "issue_number": 102,
            "title": "Demo Story · 控制台启动和检查",
            "body": "Story covering local bootstrap and doctor flow.",
            "url": f"https://example.invalid/{repo}/issues/102",
            "issue_kind": "story",
            "complexity": "medium",
            "status_label": "active",
            "parents_json": "[101]",
            "raw_json": '{"number":102,"title":"Demo Story · 控制台启动和检查"}',
        },
        {
            "repo": repo,
            "issue_number": 103,
            "title": "Demo Task · 运行 doctor",
            "body": "Run doctor and confirm configuration.",
            "url": f"https://example.invalid/{repo}/issues/103",
            "issue_kind": "task",
            "complexity": "low",
            "status_label": "blocked",
            "parents_json": "[102]",
            "raw_json": '{"number":103,"title":"Demo Task · 运行 doctor"}',
        },
    ]
