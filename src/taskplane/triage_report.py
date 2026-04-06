from __future__ import annotations

from .models import CompletionAudit, GitHubNormalizedIssue, GitHubRelationCandidate, GitHubTaskProjection, TriageReport


def build_triage_report(
    *,
    issues: list[GitHubNormalizedIssue],
    relations: list[GitHubRelationCandidate],
    completion_audit: dict[int, CompletionAudit],
    projection: GitHubTaskProjection,
) -> TriageReport:
    issue_by_number = {issue.issue_number: issue for issue in issues}

    story_numbers = [
        issue.issue_number
        for issue in issues
        if issue.issue_kind == "story" and issue.github_state == "OPEN"
    ]
    projected_story_numbers = set(projection.story_task_ids)
    storys_without_projected_tasks = sorted(
        story_issue_number
        for story_issue_number in story_numbers
        if story_issue_number not in projected_story_numbers
    )

    anomalies_by_issue = {
        issue.issue_number: list(issue.anomaly_codes)
        for issue in issues
        if issue.anomaly_codes
    }

    return TriageReport(
        unprojected_task_issue_numbers=sorted(
            projection.needs_triage_issue_numbers
        ),
        storys_without_projected_tasks=storys_without_projected_tasks,
        anomalies_by_issue=anomalies_by_issue,
    )
