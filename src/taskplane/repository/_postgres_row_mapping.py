from __future__ import annotations

from typing import Any

from ..models import NaturalLanguageIntent, OperatorRequest, ProgramStory, WorkClaim, WorkItem


def value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row[key]
    if hasattr(row, key):
        return getattr(row, key)
    return row[key]


def value_optional(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    if hasattr(row, key):
        return getattr(row, key)
    try:
        return row[key]
    except Exception:
        return None


def _json_list(row: Any, key: str) -> list[Any]:
    raw_value = value_optional(row, key)
    return raw_value if isinstance(raw_value, list) else []


def _dod_dict(row: Any) -> dict[str, Any]:
    raw_value = value_optional(row, "dod_json")
    return raw_value if isinstance(raw_value, dict) else {}


def row_to_work_item(row: Any) -> WorkItem:
    dod = _dod_dict(row)
    next_eligible_at = value_optional(row, "next_eligible_at")
    return WorkItem(
        id=value(row, "id"),
        repo=value_optional(row, "repo"),
        title=value(row, "title"),
        lane=value(row, "lane"),
        wave=value(row, "wave"),
        status=value(row, "status"),
        complexity=value(row, "complexity"),
        attempt_count=int(value_optional(row, "attempt_count") or 0),
        last_failure_reason=value_optional(row, "last_failure_reason"),
        next_eligible_at=str(next_eligible_at)
        if next_eligible_at is not None
        else None,
        source_issue_number=value_optional(row, "source_issue_number"),
        story_issue_numbers=tuple(dod.get("story_issue_numbers", [])),
        canonical_story_issue_number=value_optional(
            row, "canonical_story_issue_number"
        ),
        related_story_issue_numbers=tuple(dod.get("related_story_issue_numbers", [])),
        task_type=value_optional(row, "task_type") or "core_path",
        blocking_mode=value_optional(row, "blocking_mode") or "hard",
        planned_paths=tuple(dod.get("planned_paths", [])),
        blocked_reason=value_optional(row, "blocked_reason"),
        decision_required=bool(value_optional(row, "decision_required") or False),
    )


def row_to_program_story(row: Any) -> ProgramStory:
    return ProgramStory(
        issue_number=int(value(row, "issue_number")),
        repo=value(row, "repo"),
        epic_issue_number=value_optional(row, "epic_issue_number"),
        title=value(row, "title"),
        lane=value_optional(row, "lane"),
        complexity=value_optional(row, "complexity"),
        program_status=value(row, "program_status"),
        execution_status=value(row, "execution_status"),
        active_wave=value_optional(row, "active_wave"),
        notes=value_optional(row, "notes"),
    )


def row_to_work_claim(row: Any) -> WorkClaim:
    lease_expires_at = value_optional(row, "lease_expires_at")
    return WorkClaim(
        work_id=value(row, "work_id"),
        worker_name=value(row, "worker_name"),
        workspace_path=value(row, "workspace_path"),
        branch_name=value(row, "branch_name"),
        lease_token=value_optional(row, "lease_token"),
        lease_expires_at=str(lease_expires_at)
        if lease_expires_at is not None
        else None,
        claimed_paths=tuple(value_optional(row, "claimed_paths") or ()),
    )


def row_to_operator_request(row: Any) -> OperatorRequest:
    return OperatorRequest(
        repo=value(row, "repo"),
        epic_issue_number=int(value(row, "epic_issue_number")),
        reason_code=value(row, "reason_code"),
        summary=value(row, "summary"),
        remaining_story_issue_numbers=tuple(
            int(raw_value)
            for raw_value in _json_list(row, "remaining_story_issue_numbers_json")
        ),
        blocked_story_issue_numbers=tuple(
            int(raw_value)
            for raw_value in _json_list(row, "blocked_story_issue_numbers_json")
        ),
        status=value(row, "status"),
        opened_at=value_optional(row, "opened_at"),
        closed_at=value_optional(row, "closed_at"),
        closed_reason=value_optional(row, "closed_reason"),
    )



def row_to_natural_language_intent(row: Any) -> NaturalLanguageIntent:
    return NaturalLanguageIntent(
        id=str(value(row, "id")),
        repo=value(row, "repo"),
        prompt=value(row, "prompt"),
        status=value(row, "status"),
        conversation=tuple(
            item for item in _json_list(row, "conversation_json") if isinstance(item, dict)
        ),
        summary=str(value_optional(row, "summary") or ""),
        clarification_questions=tuple(
            str(item) for item in _json_list(row, "clarification_questions_json")
        ),
        proposal_json=value_optional(row, "proposal_json") or {},
        analysis_model=value_optional(row, "analysis_model"),
        promoted_epic_issue_number=value_optional(row, "promoted_epic_issue_number"),
        created_at=value_optional(row, "created_at"),
        updated_at=value_optional(row, "updated_at"),
        approved_at=value_optional(row, "approved_at"),
        approved_by=value_optional(row, "approved_by"),
        reviewed_at=value_optional(row, "reviewed_at"),
        reviewed_by=value_optional(row, "reviewed_by"),
        review_action=value_optional(row, "review_action"),
        review_feedback=value_optional(row, "review_feedback"),
    )
