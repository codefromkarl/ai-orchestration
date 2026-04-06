from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from .hierarchy_api_support import get_hierarchy_api_module

router = APIRouter()


def _handle_action_errors(exc: Exception) -> None:
    api = get_hierarchy_api_module()
    if isinstance(exc, api.ConsoleActionConfigurationError):
        raise HTTPException(status_code=500, detail=str(exc))
    if isinstance(exc, api.ConsoleNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, api._console_actions.ConsoleActionNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, api.ConsoleActionConflictError):
        raise HTTPException(status_code=409, detail=str(exc))
    raise exc


@router.post("/api/repos/{repo:path}/epics/{epic_issue_number}/split")
def post_repository_epic_split(repo: str, epic_issue_number: int):
    api = get_hierarchy_api_module()
    try:
        payload = api.run_epic_split_action(
            repo=repo, epic_issue_number=epic_issue_number
        )
    except Exception as exc:
        _handle_action_errors(exc)
    return JSONResponse(payload)


@router.post("/api/repos/{repo:path}/stories/{story_issue_number}/split")
def post_repository_story_split(repo: str, story_issue_number: int):
    api = get_hierarchy_api_module()
    try:
        payload = api.run_story_split_action(
            repo=repo, story_issue_number=story_issue_number
        )
    except Exception as exc:
        _handle_action_errors(exc)
    return JSONResponse(payload)


@router.post("/api/repos/{repo:path}/tasks/{work_id}/retry")
def post_repository_task_retry(repo: str, work_id: str):
    api = get_hierarchy_api_module()
    try:
        payload = api.run_task_retry_action(repo=repo, work_id=work_id)
    except Exception as exc:
        _handle_action_errors(exc)
    return JSONResponse(payload)


@router.post(
    "/api/repos/{repo:path}/epics/{epic_issue_number}/operator-requests/{reason_code}/ack"
)
def post_operator_request_ack(
    repo: str,
    epic_issue_number: int,
    reason_code: str,
):
    api = get_hierarchy_api_module()
    try:
        payload = api.run_operator_request_ack_action(
            repo=repo,
            epic_issue_number=epic_issue_number,
            reason_code=reason_code,
        )
    except Exception as exc:
        _handle_action_errors(exc)
    return JSONResponse(payload)
