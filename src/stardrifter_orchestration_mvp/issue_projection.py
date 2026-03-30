from __future__ import annotations

import re

from .models import (
    CompletionAudit,
    GitHubNormalizedIssue,
    GitHubRelationCandidate,
    GitHubTaskProjection,
    WorkDependency,
    WorkItem,
)


CODE_PATH_RE = re.compile(r"`([^`]+)`")
KNOWN_BASENAME_PATHS = {
    "starsector-combat-mainline-migration-plan.md": "docs/project/implementation/baselines/starsector-combat-mainline-migration-plan.md",
}
LANE_DOC_ROOTS = {
    "lane:04": "docs/domains/04-encounter-mediation/",
    "lane:05": "docs/domains/05-combat-handoff/",
    "lane:06": "docs/domains/06-projection-save-replay/",
}
INTERNAL_GOVERNANCE_STORY_BY_TASK: dict[int, int] = {
    69: -1901,
}


def project_github_tasks_to_work_items(
    *,
    issues: list[GitHubNormalizedIssue],
    relations: list[GitHubRelationCandidate],
    completion_audit: dict[int, CompletionAudit],
) -> GitHubTaskProjection:
    issue_by_number = {issue.issue_number: issue for issue in issues}
    story_numbers_by_task: dict[int, list[int]] = {}
    for relation in relations:
        if relation.relation_type != "parent_candidate":
            continue
        target_issue = issue_by_number.get(relation.target_issue_number)
        if target_issue is None or target_issue.issue_kind != "story":
            continue
        story_numbers_by_task.setdefault(relation.source_issue_number, []).append(
            relation.target_issue_number
        )

    # Pre-build story repo and wave mapping for inheritance
    story_repo_map: dict[int, str | None] = {}
    story_wave_map: dict[int, str | None] = {}
    for issue in issues:
        if issue.issue_kind == "story":
            story_repo_map[issue.issue_number] = issue.repo
            # Wave is not available in GitHubNormalizedIssue, will be inherited at DB level
            story_wave_map[issue.issue_number] = None

    work_items: list[WorkItem] = []
    story_task_ids: dict[int, list[str]] = {}
    needs_triage_issue_numbers: list[int] = []

    for issue in issues:
        if issue.issue_kind != "task":
            continue
        story_issue_numbers = _deduplicate_preserve_order(
            story_numbers_by_task.get(issue.issue_number, [])
        )
        task_type = _infer_task_type(issue=issue, story_issue_numbers=story_issue_numbers)
        is_governance = task_type == "governance"
        if issue.lane is None or (not story_issue_numbers and not is_governance):
            needs_triage_issue_numbers.append(issue.issue_number)
            continue
        canonical_story_issue_number = story_issue_numbers[0] if story_issue_numbers else None
        related_story_issue_numbers = tuple(story_issue_numbers[1:]) if story_issue_numbers else ()
        if is_governance:
            if canonical_story_issue_number is None:
                canonical_story_issue_number = INTERNAL_GOVERNANCE_STORY_BY_TASK.get(issue.issue_number)
                related_story_issue_numbers = ()
        blocking_mode = "soft" if task_type in {"documentation", "cross_cutting"} else "hard"

        # Inherit repo from canonical story (data integrity at source)
        repo = story_repo_map.get(canonical_story_issue_number) if canonical_story_issue_number else None

        work_item_id = f"issue-{issue.issue_number}"
        work_item = WorkItem(
            id=work_item_id,
            title=issue.title,
            lane=_normalize_lane(issue.lane),
            wave="unassigned",  # Will be inherited by DB trigger from Epic/Story
            status=_map_status_label_to_work_status(issue.status_label),
            repo=repo,  # Force set repo from story inheritance
            complexity=_map_complexity(issue.complexity),
            source_issue_number=issue.issue_number,
            story_issue_numbers=(canonical_story_issue_number,) if canonical_story_issue_number is not None else (),
            canonical_story_issue_number=canonical_story_issue_number,
            related_story_issue_numbers=related_story_issue_numbers,
            task_type=task_type,
            blocking_mode=blocking_mode,
            planned_paths=_infer_planned_paths(issue=issue),
        )
        work_items.append(work_item)
        if canonical_story_issue_number is not None:
            story_task_ids.setdefault(canonical_story_issue_number, []).append(work_item_id)

    work_id_by_issue_number = {
        work_item.source_issue_number: work_item.id
        for work_item in work_items
        if work_item.source_issue_number is not None
    }
    task_issue_numbers_with_explicit_dependencies = {
        issue.issue_number
        for issue in issues
        if issue.issue_kind == "task"
        and (
            issue.explicit_story_dependency_issue_numbers
            or issue.explicit_task_dependency_issue_numbers
        )
    }
    work_dependencies: list[WorkDependency] = []
    seen_dependencies: set[tuple[str, str]] = set()

    for issue in issues:
        if issue.issue_kind != "task" or issue.issue_number not in work_id_by_issue_number:
            continue
        current_work_id = work_id_by_issue_number[issue.issue_number]

        direct_task_targets = [
            relation.target_issue_number
            for relation in relations
            if relation.source_issue_number == issue.issue_number
            and relation.relation_type == "task_dependency_candidate"
        ]
        for target_issue_number in direct_task_targets:
            target_work_id = work_id_by_issue_number.get(target_issue_number)
            if target_work_id is None:
                needs_triage_issue_numbers.append(issue.issue_number)
                continue
            dependency_key = (current_work_id, target_work_id)
            if dependency_key in seen_dependencies:
                continue
            seen_dependencies.add(dependency_key)
            work_dependencies.append(
                WorkDependency(
                    work_id=current_work_id,
                    depends_on_work_id=target_work_id,
                )
            )

        story_targets = [
            relation.target_issue_number
            for relation in relations
            if relation.source_issue_number == issue.issue_number
            and relation.relation_type == "story_dependency_candidate"
        ]
        for target_story_issue_number in story_targets:
            target_story_work_ids = story_task_ids.get(target_story_issue_number, [])
            if not target_story_work_ids:
                needs_triage_issue_numbers.append(issue.issue_number)
                continue
            for target_work_id in target_story_work_ids:
                dependency_key = (current_work_id, target_work_id)
                if dependency_key in seen_dependencies:
                    continue
                seen_dependencies.add(dependency_key)
                work_dependencies.append(
                    WorkDependency(
                        work_id=current_work_id,
                        depends_on_work_id=target_work_id,
                    )
                )

    for _, work_item_ids in sorted(story_task_ids.items()):
        for previous_id, current_id in zip(work_item_ids, work_item_ids[1:], strict=False):
            current_issue_number = int(current_id.split("-", 1)[1])
            if current_issue_number in task_issue_numbers_with_explicit_dependencies:
                continue
            dependency_key = (current_id, previous_id)
            if dependency_key in seen_dependencies:
                continue
            seen_dependencies.add(dependency_key)
            work_dependencies.append(
                WorkDependency(
                    work_id=current_id,
                    depends_on_work_id=previous_id,
                )
            )

    story_dependencies = sorted(
        {
            (relation.source_issue_number, relation.target_issue_number)
            for relation in relations
            if relation.relation_type == "story_dependency_candidate"
            and issue_by_number.get(relation.source_issue_number) is not None
            and issue_by_number[relation.source_issue_number].issue_kind == "story"
            and issue_by_number.get(relation.target_issue_number) is not None
            and issue_by_number[relation.target_issue_number].issue_kind == "story"
        }
    )

    return GitHubTaskProjection(
        work_items=work_items,
        story_task_ids=story_task_ids,
        work_dependencies=sorted(
            work_dependencies,
            key=lambda dependency: (dependency.work_id, dependency.depends_on_work_id),
        ),
        story_dependencies=story_dependencies,
        needs_triage_issue_numbers=sorted(set(needs_triage_issue_numbers)),
    )


def build_projectable_story_task_counts(
    *,
    issues: list[GitHubNormalizedIssue],
) -> dict[int, int]:
    issue_by_number = {issue.issue_number: issue for issue in issues}
    counts: dict[int, int] = {}
    for issue in issues:
        if issue.issue_kind != "task":
            continue
        story_issue_numbers = _deduplicate_preserve_order(
            [
                parent_issue_number
                for parent_issue_number in issue.explicit_parent_issue_numbers
                if issue_by_number.get(parent_issue_number) is not None
                and issue_by_number[parent_issue_number].issue_kind == "story"
            ]
        )
        task_type = _infer_task_type(issue=issue, story_issue_numbers=story_issue_numbers)
        is_governance = task_type == "governance"
        if issue.lane is None or (not story_issue_numbers and not is_governance):
            continue
        canonical_story_issue_number = story_issue_numbers[0] if story_issue_numbers else None
        if is_governance:
            if canonical_story_issue_number is None:
                canonical_story_issue_number = INTERNAL_GOVERNANCE_STORY_BY_TASK.get(issue.issue_number)
        if canonical_story_issue_number is None:
            continue
        counts[canonical_story_issue_number] = counts.get(canonical_story_issue_number, 0) + 1
    return counts


def _normalize_lane(lane_label: str) -> str:
    suffix = lane_label.split(":", 1)[1]
    return f"Lane {suffix}"


def _map_status_label_to_work_status(status_label: str | None) -> str:
    mapping = {
        "status:pending": "pending",
        "status:in-progress": "in_progress",
        "status:blocked": "blocked",
        "status:done": "done",
    }
    return mapping.get(status_label, "pending")


def _map_complexity(complexity_label: str | None) -> str:
    if complexity_label is None:
        return "low"
    return complexity_label.split(":", 1)[1]


def _deduplicate_preserve_order(values: list[int]) -> list[int]:
    ordered: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _infer_task_type(
    *,
    issue: GitHubNormalizedIssue,
    story_issue_numbers: list[int],
) -> str:
    normalized_title = issue.title.upper()
    if "-IMPL]" in normalized_title:
        return "core_path"
    if "-DOC]" in normalized_title:
        return "documentation"
    if "-PROC]" in normalized_title or "[PROCESS]" in normalized_title:
        return "governance"
    if normalized_title.startswith("[WAVE"):
        return "governance"
    if len(story_issue_numbers) > 1:
        return "cross_cutting"
    return "core_path"


def _infer_planned_paths(*, issue: GitHubNormalizedIssue) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()

    def add_path(path: str) -> None:
        normalized = path.strip().strip("`").rstrip("*").strip()
        if not normalized:
            return
        normalized = normalized.rstrip("/")
        if normalized.endswith(".md"):
            final = normalized
        else:
            final = normalized + "/"
        if final in seen:
            return
        seen.add(final)
        ordered.append(final)

    allowed_content = _extract_allowed_modify_content(issue.body)
    scan_body = allowed_content or issue.body

    for candidate in CODE_PATH_RE.findall(scan_body):
        if "/" in candidate:
            add_path(candidate)

    lane_doc_root = LANE_DOC_ROOTS.get(issue.lane or "")
    if lane_doc_root is not None and "Domain 0" in scan_body:
        add_path(lane_doc_root)
    if lane_doc_root is not None and "Domain 05 文档" in scan_body:
        add_path(lane_doc_root)
    if lane_doc_root is not None and "Domain 06" in scan_body:
        add_path(lane_doc_root)

    for basename, mapped_path in KNOWN_BASENAME_PATHS.items():
        if basename in scan_body:
            add_path(mapped_path)

    return tuple(ordered)


def _extract_allowed_modify_content(body: str) -> str:
    lines = body.splitlines()
    in_modify_section = False
    collecting_allowed = False
    collected: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            if in_modify_section:
                break
            in_modify_section = heading in {"修改范围", "scope"}
            continue
        if not in_modify_section:
            continue
        lowered = stripped.lower()
        if "允许修改" in stripped or lowered.startswith("- in scope"):
            collecting_allowed = True
            continue
        if "禁止修改" in stripped or lowered.startswith("- out of scope"):
            collecting_allowed = False
            continue
        if collecting_allowed:
            collected.append(line)
    return "\n".join(collected).strip()
