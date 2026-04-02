from __future__ import annotations

import re
from typing import Any

from .issue_projection import build_projectable_story_task_counts
from .models import GitHubNormalizedIssue, ProgramEpic, ProgramGovernanceProjection, ProgramStory


ACTIVE_EPIC_EXECUTION_STATUS: dict[int, str] = {
    19: "active",
    13: "gated",
    14: "gated",
    15: "gated",
    16: "gated",
    17: "gated",
    18: "gated",
    20: "backlog",
    62: "planned",
    63: "planned",
    64: "planned",
}

EPIC_DEPENDENCY_OVERRIDES: tuple[tuple[int, int], ...] = (
    (13, 19),
    (14, 13),
    (15, 13),
    (16, 14),
    (16, 15),
    (17, 16),
    (18, 14),
    (18, 15),
    (20, 13),
    (20, 14),
    (20, 15),
    (20, 16),
    (20, 17),
    (20, 18),
    (62, 19),
    (63, 62),
    (63, 17),
    (64, 13),
    (64, 14),
    (64, 17),
    (64, 62),
)

STORY_PARENT_OVERRIDES: dict[int, int] = {
    65: 13,
    66: 14,
    67: 17,
    68: 17,
}

STORY_DEPENDENCY_OVERRIDES: dict[int, tuple[int, ...]] = {
    65: (21, 22, 23),
}

INTERNAL_GOVERNANCE_STORIES: tuple[ProgramStory, ...] = (
    ProgramStory(
        issue_number=-1901,
        repo="codefromkarl/stardrifter",
        epic_issue_number=19,
        title="[Internal][Wave0-G] Freeze Governance",
        lane="lane:INT",
        complexity=None,
        program_status="approved",
        execution_status="active",
        notes="Internal governance container for Wave 0 tasks without formal GitHub story parent.",
    ),
)


def build_program_governance_projection(
    *,
    repo: str,
    issues: list[GitHubNormalizedIssue],
) -> ProgramGovernanceProjection:
    epics: list[ProgramEpic] = []
    stories: list[ProgramStory] = []
    epics_by_number = {
        issue.issue_number: issue
        for issue in issues
        if issue.issue_kind == "epic"
    }
    task_count_by_story_number = build_projectable_story_task_counts(issues=issues)
    story_count_by_epic = _count_stories_by_epic(
        issues=issues, epics_by_number=epics_by_number
    )

    for issue in sorted(epics_by_number.values(), key=lambda item: item.issue_number):
        program_status = "approved"
        execution_status = ACTIVE_EPIC_EXECUTION_STATUS.get(
            issue.issue_number, "backlog"
        )
        if (
            execution_status == "active"
            and story_count_by_epic.get(issue.issue_number, 0) == 0
        ):
            execution_status = "decomposing"
        if issue.github_state != "OPEN":
            program_status = "archived"
            execution_status = "backlog"
        epics.append(
            ProgramEpic(
                issue_number=issue.issue_number,
                repo=repo,
                title=issue.title,
                lane=issue.lane,
                program_status=program_status,
                execution_status=execution_status,
            )
        )

    for issue in sorted(issues, key=lambda item: item.issue_number):
        if issue.issue_kind != "story":
            continue
        epic_issue_number = _resolve_story_parent(issue, epics_by_number)
        program_status = "approved"
        execution_status = "backlog"
        if issue.github_state != "OPEN":
            program_status = "archived"
            execution_status = "done"
        elif issue.issue_number == 52:
            program_status = "proposed"
            execution_status = "backlog"
            epic_issue_number = None
        elif epic_issue_number is not None:
            epic_execution_status = ACTIVE_EPIC_EXECUTION_STATUS.get(
                epic_issue_number, "backlog"
            )
            execution_status = _derive_story_execution_status(
                epic_execution_status=epic_execution_status,
                story_issue_number=issue.issue_number,
                task_count_by_story_number=task_count_by_story_number,
            )
        else:
            program_status = "proposed"
            execution_status = "backlog"
        stories.append(
            ProgramStory(
                issue_number=issue.issue_number,
                repo=repo,
                epic_issue_number=epic_issue_number,
                title=issue.title,
                lane=issue.lane,
                complexity=issue.complexity,
                program_status=program_status,
                execution_status=execution_status,
            )
        )

    stories.extend(
        [
            story
            for story in INTERNAL_GOVERNANCE_STORIES
            if story.repo == repo and 19 in epics_by_number
        ]
    )

    epic_dependencies = sorted(
        [
            dependency
            for dependency in EPIC_DEPENDENCY_OVERRIDES
            if dependency[0] in epics_by_number and dependency[1] in epics_by_number
        ]
    )
    story_numbers = {story.issue_number for story in stories}
    story_dependencies = sorted(
        _build_story_dependencies(issues=issues, known_story_numbers=story_numbers)
    )

    return ProgramGovernanceProjection(
        epics=epics,
        stories=stories,
        epic_dependencies=epic_dependencies,
        story_dependencies=story_dependencies,
    )


def sync_program_governance_to_control_plane(
    *,
    connection: Any,
    repo: str,
    projection: ProgramGovernanceProjection,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT issue_number, program_status, execution_status, active_wave, notes
            FROM program_epic
            WHERE repo = %s
            """,
            (repo,),
        )
        existing_epics = {
            row["issue_number"]: row
            for row in cursor.fetchall()
        }
        cursor.execute(
            """
            SELECT issue_number, program_status, execution_status, active_wave, notes
            FROM program_story
            WHERE repo = %s
            """,
            (repo,),
        )
        existing_stories = {
            row["issue_number"]: row
            for row in cursor.fetchall()
        }
        cursor.execute(
            "DELETE FROM program_story_dependency WHERE repo = %s",
            (repo,),
        )
        cursor.execute(
            "DELETE FROM program_epic_dependency WHERE repo = %s",
            (repo,),
        )
        cursor.execute(
            "DELETE FROM program_story WHERE repo = %s",
            (repo,),
        )
        cursor.execute(
            "DELETE FROM program_epic WHERE repo = %s",
            (repo,),
        )

        for epic in projection.epics:
            preserved_epic = _preserve_existing_governance_state(
                existing_row=existing_epics.get(epic.issue_number),
                program_status=epic.program_status,
                execution_status=epic.execution_status,
                active_wave=epic.active_wave,
                notes=epic.notes,
            )
            cursor.execute(
                """
                INSERT INTO program_epic (
                    issue_number,
                    repo,
                    title,
                    lane,
                    program_status,
                    execution_status,
                    active_wave,
                    notes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    epic.issue_number,
                    epic.repo,
                    epic.title,
                    epic.lane,
                    epic.program_status,
                    preserved_epic["execution_status"],
                    preserved_epic["active_wave"],
                    preserved_epic["notes"],
                ),
            )

        for story in projection.stories:
            preserved_story = _preserve_existing_governance_state(
                existing_row=existing_stories.get(story.issue_number),
                program_status=story.program_status,
                execution_status=story.execution_status,
                active_wave=story.active_wave,
                notes=story.notes,
            )
            cursor.execute(
                """
                INSERT INTO program_story (
                    issue_number,
                    repo,
                    epic_issue_number,
                    title,
                    lane,
                    complexity,
                    program_status,
                    execution_status,
                    active_wave,
                    notes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    story.issue_number,
                    story.repo,
                    story.epic_issue_number,
                    story.title,
                    story.lane,
                    story.complexity,
                    story.program_status,
                    preserved_story["execution_status"],
                    preserved_story["active_wave"],
                    preserved_story["notes"],
                ),
            )

        for epic_issue_number, depends_on_epic_issue_number in projection.epic_dependencies:
            cursor.execute(
                """
                INSERT INTO program_epic_dependency (
                    repo,
                    epic_issue_number,
                    depends_on_epic_issue_number
                )
                VALUES (%s, %s, %s)
                """,
                (repo, epic_issue_number, depends_on_epic_issue_number),
            )

        for story_issue_number, depends_on_story_issue_number in projection.story_dependencies:
            cursor.execute(
                """
                INSERT INTO program_story_dependency (
                    repo,
                    story_issue_number,
                    depends_on_story_issue_number
                )
                VALUES (%s, %s, %s)
                """,
                (repo, story_issue_number, depends_on_story_issue_number),
            )

    connection.commit()


def _preserve_existing_governance_state(
    *,
    existing_row: dict[str, Any] | None,
    program_status: str,
    execution_status: str,
    active_wave: str | None,
    notes: str | None,
) -> dict[str, Any]:
    if (
        existing_row is None
        or program_status != "approved"
        or str(existing_row.get("program_status") or "") != "approved"
    ):
        return {
            "execution_status": execution_status,
            "active_wave": active_wave,
            "notes": notes,
        }
    return {
        "execution_status": str(existing_row.get("execution_status") or execution_status),
        "active_wave": existing_row.get("active_wave") or active_wave,
        "notes": existing_row.get("notes") or notes,
    }


def _resolve_story_parent(
    issue: GitHubNormalizedIssue,
    epics_by_number: dict[int, GitHubNormalizedIssue],
) -> int | None:
    for parent_issue_number in issue.explicit_parent_issue_numbers:
        parent_issue = epics_by_number.get(parent_issue_number)
        if parent_issue is not None and parent_issue.issue_kind == "epic":
            return parent_issue_number
    return STORY_PARENT_OVERRIDES.get(issue.issue_number)


def _build_story_dependencies(
    *,
    issues: list[GitHubNormalizedIssue],
    known_story_numbers: set[int],
) -> set[tuple[int, int]]:
    dependencies: set[tuple[int, int]] = set()
    for issue in issues:
        if issue.issue_kind != "story":
            continue
        targets = set(issue.explicit_story_dependency_issue_numbers)
        targets.update(STORY_DEPENDENCY_OVERRIDES.get(issue.issue_number, ()))
        targets.update(_extract_story_numbers_from_generic_dependency_block(issue.body))
        for target_issue_number in targets:
            if issue.issue_number in known_story_numbers and target_issue_number in known_story_numbers:
                dependencies.add((issue.issue_number, target_issue_number))
    return dependencies


def _derive_story_execution_status(
    *,
    epic_execution_status: str,
    story_issue_number: int,
    task_count_by_story_number: dict[int, int],
) -> str:
    if epic_execution_status != "active":
        return epic_execution_status
    if task_count_by_story_number.get(story_issue_number, 0) > 0:
        return "active"
    return "decomposing"


def _count_stories_by_epic(
    *,
    issues: list[GitHubNormalizedIssue],
    epics_by_number: dict[int, GitHubNormalizedIssue],
) -> dict[int, int]:
    counts: dict[int, int] = {}
    for issue in issues:
        if issue.issue_kind != "story":
            continue
        epic_issue_number = _resolve_story_parent(issue, epics_by_number)
        if epic_issue_number is None:
            continue
        counts[epic_issue_number] = counts.get(epic_issue_number, 0) + 1
    return counts


GENERIC_DEP_RE = re.compile(r"##\s*依赖\s*(.*?)(?:\n##\s+|\Z)", re.S)
ISSUE_OR_STORY_NUM_RE = re.compile(r"#(\d+)|Story\s+0?(\d+)-([A-Z])", re.I)


def _extract_story_numbers_from_generic_dependency_block(body: str) -> set[int]:
    match = GENERIC_DEP_RE.search(body or "")
    if match is None:
        return set()
    content = match.group(1)
    story_numbers: set[int] = set()
    for num_match in re.finditer(r"#(\d+)", content):
        story_numbers.add(int(num_match.group(1)))
    for story_match in re.finditer(r"Story\s+0?(\d+)-([A-Z])", content, flags=re.I):
        lane = int(story_match.group(1))
        suffix = story_match.group(2).upper()
        mapped = _map_story_lane_suffix_to_issue_number(lane, suffix)
        if mapped is not None:
            story_numbers.add(mapped)
    return story_numbers


def _map_story_lane_suffix_to_issue_number(lane: int, suffix: str) -> int | None:
    mapping = {
        (1, "A"): 21,
        (1, "B"): 22,
        (1, "C"): 23,
        (2, "A"): 24,
        (2, "B"): 25,
        (2, "C"): 26,
        (3, "A"): 27,
        (3, "B"): 28,
        (3, "C"): 29,
        (4, "A"): 30,
        (4, "B"): 31,
        (4, "C"): 32,
        (5, "A"): 33,
        (5, "B"): 34,
        (5, "C"): 35,
        (5, "D"): 36,
        (5, "E"): 37,
        (6, "A"): 38,
        (6, "B"): 39,
        (6, "C"): 40,
        (6, "D"): 41,
    }
    return mapping.get((lane, suffix))
