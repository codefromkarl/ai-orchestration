from __future__ import annotations

from importlib import import_module
import os
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

_console_read_api = import_module("taskplane.console_read_api")
_console_actions = import_module("taskplane.console_actions")
_governance_priority_api = import_module(
    "taskplane.governance_priority_api"
)
_governance_health = import_module("taskplane.governance_health")
_orphan_coordinator = import_module("taskplane.orphan_coordinator")
_auto_split_trigger = import_module("taskplane.auto_split_trigger")
_governance_decision_engine = import_module(
    "taskplane.governance_decision_engine"
)
ConsoleNotFoundError = _console_read_api.ConsoleNotFoundError
ConsoleActionConfigurationError = _console_actions.ConsoleActionConfigurationError
ConsoleActionConflictError = _console_actions.ConsoleActionConflictError
get_epic_detail = _console_read_api.get_epic_detail
get_repo_summary = _console_read_api.get_repo_summary
get_story_detail = _console_read_api.get_story_detail
get_task_detail = _console_read_api.get_task_detail
get_job_detail = _console_read_api.get_job_detail
list_epic_rows = _console_read_api.list_epic_rows
list_epic_story_tree = _console_read_api.list_epic_story_tree
list_running_jobs = _console_read_api.list_running_jobs
list_runtime_observability = _console_read_api.list_runtime_observability
list_executor_routing_profiles = _console_read_api.list_executor_routing_profiles
list_executor_selection_events = _console_read_api.list_executor_selection_events
list_repositories = _console_read_api.list_repositories
run_epic_split_action = _console_actions.run_epic_split_action
run_story_split_action = _console_actions.run_story_split_action
run_task_retry_action = _console_actions.run_task_retry_action
# New multi-project API endpoints
list_portfolio_summary = _console_read_api.list_portfolio_summary
list_ai_decisions = _console_read_api.list_ai_decisions
list_notifications = _console_read_api.list_notifications
list_agent_status = _console_read_api.list_agent_status
get_failed_notifications = _console_read_api.get_failed_notifications
get_agent_efficiency_stats = _console_read_api.get_agent_efficiency_stats

app = FastAPI(title="Stardrifter Issue Hierarchy")

_STATIC_DIR = Path(__file__).parent / "static"


def _read_html_asset(filename: str, repo: str = "") -> str:
    html_path = _STATIC_DIR / filename
    if not html_path.exists():
        raise HTTPException(status_code=500, detail=f"{filename} not found")
    html = html_path.read_text(encoding="utf-8")
    return html.replace('"__DEFAULT_REPO__"', f'"{repo}"')


def _get_connection() -> Any:
    dsn = os.getenv("TASKPLANE_DSN", "").strip()
    if not dsn:
        raise RuntimeError("TASKPLANE_DSN is required")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("psycopg is required") from exc
    return cast(Any, psycopg.connect(dsn, row_factory=cast(Any, dict_row)))


def _load_issues(conn: Any, repo: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT issue_number, title, body, url, github_state,
                   issue_kind, lane, complexity, status_label,
                   explicit_parent_issue_numbers,
                   explicit_story_dependency_issue_numbers,
                   explicit_task_dependency_issue_numbers
            FROM github_issue_normalized
            WHERE repo = %s
            ORDER BY issue_number
            """,
            (repo,),
        )
        return cur.fetchall()


def _load_work_items_by_issue(conn: Any, repo: str) -> dict[int, dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_issue_number, id, status, wave, lane,
                   blocked_reason, decision_required
            FROM work_item
            WHERE source_issue_number IS NOT NULL
              AND repo = %s
            """,
            (repo,),
        )
        rows = cur.fetchall()
    return {r["source_issue_number"]: dict(r) for r in rows}


def _load_relations(conn: Any, repo: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_issue_number, target_issue_number, relation_type, confidence
            FROM github_issue_relation
            WHERE repo = %s
            """,
            (repo,),
        )
        return cur.fetchall()


def _build_node(issue: dict, work_map: dict[int, dict], children: list) -> dict:
    num = issue["issue_number"]
    wi = work_map.get(num)
    return {
        "issue_number": num,
        "title": issue["title"],
        "issue_kind": issue["issue_kind"] or "unknown",
        "github_state": issue["github_state"],
        "status_label": issue["status_label"],
        "url": issue["url"],
        "lane": issue["lane"],
        "complexity": issue["complexity"],
        "work_status": wi["status"] if wi else None,
        "blocked_reason": wi["blocked_reason"] if wi else None,
        "decision_required": wi["decision_required"] if wi else False,
        "children": children,
    }


@app.get("/", response_class=HTMLResponse)
def index(repo: str = Query(default="")):
    return HTMLResponse(content=_read_html_asset("console.html", repo=repo))


@app.get("/console", response_class=HTMLResponse)
def console_index(repo: str = Query(default="")):
    return HTMLResponse(content=_read_html_asset("console.html", repo=repo))


@app.get("/hierarchy", response_class=HTMLResponse)
def hierarchy_index(repo: str = Query(default="")):
    return HTMLResponse(content=_read_html_asset("hierarchy.html", repo=repo))


@app.get("/console.css")
def console_css():
    css_path = _STATIC_DIR / "console.css"
    if not css_path.exists():
        raise HTTPException(status_code=500, detail="console.css not found")
    return HTMLResponse(
        content=css_path.read_text(encoding="utf-8"), media_type="text/css"
    )


@app.get("/console.bundle.js")
def console_bundle_js():
    js_path = _STATIC_DIR / "console.bundle.js"
    if not js_path.exists():
        raise HTTPException(status_code=500, detail="console.bundle.js not found")
    return HTMLResponse(
        content=js_path.read_text(encoding="utf-8"),
        media_type="application/javascript",
    )


@app.get("/api/hierarchy")
def get_hierarchy(repo: str = Query(..., description="GitHub repo slug owner/repo")):
    try:
        conn = _get_connection()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    try:
        issues = _load_issues(conn, repo)
        work_map = _load_work_items_by_issue(conn, repo)
    finally:
        conn.close()

    by_number: dict[int, dict] = {r["issue_number"]: dict(r) for r in issues}

    stories_by_epic: dict[int, list[dict]] = {}
    tasks_by_story: dict[int, list[dict]] = {}
    claimed_stories: set[int] = set()
    claimed_tasks: set[int] = set()

    for issue in issues:
        parents = list(issue["explicit_parent_issue_numbers"] or [])
        kind = issue["issue_kind"]
        if kind == "story":
            for p in parents:
                if p in by_number and by_number[p]["issue_kind"] == "epic":
                    stories_by_epic.setdefault(p, []).append(dict(issue))
                    claimed_stories.add(issue["issue_number"])
                    break
        elif kind == "task":
            for p in parents:
                if p in by_number and by_number[p]["issue_kind"] == "story":
                    tasks_by_story.setdefault(p, []).append(dict(issue))
                    claimed_tasks.add(issue["issue_number"])
                    break

    epics = []
    for issue in issues:
        if issue["issue_kind"] != "epic":
            continue
        story_nodes = []
        for story in stories_by_epic.get(issue["issue_number"], []):
            task_nodes = [
                _build_node(t, work_map, [])
                for t in tasks_by_story.get(story["issue_number"], [])
            ]
            story_nodes.append(_build_node(story, work_map, task_nodes))
        epics.append(_build_node(dict(issue), work_map, story_nodes))

    orphan_stories = [
        _build_node(
            dict(i),
            work_map,
            [
                _build_node(t, work_map, [])
                for t in tasks_by_story.get(i["issue_number"], [])
            ],
        )
        for i in issues
        if i["issue_kind"] == "story" and i["issue_number"] not in claimed_stories
    ]
    orphan_tasks = [
        _build_node(dict(i), work_map, [])
        for i in issues
        if i["issue_kind"] == "task" and i["issue_number"] not in claimed_tasks
    ]

    return JSONResponse(
        {
            "repo": repo,
            "epics": epics,
            "orphan_stories": orphan_stories,
            "orphan_tasks": orphan_tasks,
        }
    )


@app.get("/api/issue/{number}")
def get_issue(number: int, repo: str = Query(...)):
    try:
        conn = _get_connection()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT issue_number, title, body, url, github_state,
                       issue_kind, lane, complexity, status_label,
                       explicit_parent_issue_numbers,
                       explicit_story_dependency_issue_numbers,
                       explicit_task_dependency_issue_numbers
                FROM github_issue_normalized
                WHERE repo = %s AND issue_number = %s
                """,
                (repo, number),
            )
            row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"issue #{number} not found")
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, status, wave, lane, blocked_reason, decision_required
                FROM work_item
                WHERE source_issue_number = %s AND repo = %s
                ORDER BY id LIMIT 1
                """,
                (number, repo),
            )
            wi = cur.fetchone()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_issue_number AS num, relation_type, 'outgoing' AS dir
                FROM github_issue_relation
                WHERE repo = %s AND target_issue_number = %s
                UNION ALL
                SELECT target_issue_number, relation_type, 'incoming'
                FROM github_issue_relation
                WHERE repo = %s AND source_issue_number = %s
                """,
                (repo, number, repo, number),
            )
            relations = cur.fetchall()
    finally:
        conn.close()

    return JSONResponse(
        {
            "issue_number": row["issue_number"],
            "title": row["title"],
            "issue_kind": row["issue_kind"],
            "github_state": row["github_state"],
            "body": (row["body"] or "")[:500],
            "url": row["url"],
            "lane": row["lane"],
            "complexity": row["complexity"],
            "status_label": row["status_label"],
            "parents": list(row["explicit_parent_issue_numbers"] or []),
            "work_item": dict(wi) if wi else None,
            "relations": [
                {"number": r["num"], "type": r["relation_type"], "dir": r["dir"]}
                for r in relations
            ],
        }
    )


@app.get("/api/repos")
def get_repositories():
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = list_repositories(conn)
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/repos/{repo:path}/summary")
def get_repository_summary(repo: str):
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = get_repo_summary(conn, repo=repo)
    except ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/repos/{repo:path}/epics")
def get_repository_epics(repo: str):
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = list_epic_rows(conn, repo=repo)
    except ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/repos/{repo:path}/epic-story-tree")
def get_repository_epic_story_tree(repo: str):
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = list_epic_story_tree(conn, repo=repo)
    except ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/repos/{repo:path}/jobs")
def get_repository_running_jobs(repo: str):
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = list_running_jobs(conn, repo=repo)
    except ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/repos/{repo:path}/runtime-observability")
def get_repository_runtime_observability(repo: str):
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = list_runtime_observability(conn, repo=repo)
    except ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/repos/{repo:path}/epics/{epic_issue_number}")
def get_repository_epic_detail(repo: str, epic_issue_number: int):
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = get_epic_detail(conn, repo=repo, epic_issue_number=epic_issue_number)
    except ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/repos/{repo:path}/stories/{story_issue_number}")
def get_repository_story_detail(repo: str, story_issue_number: int):
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = get_story_detail(
            conn, repo=repo, story_issue_number=story_issue_number
        )
    except ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/repos/{repo:path}/tasks/{work_id}")
def get_repository_task_detail(repo: str, work_id: str):
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = get_task_detail(conn, repo=repo, work_id=work_id)
    except ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/repos/{repo:path}/jobs/{job_id}")
def get_repository_job_detail(repo: str, job_id: int):
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = get_job_detail(conn, repo=repo, job_id=job_id)
    except ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        conn.close()
    return JSONResponse(payload)


@app.post("/api/repos/{repo:path}/epics/{epic_issue_number}/split")
def post_repository_epic_split(repo: str, epic_issue_number: int):
    try:
        payload = run_epic_split_action(repo=repo, epic_issue_number=epic_issue_number)
    except ConsoleActionConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ConsoleActionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return JSONResponse(payload)


@app.post("/api/repos/{repo:path}/stories/{story_issue_number}/split")
def post_repository_story_split(repo: str, story_issue_number: int):
    try:
        payload = run_story_split_action(
            repo=repo, story_issue_number=story_issue_number
        )
    except ConsoleActionConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ConsoleActionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return JSONResponse(payload)


@app.post("/api/repos/{repo:path}/tasks/{work_id}/retry")
def post_repository_task_retry(repo: str, work_id: str):
    try:
        payload = run_task_retry_action(repo=repo, work_id=work_id)
    except ConsoleActionConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except ConsoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ConsoleActionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return JSONResponse(payload)


# =============================================================================
# Multi-Project API Endpoints (新增多项目 API 端点)
# =============================================================================


@app.get("/api/portfolio")
def get_portfolio_summary():
    """Get multi-project portfolio summary."""
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = list_portfolio_summary(conn)
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/ai-decisions")
def get_ai_decisions(
    repo: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get AI decision history."""
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = list_ai_decisions(conn, repo=repo or "", limit=limit)
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/notifications")
def get_notifications(
    repo: str | None = Query(default=None),
    include_sent: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Get notification status."""
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = list_notifications(
            conn,
            repo=repo or "",
            include_sent=include_sent,
            limit=limit,
        )
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/notifications/failed")
def get_failed_notifications_route(
    repo: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = get_failed_notifications(conn, repo=repo or "")
        notifications = payload.get("notifications", [])
        payload = {"notifications": notifications[:limit]}
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/agents")
def get_agent_status(
    repo: str | None = Query(default=None),
):
    """Get agent execution status."""
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = list_agent_status(conn, repo=repo or "")
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/agents/stats")
def get_agent_efficiency_stats_route():
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = get_agent_efficiency_stats(conn)
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/repos/{repo:path}/governance/priority")
def get_governance_priority(repo: str):
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        from datetime import datetime, timezone

        snapshot = _governance_priority_api.load_priority_snapshot(
            connection=conn,
            repo=repo,
        )
        payload = _governance_priority_api.build_api_response(
            repo=repo,
            snapshot=snapshot,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/repos/{repo:path}/governance/health")
def get_governance_health(repo: str):
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        from datetime import datetime, timezone

        metrics = _governance_health.load_health_metrics(
            connection=conn,
            repo=repo,
        )
        health = _governance_health.compute_health_score(metrics=metrics)
        payload = _governance_health.build_health_response(
            repo=repo,
            metrics=metrics,
            health=health,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
    finally:
        conn.close()
    return JSONResponse(payload)


@app.post("/api/repos/{repo:path}/governance/orphans/resolve")
def resolve_governance_orphans(repo: str, dry_run: bool = Query(default=False)):
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = _orphan_coordinator.resolve_orphans(
            connection=conn,
            repo=repo,
            dry_run=dry_run,
        )
    finally:
        conn.close()
    return JSONResponse(payload)


@app.post("/api/repos/{repo:path}/governance/auto-split/evaluate")
def evaluate_auto_splits_endpoint(repo: str):
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = _auto_split_trigger.evaluate_auto_splits(
            connection=conn,
            repo=repo,
        )
    finally:
        conn.close()
    return JSONResponse(payload)


@app.post("/api/repos/{repo:path}/governance/decide")
def run_governance_decisions(repo: str, dry_run: bool = Query(default=False)):
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = _governance_decision_engine.evaluate_decisions(
            connection=conn,
            repo=repo,
            dry_run=dry_run,
        )
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/repos/{repo:path}/work-items")
def get_work_items(repo: str, status: str = Query(default="all")):
    try:
        conn = _get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
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
        conn.close()
    return JSONResponse({"repo": repo, "items": items, "count": len(items)})


@app.get("/api/repos/{repo}/tasks/{work_id}/timeline")
def task_timeline(repo: str, work_id: str, limit: int = Query(100, ge=1, le=1000)):
    conn = _get_connection()
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
        conn.close()
    return JSONResponse(
        {"work_id": work_id, "repo": repo, "events": events, "count": len(events)}
    )


@app.get("/api/repos/{repo}/events")
def global_events(
    repo: str, limit: int = Query(100, ge=1, le=1000), since: str | None = Query(None)
):
    conn = _get_connection()
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
        conn.close()
    return JSONResponse({"repo": repo, "events": events, "count": len(events)})


@app.get("/api/executors/routing")
def executor_routing_profiles():
    conn = _get_connection()
    try:
        payload = list_executor_routing_profiles(conn)
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/repos/{repo:path}/executor-selections")
def executor_selection_events(
    repo: str, limit: int = Query(100, ge=1, le=1000)
):
    conn = _get_connection()
    try:
        payload = list_executor_selection_events(conn, repo=repo, limit=limit)
    finally:
        conn.close()
    return JSONResponse(payload)


@app.get("/api/repos/{repo}/dlq")
def dlq_list(repo: str, limit: int = Query(50, ge=1, le=500)):
    conn = _get_connection()
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
        conn.close()
    return JSONResponse({"repo": repo, "items": items, "count": len(items)})
