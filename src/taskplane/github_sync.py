from __future__ import annotations

import json
import subprocess
import time
from typing import Any, Callable

from .github_importer import (
    build_completion_audit,
    extract_relation_candidates,
    normalize_github_issue,
)


GH_JSON_FIELDS = "number,title,body,state,url,labels,createdAt,updatedAt,closedAt"


def fetch_issues_via_gh(
    *,
    repo: str,
    limit: int = 200,
    runner: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    command = (
        "unset GITHUB_TOKEN; "
        f"gh issue list --repo {repo} --limit {limit} --state all "
        f"--json {GH_JSON_FIELDS}"
    )
    if runner is None:
        runner = _default_shell_runner
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            payload = runner(command)
            return json.loads(payload)
        except RuntimeError as exc:
            if not _is_retryable_fetch_error(exc) or attempt == 2:
                last_error = exc
                break
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
    try:
        return _fetch_issues_via_rest(repo=repo, limit=limit, runner=runner)
    except RuntimeError:
        if last_error is not None:
            raise last_error
        raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("unreachable fetch_issues_via_gh state")


def persist_issue_import_batch(
    *,
    connection: Any,
    repo: str,
    raw_issues: list[dict[str, Any]],
) -> None:
    normalized_issues = [
        normalize_github_issue(repo, raw_issue) for raw_issue in raw_issues
    ]
    relations = []
    for normalized_issue in normalized_issues:
        relations.extend(extract_relation_candidates(normalized_issue))
    completion_audit = build_completion_audit(normalized_issues, relations)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO github_issue_import_batch (repo)
            VALUES (%s)
            RETURNING id
            """,
            (repo,),
        )
        batch_row = cursor.fetchone()
        batch_id = _value(batch_row, "id")

        cursor.execute(
            "DELETE FROM github_issue_relation WHERE repo = %s",
            (repo,),
        )
        cursor.execute(
            "DELETE FROM github_issue_completion_audit WHERE repo = %s",
            (repo,),
        )
        cursor.execute(
            "DELETE FROM github_issue_normalized WHERE repo = %s",
            (repo,),
        )

        snapshot_ids_by_issue_number: dict[int, int] = {}
        for raw_issue in raw_issues:
            cursor.execute(
                """
                INSERT INTO github_issue_snapshot (batch_id, repo, issue_number, raw_json)
                VALUES (%s, %s, %s, %s::jsonb)
                RETURNING id
                """,
                (
                    batch_id,
                    repo,
                    int(raw_issue["number"]),
                    json.dumps(raw_issue, ensure_ascii=False),
                ),
            )
            snapshot_row = cursor.fetchone()
            snapshot_ids_by_issue_number[int(raw_issue["number"])] = _value(
                snapshot_row, "id"
            )

        for normalized_issue in normalized_issues:
            cursor.execute(
                """
                INSERT INTO github_issue_normalized (
                    repo,
                    issue_number,
                    title,
                    body,
                    url,
                    github_state,
                    import_state,
                    issue_kind,
                    lane,
                    complexity,
                    status_label,
                    explicit_parent_issue_numbers,
                    explicit_story_dependency_issue_numbers,
                    explicit_task_dependency_issue_numbers,
                    anomaly_codes,
                    source_snapshot_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s)
                ON CONFLICT (repo, issue_number) DO UPDATE SET
                    title = EXCLUDED.title,
                    body = EXCLUDED.body,
                    url = EXCLUDED.url,
                    github_state = EXCLUDED.github_state,
                    import_state = EXCLUDED.import_state,
                    issue_kind = EXCLUDED.issue_kind,
                    lane = EXCLUDED.lane,
                    complexity = EXCLUDED.complexity,
                    status_label = EXCLUDED.status_label,
                    explicit_parent_issue_numbers = EXCLUDED.explicit_parent_issue_numbers,
                    explicit_story_dependency_issue_numbers = EXCLUDED.explicit_story_dependency_issue_numbers,
                    explicit_task_dependency_issue_numbers = EXCLUDED.explicit_task_dependency_issue_numbers,
                    anomaly_codes = EXCLUDED.anomaly_codes,
                    source_snapshot_id = EXCLUDED.source_snapshot_id,
                    updated_at = NOW()
                """,
                (
                    normalized_issue.repo,
                    normalized_issue.issue_number,
                    normalized_issue.title,
                    normalized_issue.body,
                    normalized_issue.url,
                    normalized_issue.github_state,
                    normalized_issue.import_state,
                    normalized_issue.issue_kind,
                    normalized_issue.lane,
                    normalized_issue.complexity,
                    normalized_issue.status_label,
                    json.dumps(normalized_issue.explicit_parent_issue_numbers),
                    json.dumps(
                        normalized_issue.explicit_story_dependency_issue_numbers
                    ),
                    json.dumps(normalized_issue.explicit_task_dependency_issue_numbers),
                    json.dumps(normalized_issue.anomaly_codes),
                    snapshot_ids_by_issue_number[normalized_issue.issue_number],
                ),
            )

        for relation in relations:
            cursor.execute(
                """
                INSERT INTO github_issue_relation (
                    repo,
                    source_issue_number,
                    target_issue_number,
                    relation_type,
                    confidence,
                    evidence_text
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    relation.source_issue_number,
                    relation.target_issue_number,
                    relation.relation_type,
                    relation.confidence,
                    relation.evidence_text,
                ),
            )

        for issue_number, audit in completion_audit.items():
            cursor.execute(
                """
                INSERT INTO github_issue_completion_audit (
                    repo,
                    issue_number,
                    derived_complete,
                    reasons
                )
                VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT (repo, issue_number) DO UPDATE SET
                    derived_complete = EXCLUDED.derived_complete,
                    reasons = EXCLUDED.reasons,
                    updated_at = NOW()
                """,
                (
                    repo,
                    issue_number,
                    audit.derived_complete,
                    json.dumps(audit.reasons, ensure_ascii=False),
                ),
            )

    connection.commit()


def _default_shell_runner(command: str) -> str:
    completed = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout


def _fetch_issues_via_rest(
    *, repo: str, limit: int, runner: Callable[[str], str]
) -> list[dict[str, Any]]:
    command = (
        f"unset GITHUB_TOKEN; gh api repos/{repo}/issues?state=all&per_page={limit}"
    )
    payload = runner(command)
    raw_issues = json.loads(payload)
    return [_normalize_rest_issue(raw_issue) for raw_issue in raw_issues]


def _normalize_rest_issue(raw_issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": raw_issue["number"],
        "title": raw_issue.get("title", ""),
        "body": raw_issue.get("body", ""),
        "state": str(raw_issue.get("state", "")).upper(),
        "url": raw_issue.get("html_url") or raw_issue.get("url", ""),
        "labels": raw_issue.get("labels", []),
        "createdAt": raw_issue.get("created_at"),
        "updatedAt": raw_issue.get("updated_at"),
        "closedAt": raw_issue.get("closed_at"),
    }


def _is_retryable_fetch_error(error: RuntimeError) -> bool:
    message = str(error)
    retry_markers = (
        "GraphQL",
        "EOF",
        "tls",
        "TLS",
        "connection reset",
        "timeout",
        "temporarily unavailable",
    )
    return any(marker in message for marker in retry_markers)


def _value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row[key]
    return getattr(row, key, row[key])
