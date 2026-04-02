from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import Any

from .attempt_report import build_attempt_report
from .factory import build_postgres_repository
from .settings import load_postgres_settings_from_env


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_builder: Callable[..., Any] = build_postgres_repository,
    row_loader: Callable[..., list[dict[str, Any]]] | None = None,
    report_builder: Callable[..., dict[str, int]] = build_attempt_report,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)
    connection = getattr(repository, "_connection", repository)
    rows = (
        row_loader(connection=connection, repo=args.repo)
        if row_loader is not None
        else _load_execution_runs(connection=connection, repo=args.repo)
    )
    report = report_builder(execution_runs=rows)
    print(
        f"repo={args.repo} total_runs={report['total_runs']} "
        f"done_runs={report['done_runs']} "
        f"needs_decision_runs={report['needs_decision_runs']} "
        f"timeout_runs={report['timeout_runs']} "
        f"protocol_error_runs={report['protocol_error_runs']} "
        f"first_attempt_success_runs={report['first_attempt_success_runs']} "
        f"eventual_success_runs={report['eventual_success_runs']} "
        f"average_attempts_to_success={report['average_attempts_to_success']}"
    )
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskplane-attempt-report",
        description="Print a compact execution-attempt summary from PostgreSQL.",
    )
    parser.add_argument("--repo", required=True)
    return parser


def _load_execution_runs(*, connection: Any, repo: str) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT er.status, er.result_payload_json
            FROM execution_run er
            JOIN work_item wi ON wi.id = er.work_id
            WHERE wi.repo = %s
            ORDER BY er.id
            """,
            (repo,),
        )
        return list(cursor.fetchall())


if __name__ == "__main__":
    entrypoint()
