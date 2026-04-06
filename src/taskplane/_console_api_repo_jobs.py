from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import console_queries as queries
from ._console_api_internal import (
    _fetch_all,
    _fetch_one,
    _load_job_log_preview,
    _normalize_row,
    _require_repo,
)
from .contextatlas_indexing import (
    CheckoutAliasRecord,
    FileIndexRegistry,
    _default_registry_path,
)


def get_repo_summary(connection: Any, *, repo: str) -> dict[str, Any]:
    _require_repo(connection, repo)
    summary_row = _fetch_one(connection, queries.GET_REPO_SUMMARY_QUERY, (repo,) * 15)

    return {
        "repo": repo,
        "summary": _normalize_row(summary_row or {}),
        "snapshot_health": _normalize_row(_build_repo_snapshot_health(repo=repo)),
        "epic_status_counts": _load_status_counts(
            connection, fetch_all=_fetch_all, table="program_epic", repo=repo
        ),
        "story_status_counts": _load_status_counts(
            connection, fetch_all=_fetch_all, table="program_story", repo=repo
        ),
        "task_status_counts": _load_status_counts(
            connection, fetch_all=_fetch_all, table="work_item", repo=repo
        ),
    }


def get_job_detail(connection: Any, *, repo: str, job_id: int) -> dict[str, Any]:
    from .console_api import ConsoleNotFoundError

    job = _fetch_one(
        connection,
        queries.GET_JOB_DETAIL_QUERY,
        (repo, job_id),
    )

    if job is None:
        raise ConsoleNotFoundError(f"job #{job_id} not found in {repo}")

    story = None
    if job.get("story_issue_number") is not None:
        story = _fetch_one(
            connection,
            queries.GET_JOB_STORY_DETAIL_QUERY,
            (repo, job["story_issue_number"]),
        )

    task = None
    if job.get("work_id") is not None:
        task = _fetch_one(
            connection,
            queries.GET_JOB_TASK_DETAIL_QUERY,
            (repo, job["work_id"]),
        )

    log_preview = _load_job_log_preview(job.get("log_path"))

    return {
        "repo": repo,
        "job": _normalize_row(job),
        "story": _normalize_row(story or {}),
        "task": _normalize_row(task or {}),
        "log_preview": _normalize_row(log_preview),
    }


def get_repo_snapshot_health(*, repo: str) -> dict[str, Any]:
    return _normalize_row(_build_repo_snapshot_health(repo=repo))


def _load_status_counts(
    connection: Any,
    *,
    fetch_all: Any,
    table: str,
    repo: str,
) -> list[dict[str, Any]]:
    if table in {"program_epic", "program_story"}:
        query = queries.GET_STATUS_COUNTS_EXECUTION_QUERY
    else:
        query = queries.GET_STATUS_COUNTS_STATUS_QUERY

    rows = fetch_all(connection, query.format(table=table), (repo,))
    return [_normalize_row(row) for row in rows]


def _build_repo_snapshot_health(*, repo: str) -> dict[str, Any]:
    registry = FileIndexRegistry(_default_registry_path())
    repository_id = f"control:{repo}"
    matching = [
        (snapshot_id, schema_version)
        for key_repo, snapshot_id, schema_version in registry.list_snapshot_keys()
        if key_repo == repository_id
    ]
    if not matching:
        return {
            "status": "missing",
            "summary": "No snapshot has been indexed for this repository yet.",
            "repository_id": repository_id,
            "snapshot_id": None,
            "schema_version": None,
            "artifact_status": None,
            "artifact_age_seconds": None,
            "lock_age_seconds": None,
            "lock_is_stale": False,
            "observed_at": datetime.now(UTC).isoformat(),
        }

    def _ranking_key(item: tuple[str, str]) -> tuple[int, float, float]:
        snapshot_id, schema_version = item
        observation = registry.inspect_snapshot(
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            schema_version=schema_version,
        )
        artifact_status = observation.artifact.status if observation.artifact else None
        status_rank = {
            "ready": 5,
            "building": 4,
            "failed": 3,
            None: 2,
        }.get(artifact_status, 1)
        artifact_age = -(observation.artifact_age_seconds or 0.0)
        lock_age = -(observation.lock_age_seconds or 0.0)
        return (status_rank, artifact_age, lock_age)

    snapshot_id, schema_version = max(matching, key=_ranking_key)
    observation = registry.inspect_snapshot(
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        schema_version=schema_version,
    )
    checkout_paths = registry.list_checkout_paths_for_snapshot(
        repository_id=repository_id,
        snapshot_id=snapshot_id,
    )
    artifact_status = observation.artifact.status if observation.artifact else None
    if artifact_status == "ready":
        status = "ready"
        summary = (
            f"Ready and reusable across {len(checkout_paths)} checkout(s)."
            if checkout_paths
            else "Ready and reusable."
        )
    elif artifact_status == "failed":
        status = "failed"
        summary = (
            observation.artifact.last_error
            if observation.artifact is not None and observation.artifact.last_error
            else "Last snapshot build failed."
        )
    elif observation.lock_exists and observation.lock_is_stale:
        status = "stale_lock"
        summary = "Stale snapshot build lock detected."
    elif artifact_status == "building" or observation.lock_exists:
        status = "building"
        summary = "Snapshot build in progress."
    else:
        status = "unknown"
        summary = "Snapshot state is currently unknown."
    return {
        "status": status,
        "summary": summary,
        "repository_id": repository_id,
        "snapshot_id": snapshot_id,
        "schema_version": schema_version,
        "artifact_status": artifact_status,
        "artifact_age_seconds": observation.artifact_age_seconds,
        "lock_age_seconds": observation.lock_age_seconds,
        "lock_is_stale": observation.lock_is_stale,
        "observed_at": datetime.now(UTC).isoformat(),
    }
