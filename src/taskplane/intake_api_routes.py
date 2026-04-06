from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .hierarchy_api_support import close_repository_connection, get_hierarchy_api_module

router = APIRouter()


def list_natural_language_intents(connection: Any, *, repo: str) -> dict[str, Any]:
    api = get_hierarchy_api_module()
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT id, repo, prompt, status, conversation_json, summary,
                   clarification_questions_json, proposal_json, analysis_model,
                   promoted_epic_issue_number, created_at, updated_at,
                   approved_at, approved_by,
                   reviewed_at, reviewed_by, review_action, review_feedback
            FROM natural_language_intent
            WHERE repo = %s
            ORDER BY created_at DESC, id DESC
            """,
            (repo,),
        )
        rows = [
            {key: api._normalize_value(value) for key, value in dict(row).items()}
            for row in cur.fetchall()
        ]
    return {"repo": repo, "items": rows, "count": len(rows)}


class IntentSubmitRequest(BaseModel):
    prompt: str


class IntentAnswerRequest(BaseModel):
    answer: str


class IntentApproveRequest(BaseModel):
    approver: str = "operator"


class IntentRejectRequest(BaseModel):
    reviewer: str = "operator"
    reason: str


class IntentReviseRequest(BaseModel):
    reviewer: str = "operator"
    feedback: str


def serialize_intent(intent: Any) -> dict[str, Any]:
    return {
        "intent_id": intent.id,
        "repo": intent.repo,
        "status": intent.status,
        "summary": intent.summary,
        "questions": list(intent.clarification_questions),
        "proposal": intent.proposal_json,
        "promoted_epic_issue_number": intent.promoted_epic_issue_number,
        "approved_by": intent.approved_by,
        "reviewed_by": getattr(intent, "reviewed_by", None),
        "review_action": getattr(intent, "review_action", None),
        "review_feedback": getattr(intent, "review_feedback", None),
    }


@router.get("/api/repos/{repo:path}/intents")
def get_natural_language_intents(repo: str):
    api = get_hierarchy_api_module()
    try:
        conn = api._get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        payload = api.list_natural_language_intents(conn, repo=repo)
    finally:
        api._close_connection(conn)
    return JSONResponse(payload)


@router.post("/api/repos/{repo:path}/intents")
def submit_natural_language_intent(repo: str, request: IntentSubmitRequest):
    api = get_hierarchy_api_module()
    repository = api._build_intake_repository()
    service = api._create_intake_service(repository)
    try:
        intent = service.submit_intent(repo=repo, prompt=request.prompt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        close_repository_connection(repository)
    return JSONResponse(api._serialize_intent(intent))


@router.post("/api/intents/{intent_id}/answer")
def answer_natural_language_intent(intent_id: str, request: IntentAnswerRequest):
    api = get_hierarchy_api_module()
    repository = api._build_intake_repository()
    service = api._create_intake_service(repository)
    try:
        intent = service.answer_intent(intent_id=intent_id, answer=request.answer)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        close_repository_connection(repository)
    return JSONResponse(api._serialize_intent(intent))


@router.post("/api/intents/{intent_id}/approve")
def approve_natural_language_intent(intent_id: str, request: IntentApproveRequest):
    api = get_hierarchy_api_module()
    repository = api._build_intake_repository()
    service = api._create_intake_service(repository)
    try:
        intent = service.approve_intent(
            intent_id=intent_id,
            approver=request.approver,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        close_repository_connection(repository)
    return JSONResponse(api._serialize_intent(intent))


@router.post("/api/intents/{intent_id}/reject")
def reject_natural_language_intent(intent_id: str, request: IntentRejectRequest):
    api = get_hierarchy_api_module()
    repository = api._build_intake_repository()
    service = api._create_intake_service(repository)
    try:
        intent = service.reject_intent(
            intent_id=intent_id,
            reviewer=request.reviewer,
            reason=request.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        close_repository_connection(repository)
    return JSONResponse(api._serialize_intent(intent))


@router.post("/api/intents/{intent_id}/revise")
def revise_natural_language_intent(intent_id: str, request: IntentReviseRequest):
    api = get_hierarchy_api_module()
    repository = api._build_intake_repository()
    service = api._create_intake_service(repository)
    try:
        intent = service.revise_intent(
            intent_id=intent_id,
            reviewer=request.reviewer,
            feedback=request.feedback,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        close_repository_connection(repository)
    return JSONResponse(api._serialize_intent(intent))
