from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

from . import console_queries as queries


def _require_repo(connection: Any, repo: str) -> None:
    row = _fetch_one(
        connection,
        queries.REQUIRE_REPO_QUERY,
        (repo,),
    )

    if row is None:
        from .console_api import ConsoleNotFoundError

        raise ConsoleNotFoundError(f"repo {repo} not found")


def _rollback_if_possible(connection: Any) -> None:
    rollback = getattr(connection, "rollback", None)
    if callable(rollback):
        rollback()


def _is_missing_epic_execution_state(exc: psycopg.errors.UndefinedTable) -> bool:
    message = str(exc)
    return "epic_execution_state" in message


def _get_notification_query(repo: str | None, include_sent: bool) -> str:
    if repo:
        if include_sent:
            return queries.LIST_NOTIFICATIONS_WITH_REPO_SENT_QUERY
        return queries.LIST_NOTIFICATIONS_WITH_REPO_PENDING_QUERY

    if include_sent:
        return queries.LIST_NOTIFICATIONS_SENT_QUERY
    return queries.LIST_NOTIFICATIONS_PENDING_QUERY


def _build_retry_context(
    *, task: dict[str, Any], recent_runs: list[dict[str, Any]]
) -> dict[str, Any]:
    latest_run = recent_runs[0] if recent_runs else None
    latest_failure = next(
        (
            run
            for run in recent_runs
            if str(run.get("status") or "") != "done"
            or bool(run.get("verification_passed")) is False
        ),
        None,
    )

    result_payload = (
        latest_failure.get("result_payload_json") if latest_failure else None
    )

    return {
        "attempt_count": task.get("attempt_count") or 0,
        "last_failure_reason": task.get("last_failure_reason"),
        "next_eligible_at": task.get("next_eligible_at"),
        "blocked_reason": task.get("blocked_reason"),
        "decision_required": bool(task.get("decision_required")),
        "latest_run_status": None if latest_run is None else latest_run.get("status"),
        "latest_run_summary": None if latest_run is None else latest_run.get("summary"),
        "latest_failure_status": None
        if latest_failure is None
        else latest_failure.get("status"),
        "latest_failure_summary": None
        if latest_failure is None
        else latest_failure.get("summary"),
        "latest_failure_reason_code": None
        if not isinstance(result_payload, dict)
        else result_payload.get("reason_code"),
        "latest_failure_outcome": None
        if not isinstance(result_payload, dict)
        else result_payload.get("outcome"),
        "latest_failure_payload": result_payload,
        "latest_verification_passed": None
        if latest_failure is None
        else latest_failure.get("verification_passed"),
        "latest_verification_output_digest": None
        if latest_failure is None
        else latest_failure.get("verification_output_digest"),
    }


def _load_job_log_preview(log_path: Any, *, max_chars: int = 4000) -> dict[str, Any]:
    raw_path = str(log_path or "").strip()

    if not raw_path:
        return {
            "available": False,
            "reason": "missing_log_path",
            "content": "",
            "truncated": False,
        }

    path = Path(raw_path).expanduser().resolve()

    if not path.exists() or not path.is_file():
        return {
            "available": False,
            "reason": "missing_file",
            "content": "",
            "truncated": False,
            "path": str(path),
        }

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {
            "available": False,
            "reason": "unreadable",
            "content": "",
            "truncated": False,
            "path": str(path),
        }

    truncated = len(content) > max_chars

    return {
        "available": True,
        "reason": None,
        "content": content[:max_chars],
        "truncated": truncated,
        "path": str(path),
    }


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _normalize_value(value) for key, value in row.items()}


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_normalize_value(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def list_portfolio_summary(connection: Any) -> dict[str, Any]:
    try:
        rows = _fetch_all(
            connection,
            queries.LIST_PORTFOLIO_SUMMARY_QUERY,
        )
        return {"repos": [_normalize_row(row) for row in rows]}
    except psycopg.errors.UndefinedTable:
        return {"repos": []}


def list_ai_decisions(
    connection: Any,
    *,
    repo: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    try:
        if repo:
            rows = _fetch_all(
                connection,
                queries.LIST_AI_DECISIONS_WITH_REPO_QUERY,
                (repo, limit),
            )
        else:
            rows = _fetch_all(
                connection,
                queries.LIST_AI_DECISIONS_QUERY,
                (limit,),
            )
        return {"decisions": [_normalize_row(row) for row in rows]}
    except psycopg.errors.UndefinedTable:
        return {"decisions": []}


def list_notifications(
    connection: Any,
    *,
    repo: str | None = None,
    include_sent: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    try:
        query = _get_notification_query(repo, include_sent)
        params: tuple[Any, ...] = (repo, limit) if repo else (limit,)
        rows = _fetch_all(connection, query, params)
        return {"notifications": [_normalize_row(row) for row in rows]}
    except psycopg.errors.UndefinedTable:
        return {"notifications": []}


def list_agent_status(
    connection: Any,
    *,
    repo: str | None = None,
) -> dict[str, Any]:
    try:
        if repo:
            rows = _fetch_all(
                connection,
                queries.LIST_AGENT_STATUS_WITH_REPO_QUERY,
                (repo, repo),
            )
        else:
            rows = _fetch_all(
                connection,
                queries.LIST_AGENT_STATUS_QUERY,
            )
        return {"agents": [_normalize_row(row) for row in rows]}
    except psycopg.errors.UndefinedTable:
        return {"agents": []}


def get_failed_notifications(
    connection: Any, *, repo: str | None = None
) -> dict[str, Any]:
    try:
        if repo:
            rows = _fetch_all(
                connection,
                queries.GET_FAILED_NOTIFICATIONS_WITH_REPO_QUERY,
                (repo,),
            )
        else:
            rows = _fetch_all(
                connection,
                queries.GET_FAILED_NOTIFICATIONS_QUERY,
            )
        return {"notifications": [_normalize_row(row) for row in rows]}
    except psycopg.errors.UndefinedTable:
        return {"notifications": []}


def get_agent_efficiency_stats(connection: Any) -> dict[str, Any]:
    try:
        rows = _fetch_all(
            connection,
            queries.GET_AGENT_EFFICIENCY_STATS_QUERY,
        )
        return {"stats": [_normalize_row(row) for row in rows]}
    except psycopg.errors.UndefinedTable:
        return {"stats": []}


def _fetch_all(
    connection: Any, query: str, params: tuple[Any, ...] = ()
) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        return list(cursor.fetchall())


def _fetch_one(
    connection: Any, query: str, params: tuple[Any, ...] = ()
) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        row = cursor.fetchone()
    return None if row is None else dict(row)
