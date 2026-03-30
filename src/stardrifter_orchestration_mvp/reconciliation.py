from __future__ import annotations

from pathlib import Path
from typing import Callable
from typing import Any

from .workspace import build_workspace_spec
from .models import WorkItem


def build_reconciliation_report(
    *,
    task_rows: list[dict[str, Any]],
    epic_rows: list[dict[str, Any]],
    story_rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    task_drift: list[dict[str, Any]] = []
    for row in task_rows:
        issue_number = int(row["issue_number"])
        db_status = str(row.get("db_status") or "")
        github_state = str(row.get("github_state") or "")
        github_status_label = row.get("status_label")
        pull_url = row.get("pull_url")

        expected_state = "CLOSED" if db_status == "done" else "OPEN"
        expected_label = "status:done" if db_status == "done" else "status:blocked"
        if github_state != expected_state or github_status_label != expected_label:
            task_drift.append(
                {
                    "issue_number": issue_number,
                    "kind": "task_status_mismatch",
                    "db_status": db_status,
                    "github_state": github_state,
                    "github_status_label": github_status_label,
                }
            )
            continue

        if db_status == "done" and not pull_url:
            task_drift.append(
                {
                    "issue_number": issue_number,
                    "kind": "missing_pull_request_link",
                    "db_status": db_status,
                }
            )

    epic_drift: list[dict[str, Any]] = []
    for row in epic_rows:
        issue_number = int(row["issue_number"])
        db_epic_complete = bool(row.get("db_epic_complete") or False)
        github_state = str(row.get("github_state") or "")
        github_status_label = row.get("status_label")
        expected_state = "CLOSED" if db_epic_complete else "OPEN"
        expected_label = "status:done" if db_epic_complete else "status:blocked"
        if github_state != expected_state or github_status_label != expected_label:
            epic_drift.append(
                {
                    "issue_number": issue_number,
                    "kind": "epic_status_mismatch",
                    "db_epic_complete": db_epic_complete,
                    "github_state": github_state,
                    "github_status_label": github_status_label,
                }
            )

    story_drift: list[dict[str, Any]] = []
    for row in story_rows:
        issue_number = int(row["issue_number"])
        db_story_complete = bool(row.get("db_story_complete") or False)
        execution_status = str(row.get("execution_status") or "")
        story_task_count = int(row.get("story_task_count") or 0)
        branch_exists = row.get("canonical_branch_exists")
        worktree_exists = row.get("canonical_worktree_exists")
        github_state = str(row.get("github_state") or "")
        github_status_label = row.get("status_label")
        expected_state = "CLOSED" if db_story_complete else "OPEN"
        expected_label = "status:done" if db_story_complete else "status:blocked"
        if github_state != expected_state or github_status_label != expected_label:
            story_drift.append(
                {
                    "issue_number": issue_number,
                    "kind": "story_status_mismatch",
                    "db_story_complete": db_story_complete,
                    "github_state": github_state,
                    "github_status_label": github_status_label,
                }
            )

        if execution_status == "active" and story_task_count > 0:
            if branch_exists is False:
                story_drift.append(
                    {
                        "issue_number": issue_number,
                        "kind": "missing_story_branch",
                        "execution_status": execution_status,
                        "story_task_count": story_task_count,
                    }
                )
            if worktree_exists is False:
                story_drift.append(
                    {
                        "issue_number": issue_number,
                        "kind": "missing_story_worktree",
                        "execution_status": execution_status,
                        "story_task_count": story_task_count,
                    }
                )

    return {
        "task_drift": task_drift,
        "epic_drift": epic_drift,
        "story_drift": story_drift,
    }


def load_reconciliation_rows(
    *,
    connection: Any,
    repo: str,
    repo_root: Path | None = None,
    worktree_root: Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                wi.source_issue_number AS issue_number,
                wi.status AS db_status,
                wi.decision_required AS db_decision_required,
                gin.github_state,
                gin.status_label,
                pr.pull_url
            FROM work_item wi
            LEFT JOIN github_issue_normalized gin
              ON gin.repo = wi.repo
             AND gin.issue_number = wi.source_issue_number
            LEFT JOIN pull_request_link pr
              ON pr.work_id = wi.id
            WHERE wi.repo = %s
              AND wi.source_issue_number IS NOT NULL
            ORDER BY wi.source_issue_number
            """,
            (repo,),
        )
        task_rows = list(cursor.fetchall())
        cursor.execute(
            """
            SELECT
                e.issue_number,
                (
                    e.execution_status = 'done'
                    OR NOT EXISTS (
                        SELECT 1
                        FROM program_story s
                        WHERE s.repo = e.repo
                          AND s.epic_issue_number = e.issue_number
                          AND s.execution_status <> 'done'
                    )
                ) AS db_epic_complete,
                gin.github_state,
                gin.status_label
            FROM program_epic e
            LEFT JOIN github_issue_normalized gin
              ON gin.repo = e.repo
             AND gin.issue_number = e.issue_number
            WHERE e.repo = %s
            ORDER BY e.issue_number
            """,
            (repo,),
        )
        epic_rows = list(cursor.fetchall())
        cursor.execute(
            """
            SELECT
                s.issue_number,
                s.execution_status,
                (
                    s.execution_status = 'done'
                    OR NOT EXISTS (
                        SELECT 1
                        FROM work_item wi
                        WHERE wi.repo = s.repo
                          AND wi.canonical_story_issue_number = s.issue_number
                          AND wi.status <> 'done'
                    )
                ) AS db_story_complete,
                COALESCE(task_counts.story_task_count, 0) AS story_task_count,
                gin.github_state,
                gin.status_label
            FROM program_story s
            LEFT JOIN (
                SELECT
                    repo,
                    canonical_story_issue_number AS story_issue_number,
                    COUNT(*) AS story_task_count
                FROM work_item
                WHERE canonical_story_issue_number IS NOT NULL
                GROUP BY repo, canonical_story_issue_number
            ) task_counts
              ON task_counts.repo = s.repo
             AND task_counts.story_issue_number = s.issue_number
            LEFT JOIN github_issue_normalized gin
              ON gin.repo = s.repo
             AND gin.issue_number = s.issue_number
            WHERE s.repo = %s
            ORDER BY s.issue_number
            """,
            (repo,),
        )
        story_rows = list(cursor.fetchall())

    if repo_root is not None:
        resolved_repo_root = Path(repo_root).resolve()
        resolved_worktree_root = (
            Path(worktree_root).resolve() if worktree_root is not None else None
        )
        for row in story_rows:
            issue_number = int(row["issue_number"])
            spec = build_workspace_spec(
                work_item=WorkItem(
                    id=f"issue-{issue_number}",
                    title=str(row.get("issue_number") or issue_number),
                    lane="reconciliation",
                    wave="Wave0",
                    status="done",
                    repo=repo,
                    canonical_story_issue_number=issue_number,
                ),
                repo_root=resolved_repo_root,
                worktree_root=resolved_worktree_root,
            )
            row["canonical_branch_exists"] = _git_branch_exists(
                resolved_repo_root, spec.branch_name
            )
            row["canonical_worktree_exists"] = spec.workspace_path.exists()
    return {
        "task_rows": task_rows,
        "epic_rows": epic_rows,
        "story_rows": story_rows,
    }


def _git_branch_exists(repo_root: Path, branch_name: str) -> bool:
    import subprocess

    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "show-ref",
            "--verify",
            f"refs/heads/{branch_name}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def repair_reconciliation_drift(
    *,
    report: dict[str, list[dict[str, Any]]],
    repo: str,
    task_repair: Callable[..., None],
    epic_repair: Callable[..., None],
    story_repair: Callable[..., None],
) -> dict[str, int]:
    task_repaired = 0
    task_skipped = 0
    for drift in report.get("task_drift", []):
        if drift.get("kind") != "task_status_mismatch":
            task_skipped += 1
            continue
        task_repair(
            repo=repo,
            issue_number=int(drift["issue_number"]),
            status=str(drift["db_status"]),
            decision_required=bool(drift.get("db_decision_required") or False),
        )
        task_repaired += 1

    epic_repaired = 0
    epic_skipped = 0
    for drift in report.get("epic_drift", []):
        if drift.get("kind") != "epic_status_mismatch":
            epic_skipped += 1
            continue
        epic_repair(
            repo=repo,
            issue_number=int(drift["issue_number"]),
            status="done"
            if bool(drift.get("db_epic_complete") or False)
            else "blocked",
            decision_required=False,
        )
        epic_repaired += 1

    story_repaired = 0
    story_skipped = 0
    for drift in report.get("story_drift", []):
        if drift.get("kind") != "story_status_mismatch":
            story_skipped += 1
            continue
        story_repair(
            repo=repo,
            issue_number=int(drift["issue_number"]),
            status="done"
            if bool(drift.get("db_story_complete") or False)
            else "blocked",
            decision_required=False,
        )
        story_repaired += 1

    return {
        "task_repaired": task_repaired,
        "epic_repaired": epic_repaired,
        "story_repaired": story_repaired,
        "task_skipped": task_skipped,
        "epic_skipped": epic_skipped,
        "story_skipped": story_skipped,
    }
