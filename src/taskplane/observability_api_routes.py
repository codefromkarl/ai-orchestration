from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from .hierarchy_api_support import get_hierarchy_api_module, open_connection

router = APIRouter()


def _close_connection(connection: Any) -> None:
    connection.close()


@router.get("/api/portfolio")
def get_portfolio_summary():
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.list_portfolio_summary(conn)
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/ai-decisions")
def get_ai_decisions(
    repo: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.list_ai_decisions(conn, repo=repo or "", limit=limit)
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/notifications")
def get_notifications(
    repo: str | None = Query(default=None),
    include_sent: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.list_notifications(
            conn,
            repo=repo or "",
            include_sent=include_sent,
            limit=limit,
        )
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/notifications/failed")
def get_failed_notifications_route(
    repo: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.get_failed_notifications(conn, repo=repo or "")
        notifications = payload.get("notifications", [])
        payload = {"notifications": notifications[:limit]}
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/agents")
def get_agent_status(
    repo: str | None = Query(default=None),
):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.list_agent_status(conn, repo=repo or "")
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/agents/stats")
def get_agent_efficiency_stats_route():
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.get_agent_efficiency_stats(conn)
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/repos/{repo}/tasks/{work_id}/timeline")
def task_timeline(repo: str, work_id: str, limit: int = Query(100, ge=1, le=1000)):
    conn = open_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT el.event_type, el.work_id, el.actor,
                       el.detail, el.created_at,
                       wi.title AS work_title
                FROM event_log el
                LEFT JOIN work_item wi ON wi.id = el.work_id
                WHERE el.work_id = %s
                ORDER BY el.created_at DESC
                LIMIT %s
                """,
                (work_id, limit),
            )
            events = [dict(r) for r in cur.fetchall()]
    finally:
        _close_connection(conn)
    return JSONResponse(
        {"work_id": work_id, "repo": repo, "events": events, "count": len(events)}
    )


@router.get("/api/repos/{repo}/events")
def global_events(
    repo: str, limit: int = Query(100, ge=1, le=1000), since: str | None = Query(None)
):
    conn = open_connection()
    try:
        with conn.cursor() as cur:
            if since:
                cur.execute(
                    """
                    SELECT el.id, el.event_type, el.work_id, el.actor,
                           el.detail, el.created_at,
                           wi.title AS work_title
                    FROM event_log el
                    LEFT JOIN work_item wi ON wi.id = el.work_id
                    WHERE el.created_at >= %s
                    ORDER BY el.created_at DESC
                    LIMIT %s
                    """,
                    (since, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT el.id, el.event_type, el.work_id, el.actor,
                           el.detail, el.created_at,
                           wi.title AS work_title
                    FROM event_log el
                    LEFT JOIN work_item wi ON wi.id = el.work_id
                    ORDER BY el.created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            events = [dict(r) for r in cur.fetchall()]
    finally:
        _close_connection(conn)
    return JSONResponse({"repo": repo, "events": events, "count": len(events)})


@router.get("/api/executors/routing")
def executor_routing_profiles():
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.list_executor_routing_profiles(conn)
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/repos/{repo:path}/executor-selections")
def executor_selection_events(repo: str, limit: int = Query(100, ge=1, le=1000)):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api.list_executor_selection_events(conn, repo=repo, limit=limit)
    finally:
        _close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/repos/{repo}/dlq")
def dlq_list(repo: str, limit: int = Query(50, ge=1, le=500)):
    conn = open_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT dlq.id, dlq.work_id, wi.title, dlq.original_status,
                       dlq.failure_reason, dlq.attempt_count,
                       dlq.moved_at, dlq.moved_by, dlq.resolution,
                       er.summary AS last_run_summary
                FROM dead_letter_queue dlq
                LEFT JOIN work_item wi ON wi.id = dlq.work_id
                LEFT JOIN execution_run er ON er.id = dlq.last_run_id
                WHERE dlq.resolution IS NULL
                ORDER BY dlq.moved_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            items = [dict(r) for r in cur.fetchall()]
    finally:
        _close_connection(conn)
    return JSONResponse({"repo": repo, "items": items, "count": len(items)})
