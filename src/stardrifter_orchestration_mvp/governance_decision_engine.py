from __future__ import annotations

from typing import Any

TRANSIENT_FAILURE_REASONS = {
    "timeout",
    "transient_error",
    "rate_limit",
    "network_error",
    "temporary_failure",
}

MAX_AUTO_RETRY_ATTEMPTS = 3
HIGH_CONFIDENCE_THRESHOLD = 0.85


def load_decidable_tasks(
    *,
    connection: Any,
    repo: str,
) -> dict[str, list[dict[str, Any]]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                wi.id,
                wi.source_issue_number,
                wi.title,
                wi.status,
                wi.blocked_reason,
                wi.decision_required,
                wi.attempt_count,
                wi.last_failure_reason,
                wi.next_eligible_at,
                wi.task_type,
                wi.blocking_mode,
                wi.canonical_story_issue_number
            FROM work_item wi
            WHERE wi.repo = %s
              AND wi.status IN ('blocked', 'pending')
              AND (
                wi.last_failure_reason IS NOT NULL
                OR wi.blocked_reason IS NOT NULL
                OR wi.decision_required = true
              )
            ORDER BY
                CASE wi.task_type
                    WHEN 'governance' THEN 0
                    WHEN 'core_path' THEN 1
                    ELSE 2
                END,
                wi.source_issue_number
            """,
            (repo,),
        )
        blocked_tasks = [dict(r) for r in cursor.fetchall()]

        cursor.execute(
            """
            SELECT
                wi.id AS blocked_task_id,
                wi.source_issue_number AS blocked_issue,
                dep_wi.source_issue_number AS dependency_issue,
                dep_wi.status AS dependency_status
            FROM work_item wi
            JOIN work_dependency wd
              ON wd.work_id = wi.id
            JOIN work_item dep_wi
              ON dep_wi.id = wd.depends_on_work_id
            WHERE wi.repo = %s
              AND wi.status = 'blocked'
            ORDER BY wi.source_issue_number
            """,
            (repo,),
        )
        dependency_chains = [dict(r) for r in cursor.fetchall()]

    return {
        "blocked_tasks": blocked_tasks,
        "dependency_chains": dependency_chains,
    }


def evaluate_retry_eligibility(
    *,
    task: dict[str, Any],
    max_attempts: int = MAX_AUTO_RETRY_ATTEMPTS,
) -> dict[str, Any] | None:
    if task.get("status") != "blocked":
        return None

    failure_reason = str(task.get("last_failure_reason") or "").lower()
    if failure_reason not in TRANSIENT_FAILURE_REASONS:
        return None

    attempt_count = int(task.get("attempt_count") or 0)
    if attempt_count >= max_attempts:
        return None

    return {
        "task_id": task["id"],
        "source_issue_number": task["source_issue_number"],
        "title": task["title"],
        "action": "retry",
        "reason": f"transient_{failure_reason}",
        "attempt_count": attempt_count,
        "max_attempts": max_attempts,
        "confidence": round(0.9 - (attempt_count * 0.1), 2),
    }


def evaluate_unblock_eligibility(
    *,
    task: dict[str, Any],
    dependency_chains: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if task.get("status") != "blocked":
        return None

    task_deps = [dc for dc in dependency_chains if dc["blocked_task_id"] == task["id"]]
    if not task_deps:
        return None

    all_deps_done = all(dc["dependency_status"] == "done" for dc in task_deps)
    if not all_deps_done:
        return None

    return {
        "task_id": task["id"],
        "source_issue_number": task["source_issue_number"],
        "title": task["title"],
        "action": "unblock",
        "reason": "all_dependencies_resolved",
        "resolved_dependencies": [dc["dependency_issue"] for dc in task_deps],
        "confidence": 0.95,
    }


def evaluate_flag_eligibility(
    *,
    task: dict[str, Any],
) -> dict[str, Any] | None:
    if not task.get("decision_required"):
        return None

    return {
        "task_id": task["id"],
        "source_issue_number": task["source_issue_number"],
        "title": task["title"],
        "action": "flag",
        "reason": "decision_required_by_operator",
        "blocked_reason": task.get("blocked_reason"),
        "confidence": 1.0,
    }


def evaluate_decisions(
    *,
    connection: Any,
    repo: str,
    max_attempts: int = MAX_AUTO_RETRY_ATTEMPTS,
    dry_run: bool = False,
) -> dict[str, Any]:
    data = load_decidable_tasks(connection=connection, repo=repo)
    tasks = data["blocked_tasks"]
    deps = data["dependency_chains"]

    decisions: list[dict[str, Any]] = []
    auto_retry = 0
    auto_unblock = 0
    flagged = 0

    for task in tasks:
        retry = evaluate_retry_eligibility(task=task, max_attempts=max_attempts)
        if retry:
            if not dry_run:
                _execute_retry(connection=connection, task_id=task["id"])
                _log_decision(
                    connection=connection,
                    task_id=task["id"],
                    decision_type="auto_retry",
                    reasoning=retry["reason"],
                    context=f"attempt={retry['attempt_count']}/{retry['max_attempts']}",
                )
            auto_retry += 1
            decisions.append(retry)
            continue

        unblock = evaluate_unblock_eligibility(task=task, dependency_chains=deps)
        if unblock:
            if not dry_run:
                _execute_unblock(connection=connection, task_id=task["id"])
                _log_decision(
                    connection=connection,
                    task_id=task["id"],
                    decision_type="auto_unblock",
                    reasoning=unblock["reason"],
                    context=f"deps={unblock['resolved_dependencies']}",
                )
            auto_unblock += 1
            decisions.append(unblock)
            continue

        flag = evaluate_flag_eligibility(task=task)
        if flag:
            flagged += 1
            decisions.append(flag)

    if not dry_run:
        connection.commit()

    return {
        "repo": repo,
        "decisions_made": len(decisions),
        "auto_retry": auto_retry,
        "auto_unblock": auto_unblock,
        "flagged_for_review": flagged,
        "decisions": decisions,
    }


def _execute_retry(*, connection: Any, task_id: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE work_item
            SET status = 'ready',
                blocked_reason = NULL,
                next_eligible_at = NOW()
            WHERE id = %s
              AND status = 'blocked'
            """,
            (task_id,),
        )


def _execute_unblock(*, connection: Any, task_id: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE work_item
            SET status = 'ready',
                blocked_reason = NULL
            WHERE id = %s
              AND status = 'blocked'
            """,
            (task_id,),
        )


def _log_decision(
    *,
    connection: Any,
    task_id: str,
    decision_type: str,
    reasoning: str,
    context: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO ai_decision_log (work_id, decision_type, ai_reasoning, context_summary, outcome)
            VALUES (%s, %s, %s, %s, 'auto_applied')
            """,
            (task_id, decision_type, reasoning, context),
        )
