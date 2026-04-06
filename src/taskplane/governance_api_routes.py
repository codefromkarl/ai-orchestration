from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from .hierarchy_api_support import close_connection, get_hierarchy_api_module, open_connection

router = APIRouter()


@router.get("/api/repos/{repo:path}/governance/priority")
def get_governance_priority(repo: str):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        snapshot = api._governance_priority_api.load_priority_snapshot(
            connection=conn,
            repo=repo,
        )
        payload = api._governance_priority_api.build_api_response(
            repo=repo,
            snapshot=snapshot,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
    finally:
        close_connection(conn)
    return JSONResponse(payload)


@router.get("/api/repos/{repo:path}/governance/health")
def get_governance_health(repo: str):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        metrics = api._governance_health.load_health_metrics(
            connection=conn,
            repo=repo,
        )
        health = api._governance_health.compute_health_score(metrics=metrics)
        payload = api._governance_health.build_health_response(
            repo=repo,
            metrics=metrics,
            health=health,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
    finally:
        close_connection(conn)
    return JSONResponse(payload)


@router.post("/api/repos/{repo:path}/governance/orphans/resolve")
def resolve_governance_orphans(repo: str, dry_run: bool = Query(default=False)):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api._orphan_coordinator.resolve_orphans(
            connection=conn,
            repo=repo,
            dry_run=dry_run,
        )
    finally:
        close_connection(conn)
    return JSONResponse(payload)


@router.post("/api/repos/{repo:path}/governance/auto-split/evaluate")
def evaluate_auto_splits_endpoint(repo: str):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api._auto_split_trigger.evaluate_auto_splits(
            connection=conn,
            repo=repo,
        )
    finally:
        close_connection(conn)
    return JSONResponse(payload)


@router.post("/api/repos/{repo:path}/governance/decide")
def run_governance_decisions(repo: str, dry_run: bool = Query(default=False)):
    api = get_hierarchy_api_module()
    conn = open_connection()
    try:
        payload = api._governance_decision_engine.evaluate_decisions(
            connection=conn,
            repo=repo,
            dry_run=dry_run,
        )
    finally:
        close_connection(conn)
    return JSONResponse(payload)
