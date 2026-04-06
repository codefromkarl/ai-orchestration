from __future__ import annotations

import json

from ..models import NaturalLanguageIntent

NATURAL_LANGUAGE_INTENT_SELECT_COLUMNS = """id, repo, prompt, status, conversation_json, summary,
       clarification_questions_json, proposal_json, analysis_model,
       promoted_epic_issue_number, created_at, updated_at,
       approved_at, approved_by,
       reviewed_at, reviewed_by, review_action, review_feedback"""

NATURAL_LANGUAGE_INTENT_SELECT_SQL = f"""
SELECT {NATURAL_LANGUAGE_INTENT_SELECT_COLUMNS}
FROM natural_language_intent
"""

RECORD_NATURAL_LANGUAGE_INTENT_SQL = """
INSERT INTO natural_language_intent (
    id,
    repo,
    prompt,
    status,
    conversation_json,
    summary,
    clarification_questions_json,
    proposal_json,
    analysis_model,
    promoted_epic_issue_number,
    approved_at,
    approved_by,
    reviewed_at,
    reviewed_by,
    review_action,
    review_feedback,
    created_at,
    updated_at
)
VALUES (
    %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb,
    %s, %s, %s, %s, %s, %s, %s, %s,
    COALESCE(%s, NOW()), COALESCE(%s, NOW())
)
ON CONFLICT (id) DO UPDATE SET
    repo = EXCLUDED.repo,
    prompt = EXCLUDED.prompt,
    status = EXCLUDED.status,
    conversation_json = EXCLUDED.conversation_json,
    summary = EXCLUDED.summary,
    clarification_questions_json = EXCLUDED.clarification_questions_json,
    proposal_json = EXCLUDED.proposal_json,
    analysis_model = EXCLUDED.analysis_model,
    promoted_epic_issue_number = EXCLUDED.promoted_epic_issue_number,
    approved_at = EXCLUDED.approved_at,
    approved_by = EXCLUDED.approved_by,
    reviewed_at = EXCLUDED.reviewed_at,
    reviewed_by = EXCLUDED.reviewed_by,
    review_action = EXCLUDED.review_action,
    review_feedback = EXCLUDED.review_feedback,
    updated_at = COALESCE(EXCLUDED.updated_at, NOW())
RETURNING id
"""


def build_record_natural_language_intent_params(
    intent: NaturalLanguageIntent,
) -> tuple[object, ...]:
    return (
        intent.id,
        intent.repo,
        intent.prompt,
        intent.status,
        json.dumps(list(intent.conversation), ensure_ascii=False),
        intent.summary,
        json.dumps(list(intent.clarification_questions), ensure_ascii=False),
        json.dumps(intent.proposal_json, ensure_ascii=False),
        intent.analysis_model,
        intent.promoted_epic_issue_number,
        intent.approved_at,
        intent.approved_by,
        intent.reviewed_at,
        intent.reviewed_by,
        intent.review_action,
        intent.review_feedback,
        intent.created_at,
        intent.updated_at,
    )


def build_get_natural_language_intent_query() -> str:
    return f"""{NATURAL_LANGUAGE_INTENT_SELECT_SQL}
WHERE id = %s
"""


def build_list_natural_language_intents_query() -> str:
    return f"""{NATURAL_LANGUAGE_INTENT_SELECT_SQL}
WHERE repo = %s
ORDER BY created_at DESC, id DESC
"""
