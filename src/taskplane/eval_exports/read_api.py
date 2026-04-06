from __future__ import annotations

from typing import Any, Callable

from .._console_api_internal import _normalize_row
from typing import cast

from ..models import ExecutionRun, VerificationEvidence, WorkStatus
from ..repository._postgres_row_mapping import row_to_work_item, value, value_optional
from .api import build_collection_response
from .queries import (
    GET_WORK_SNAPSHOT_EXPORT_QUERY,
    LIST_EXECUTION_ATTEMPT_EXPORTS_QUERY,
    LIST_VERIFICATION_RESULT_EXPORTS_QUERY,
    LIST_WORK_SNAPSHOT_EXPORTS_QUERY,
)
from .serializers import (
    serialize_execution_attempt,
    serialize_verification_result,
    serialize_work_snapshot,
)


def _fetch_all(
    connection: Any, query: str, params: tuple[Any, ...]
) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        return list(cursor.fetchall())


def _fetch_one(
    connection: Any, query: str, params: tuple[Any, ...]
) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        row = cursor.fetchone()
    return None if row is None else dict(row)


def list_work_snapshot_exports(
    connection: Any,
    *,
    repo: str,
    after_work_id: str | None = None,
    limit: int = 100,
    row_fetcher: Callable[..., list[dict[str, Any]]] | None = None,
    emitted_at: str | None = None,
) -> dict[str, Any]:
    fetcher = row_fetcher or _load_work_snapshot_rows
    rows = fetcher(connection, repo, after_work_id, limit)
    return _build_paginated_collection_response(
        rows,
        limit=limit,
        mapper=lambda row: serialize_work_snapshot(row_to_work_item(row)),
        cursor_builder=_work_snapshot_cursor,
        emitted_at=emitted_at,
    )


def get_work_snapshot_export(
    connection: Any,
    *,
    repo: str,
    work_id: str,
    row_fetcher: Callable[..., dict[str, Any] | None] | None = None,
) -> Any:
    fetcher = row_fetcher or _load_single_work_snapshot_row
    row = fetcher(connection, repo, work_id)
    if row is None:
        return None
    return serialize_work_snapshot(row_to_work_item(row))


def list_execution_attempt_exports(
    connection: Any,
    *,
    repo: str,
    after_run_id: int | None = None,
    limit: int = 100,
    row_fetcher: Callable[..., list[dict[str, Any]]] | None = None,
    emitted_at: str | None = None,
) -> dict[str, Any]:
    fetcher = row_fetcher or _load_execution_attempt_rows
    rows = fetcher(connection, repo, after_run_id, limit)
    return _build_paginated_collection_response(
        rows,
        limit=limit,
        mapper=_map_execution_attempt_row,
        cursor_builder=lambda page_rows: _numeric_cursor(page_rows, key="id"),
        emitted_at=emitted_at,
    )


def list_verification_result_exports(
    connection: Any,
    *,
    repo: str,
    after_id: int | None = None,
    limit: int = 100,
    row_fetcher: Callable[..., list[dict[str, Any]]] | None = None,
    emitted_at: str | None = None,
) -> dict[str, Any]:
    fetcher = row_fetcher or _load_verification_result_rows
    rows = fetcher(connection, repo, after_id, limit)
    return _build_paginated_collection_response(
        rows,
        limit=limit,
        mapper=_map_verification_result_row,
        cursor_builder=lambda page_rows: _numeric_cursor(page_rows, key="id"),
        emitted_at=emitted_at,
    )


def _load_work_snapshot_rows(
    connection: Any, repo: str, after_work_id: str | None, limit: int
) -> list[dict[str, Any]]:
    return _fetch_all(
        connection,
        LIST_WORK_SNAPSHOT_EXPORTS_QUERY,
        (repo, after_work_id, after_work_id, limit + 1),
    )


def _load_single_work_snapshot_row(
    connection: Any, repo: str, work_id: str
) -> dict[str, Any] | None:
    return _fetch_one(connection, GET_WORK_SNAPSHOT_EXPORT_QUERY, (repo, work_id))


def _load_execution_attempt_rows(
    connection: Any, repo: str, after_run_id: int | None, limit: int
) -> list[dict[str, Any]]:
    return _fetch_all(
        connection,
        LIST_EXECUTION_ATTEMPT_EXPORTS_QUERY,
        (repo, after_run_id, after_run_id, limit + 1),
    )


def _load_verification_result_rows(
    connection: Any, repo: str, after_id: int | None, limit: int
) -> list[dict[str, Any]]:
    return _fetch_all(
        connection,
        LIST_VERIFICATION_RESULT_EXPORTS_QUERY,
        (repo, after_id, after_id, limit + 1),
    )


def _normalized_optional(row: dict[str, Any], key: str) -> str | None:
    value_raw = value_optional(row, key)
    if value_raw is None:
        return None
    return _normalize_row({key: value_raw}).get(key)


def _numeric_cursor(rows: list[dict[str, Any]], *, key: str) -> str | None:
    if not rows:
        return None
    return str(value(rows[-1], key))


def _work_snapshot_cursor(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    return str(value(rows[-1], "id"))


def _trim_page(
    rows: list[dict[str, Any]], *, limit: int
) -> tuple[list[dict[str, Any]], bool]:
    if len(rows) > limit:
        return rows[:limit], True
    return rows, False


def _build_paginated_collection_response(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    mapper: Callable[[dict[str, Any]], Any],
    cursor_builder: Callable[[list[dict[str, Any]]], str | None],
    emitted_at: str | None,
) -> dict[str, Any]:
    page_rows, has_more = _trim_page(rows, limit=limit)
    items = [mapper(row) for row in page_rows]
    payload = build_collection_response(
        items,
        next_cursor=cursor_builder(page_rows) if has_more else None,
        has_more=has_more,
    )
    if emitted_at is not None:
        payload["emitted_at"] = emitted_at
    return payload


def _map_execution_attempt_row(row: dict[str, Any]) -> Any:
    return serialize_execution_attempt(
        ExecutionRun(
            work_id=str(value(row, "work_id")),
            worker_name=str(value(row, "worker_name")),
            status=cast(WorkStatus, value(row, "status")),
            branch_name=value_optional(row, "branch_name"),
            command_digest=value_optional(row, "command_digest"),
            exit_code=value_optional(row, "exit_code"),
            elapsed_ms=value_optional(row, "elapsed_ms"),
            stdout_digest=str(value_optional(row, "stdout_digest") or ""),
            stderr_digest=str(value_optional(row, "stderr_digest") or ""),
            result_payload_json=value_optional(row, "result_payload_json"),
        ),
        run_id=int(value(row, "id")),
        attempt_number=int(value_optional(row, "attempt_number") or 0),
        started_at=_normalized_optional(row, "started_at"),
        finished_at=_normalized_optional(row, "finished_at"),
    )


def _map_verification_result_row(row: dict[str, Any]) -> Any:
    return serialize_verification_result(
        VerificationEvidence(
            work_id=str(value(row, "work_id")),
            check_type=str(value(row, "check_type")),
            command=str(value(row, "command")),
            passed=bool(value(row, "passed")),
            output_digest=str(value(row, "output_digest")),
            run_id=int(value(row, "run_id")),
            exit_code=value_optional(row, "exit_code"),
            elapsed_ms=value_optional(row, "elapsed_ms"),
            stdout_digest=str(value_optional(row, "stdout_digest") or ""),
            stderr_digest=str(value_optional(row, "stderr_digest") or ""),
        ),
        attempt_number=int(value_optional(row, "attempt_number") or 0),
        verifier_name="task_verifier",
    )
