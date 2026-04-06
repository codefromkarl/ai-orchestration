from __future__ import annotations

import json

from ..models import OperatorRequest

OPERATOR_REQUEST_SELECT_COLUMNS = """repo,
       epic_issue_number,
       reason_code,
       summary,
       remaining_story_issue_numbers_json,
       blocked_story_issue_numbers_json,
       status,
       opened_at,
       closed_at,
       closed_reason"""

OPERATOR_REQUEST_SELECT_SQL = f"""
SELECT {OPERATOR_REQUEST_SELECT_COLUMNS}
FROM operator_request
"""

RECORD_OPERATOR_REQUEST_SQL = """
INSERT INTO operator_request (
    repo,
    epic_issue_number,
    reason_code,
    summary,
    remaining_story_issue_numbers_json,
    blocked_story_issue_numbers_json,
    status,
    opened_at,
    closed_at,
    closed_reason
)
VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
RETURNING id
"""

CLOSE_OPERATOR_REQUEST_SQL = f"""
WITH closed_request AS (
    UPDATE operator_request
    SET status = 'closed',
        closed_at = NOW(),
        closed_reason = %s
    WHERE repo = %s
      AND epic_issue_number = %s
      AND reason_code = %s
      AND status = 'open'
    RETURNING {OPERATOR_REQUEST_SELECT_COLUMNS}
),
synced_epic_state AS (
    UPDATE epic_execution_state ees
    SET operator_attention_required = EXISTS (
            SELECT 1
            FROM operator_request orq
            JOIN closed_request cr
              ON cr.repo = orq.repo
             AND cr.epic_issue_number = orq.epic_issue_number
            WHERE orq.status = 'open'
        ),
        last_operator_action_at = cr.closed_at,
        last_operator_action_reason = cr.closed_reason,
        updated_at = NOW()
    FROM closed_request cr
    WHERE ees.repo = cr.repo
      AND ees.epic_issue_number = cr.epic_issue_number
)
SELECT {OPERATOR_REQUEST_SELECT_COLUMNS}
FROM closed_request
"""


def build_record_operator_request_params(request: OperatorRequest) -> tuple[object, ...]:
    return (
        request.repo,
        request.epic_issue_number,
        request.reason_code,
        request.summary,
        json.dumps(list(request.remaining_story_issue_numbers)),
        json.dumps(list(request.blocked_story_issue_numbers)),
        request.status,
        request.opened_at,
        request.closed_at,
        request.closed_reason,
    )


def build_list_operator_requests_query(
    *,
    repo: str,
    epic_issue_number: int | None = None,
    include_closed: bool = False,
) -> tuple[str, tuple[object, ...]]:
    where_clauses = ["repo = %s"]
    params: tuple[object, ...] = (repo,)
    if epic_issue_number is not None:
        where_clauses.append("epic_issue_number = %s")
        params = (repo, epic_issue_number)
    if not include_closed:
        where_clauses.append("status = 'open'")
    sql = f"""{OPERATOR_REQUEST_SELECT_SQL}
WHERE {" AND ".join(where_clauses)}
ORDER BY opened_at ASC, id ASC
"""
    return sql, params
