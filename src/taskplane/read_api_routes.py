from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from .hierarchy_api_support import get_hierarchy_api_module, open_connection

router = APIRouter()


def _close_connection(connection: Any) -> None:
    connection.close()


@router.get("/api/repos")
def get_repositories():
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.list_repositories(conn)
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/repos/{repo:path}/summary")
def get_repository_summary(repo: str):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.get_repo_summary(conn, repo=repo)
    except api.ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/repos/{repo:path}/epics")
def get_repository_epics(repo: str):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.list_epic_rows(conn, repo=repo)
    except api.ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/repos/{repo:path}/epic-story-tree")
def get_repository_epic_story_tree(repo: str):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.list_epic_story_tree(conn, repo=repo)
    except api.ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/repos/{repo:path}/jobs")
def get_repository_running_jobs(repo: str):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.list_running_jobs(conn, repo=repo)
    except api.ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/repos/{repo:path}/runtime-observability")
def get_repository_runtime_observability(repo: str):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.list_runtime_observability(conn, repo=repo)
    except api.ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/eval/v1/repos/{repo:path}/work-items")
def get_eval_export_work_items(
    repo: str,
    after_work_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.list_work_snapshot_exports(
            conn,
            repo=repo,
            after_work_id=after_work_id,
            limit=limit,
        )
    except api.ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/eval/v1/repos/{repo:path}/work-items/{work_id}")
def get_eval_export_work_item(repo: str, work_id: str):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.get_work_snapshot_export(conn, repo=repo, work_id=work_id)
    finally:
        _close_connection(conn)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"work item {work_id} not found in {repo}",
        )
    return JSONResponse(payload.to_dict())


@router.get("/api/eval/v1/repos/{repo:path}/attempts")
def get_eval_export_attempts(
    repo: str,
    after_run_id: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.list_execution_attempt_exports(
            conn,
            repo=repo,
            after_run_id=after_run_id,
            limit=limit,
        )
    except api.ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/eval/v1/repos/{repo:path}/verifications")
def get_eval_export_verifications(
    repo: str,
    after_id: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.list_verification_result_exports(
            conn,
            repo=repo,
            after_id=after_id,
            limit=limit,
        )
    except api.ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/repos/{repo:path}/epics/{epic_issue_number}")
def get_repository_epic_detail(repo: str, epic_issue_number: int):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.get_epic_detail(conn, repo=repo, epic_issue_number=epic_issue_number)
    except api.ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/repos/{repo:path}/stories/{story_issue_number}")
def get_repository_story_detail(repo: str, story_issue_number: int):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.get_story_detail(
            conn, repo=repo, story_issue_number=story_issue_number
        )
    except api.ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/repos/{repo:path}/tasks/{work_id}")
def get_repository_task_detail(repo: str, work_id: str):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.get_task_detail(conn, repo=repo, work_id=work_id)
    except api.ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/repos/{repo:path}/jobs/{job_id}")
def get_repository_job_detail(repo: str, job_id: int):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.get_job_detail(conn, repo=repo, job_id=job_id)
    except api.ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/repos/{repo:path}/work-items")
def get_work_items(repo: str, status: str = Query(default="all")):
    conn = open_connection()
    try:
        with conn.cursor() as cur:
            if status == "all":
                cur.execute(
                    """
                    SELECT
                        wi.id,
                        wi.source_issue_number,
                        wi.title,
                        wi.status,
                        wi.canonical_story_issue_number,
                        wi.blocked_reason,
                        wi.task_type
                    FROM work_item wi
                    WHERE wi.repo = %s
                    ORDER BY wi.source_issue_number
                    """,
                    (repo,),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        wi.id,
                        wi.source_issue_number,
                        wi.title,
                        wi.status,
                        wi.canonical_story_issue_number,
                        wi.blocked_reason,
                        wi.task_type
                    FROM work_item wi
                    WHERE wi.repo = %s AND wi.status = %s
                    ORDER BY wi.source_issue_number
                    """,
                    (repo, status),
                )
            items = [dict(r) for r in cur.fetchall()]
    finally:
        _close_connection(conn)
    return JSONResponse({"repo": repo, "items": items, "count": len(items)})
