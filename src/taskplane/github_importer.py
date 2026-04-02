from __future__ import annotations

import re

from .models import (
    CompletionAudit,
    GitHubNormalizedIssue,
    GitHubRelationCandidate,
)


ISSUE_REF_RE = re.compile(r"(?<![A-Za-z])#(\d+)")
SECTION_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def normalize_github_issue(repo: str, raw_issue: dict) -> GitHubNormalizedIssue:
    labels = [label["name"] if isinstance(label, dict) else str(label) for label in raw_issue.get("labels", [])]
    body = raw_issue.get("body") or ""
    title = str(raw_issue.get("title") or "")
    issue_kind = next((name for name in labels if name in {"epic", "story", "task"}), None)
    lane = next((name for name in labels if name.startswith("lane:")), None)
    if lane is None:
        lane = _infer_lane_from_title(title)
    complexity = next((name for name in labels if name.startswith("complexity:")), None)
    github_state = str(raw_issue.get("state") or "")
    status_label = _select_status_label(labels, github_state=github_state)
    parent_numbers = _extract_parent_issue_numbers(body)
    story_dependency_numbers = _extract_dependency_issue_numbers(
        body,
        headings={"依赖 story", "depends on story"},
    )
    task_dependency_numbers = _extract_dependency_issue_numbers(
        body,
        headings={"依赖 task", "depends on task"},
    )

    anomaly_codes: list[str] = []
    if issue_kind is None:
        anomaly_codes.append("missing-kind")
    if lane is None:
        anomaly_codes.append("missing-lane")
    if issue_kind in {"task", "story"} and not parent_numbers and not _allows_parentless_issue(title, issue_kind):
        anomaly_codes.append("missing-parent-reference")

    return GitHubNormalizedIssue(
        repo=repo,
        issue_number=int(raw_issue["number"]),
        title=title,
        body=body,
        url=str(raw_issue.get("url") or ""),
        github_state=github_state,
        import_state="active",
        issue_kind=issue_kind,
        lane=lane,
        complexity=complexity,
        status_label=status_label,
        explicit_parent_issue_numbers=parent_numbers,
        explicit_story_dependency_issue_numbers=story_dependency_numbers,
        explicit_task_dependency_issue_numbers=task_dependency_numbers,
        anomaly_codes=anomaly_codes,
    )


def _infer_lane_from_title(title: str) -> str | None:
    normalized = title.upper()
    if normalized.startswith("[WAVE") or "[WAVE" in normalized:
        return "lane:INT"
    return None


def _select_status_label(labels: list[str], *, github_state: str) -> str | None:
    status_labels = [label for label in labels if label.startswith("status:")]
    if not status_labels:
        return None

    unique_labels = set(status_labels)
    if github_state.upper() == "CLOSED" and "status:done" in unique_labels:
        return "status:done"

    priority = [
        "status:blocked",
        "status:in-progress",
        "status:done",
        "status:pending",
    ]
    for candidate in priority:
        if candidate in unique_labels:
            return candidate
    return status_labels[0]


def _allows_parentless_issue(title: str, issue_kind: str | None) -> bool:
    if issue_kind != "task":
        return False
    normalized = title.upper()
    return normalized.startswith("[WAVE") or "[PROCESS]" in normalized


def _extract_parent_issue_numbers(body: str) -> list[int]:
    parent_numbers: list[int] = []
    parent_numbers.extend(_extract_part_of_issue_numbers(body))

    sections = _split_markdown_sections(body)
    for heading, content in sections:
        normalized_heading = heading.strip().lower()
        if normalized_heading in {
            "上级 story",
            "上级 epic",
            "parent story",
            "parent epic",
        }:
            parent_numbers.extend(int(match) for match in ISSUE_REF_RE.findall(content))

    return _deduplicate_preserve_order(parent_numbers)


def _extract_part_of_issue_numbers(body: str) -> list[int]:
    return [
        int(match)
        for match in re.findall(r"Part of\s+#(\d+)", body, flags=re.IGNORECASE)
    ]


def _extract_dependency_issue_numbers(body: str, *, headings: set[str]) -> list[int]:
    dependency_numbers: list[int] = []
    sections = _split_markdown_sections(body)
    for heading, content in sections:
        normalized_heading = heading.strip().lower()
        if normalized_heading in headings:
            dependency_numbers.extend(int(match) for match in ISSUE_REF_RE.findall(content))
    return _deduplicate_preserve_order(dependency_numbers)


def _split_markdown_sections(body: str) -> list[tuple[str, str]]:
    matches = list(SECTION_HEADING_RE.finditer(body))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.append((match.group(1), body[start:end]))
    return sections


def _deduplicate_preserve_order(values: list[int]) -> list[int]:
    ordered: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def extract_relation_candidates(
    issue: GitHubNormalizedIssue,
) -> list[GitHubRelationCandidate]:
    relations: list[GitHubRelationCandidate] = []
    evidence_text = issue.body
    for target_issue_number in issue.explicit_parent_issue_numbers:
        relations.append(
            GitHubRelationCandidate(
                source_issue_number=issue.issue_number,
                target_issue_number=target_issue_number,
                relation_type="parent_candidate",
                confidence=1.0,
                evidence_text=evidence_text,
            )
        )
    for target_issue_number in issue.explicit_story_dependency_issue_numbers:
        relations.append(
            GitHubRelationCandidate(
                source_issue_number=issue.issue_number,
                target_issue_number=target_issue_number,
                relation_type="story_dependency_candidate",
                confidence=1.0,
                evidence_text=evidence_text,
            )
        )
    for target_issue_number in issue.explicit_task_dependency_issue_numbers:
        relations.append(
            GitHubRelationCandidate(
                source_issue_number=issue.issue_number,
                target_issue_number=target_issue_number,
                relation_type="task_dependency_candidate",
                confidence=1.0,
                evidence_text=evidence_text,
            )
        )
    return relations


def build_completion_audit(
    issues: list[GitHubNormalizedIssue],
    relations: list[GitHubRelationCandidate],
) -> dict[int, CompletionAudit]:
    issue_by_number = {issue.issue_number: issue for issue in issues}
    child_numbers_by_parent: dict[int, list[int]] = {}
    for relation in relations:
        if relation.relation_type != "parent_candidate":
            continue
        child_numbers_by_parent.setdefault(relation.target_issue_number, []).append(
            relation.source_issue_number
        )

    audit_cache: dict[int, CompletionAudit] = {}

    def _audit(issue_number: int) -> CompletionAudit:
        if issue_number in audit_cache:
            return audit_cache[issue_number]

        issue = issue_by_number[issue_number]
        reasons: list[str] = []
        derived_complete = False

        if issue.issue_kind == "task":
            derived_complete = issue.status_label == "status:done"
            if not derived_complete:
                reasons.append("status-label-not-done")
        elif issue.issue_kind in {"story", "epic"}:
            children = child_numbers_by_parent.get(issue_number, [])
            if not children:
                reasons.append("no-child-issues")
                derived_complete = False
            else:
                child_audits = [_audit(child_issue_number) for child_issue_number in children if child_issue_number in issue_by_number]
                if child_audits and all(child_audit.derived_complete for child_audit in child_audits):
                    derived_complete = True
                else:
                    reasons.append("child-issues-incomplete")
                    derived_complete = False
        else:
            reasons.append("unknown-issue-kind")
            derived_complete = False

        audit = CompletionAudit(
            issue_number=issue_number,
            derived_complete=derived_complete,
            reasons=reasons,
        )
        audit_cache[issue_number] = audit
        return audit

    return {issue.issue_number: _audit(issue.issue_number) for issue in issues}
