from __future__ import annotations

import json
from typing import Any, Callable

from ..models import NaturalLanguageIntent

UPDATE_INTENT_PROMOTION_SQL = """
UPDATE natural_language_intent
SET status = 'promoted',
    promoted_epic_issue_number = %s,
    approved_at = NOW(),
    approved_by = %s,
    reviewed_at = NOW(),
    reviewed_by = %s,
    review_action = 'approve',
    review_feedback = NULL,
    updated_at = NOW()
WHERE id = %s
"""


def normalize_promotion_payload(
    proposal: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    epic_payload = proposal.get("epic") if isinstance(proposal, dict) else {}
    if not isinstance(epic_payload, dict):
        epic_payload = {}
    stories_payload = proposal.get("stories") if isinstance(proposal, dict) else []
    if not isinstance(stories_payload, list):
        stories_payload = []
    normalized_stories = [
        story_payload
        for story_payload in stories_payload
        if isinstance(story_payload, dict)
    ]
    return epic_payload, normalized_stories


def promote_intent_proposal_via_cursor(
    *,
    cursor: Any,
    intent: NaturalLanguageIntent,
    intent_id: str,
    approver: str,
    proposal: dict[str, Any],
    intake_epic_start: int,
    intake_story_start: int,
    value_reader: Callable[[Any, str], Any],
) -> int:
    epic_payload, stories_payload = normalize_promotion_payload(proposal)

    cursor.execute(
        "SELECT COALESCE(MAX(issue_number), %s - 1) + 1 AS issue_number FROM program_epic",
        (intake_epic_start,),
    )
    epic_issue_number = int(value_reader(cursor.fetchone(), "issue_number"))
    cursor.execute(
        "SELECT COALESCE(MAX(issue_number), %s - 1) + 1 AS issue_number FROM program_story",
        (intake_story_start,),
    )
    next_story_issue_number = int(value_reader(cursor.fetchone(), "issue_number"))

    cursor.execute(
        """
        INSERT INTO program_epic (
            issue_number, repo, title, lane, program_status,
            execution_status, active_wave, notes
        )
        VALUES (%s, %s, %s, %s, 'approved', 'active', %s, %s)
        """,
        (
            epic_issue_number,
            intent.repo,
            str(epic_payload.get("title") or intent.prompt[:120]),
            epic_payload.get("lane"),
            epic_payload.get("active_wave") or "wave-1",
            epic_payload.get("notes") or f"intake:{intent_id}",
        ),
    )

    story_issue_by_key: dict[str, int] = {}
    story_work_ids: dict[int, list[str]] = {}

    for story_index, story_payload in enumerate(stories_payload, start=1):
        story_issue_number = next_story_issue_number
        next_story_issue_number += 1
        story_key = str(story_payload.get("story_key") or f"S{story_index}")
        story_issue_by_key[story_key] = story_issue_number
        cursor.execute(
            """
            INSERT INTO program_story (
                issue_number, repo, epic_issue_number, title, lane,
                complexity, program_status, execution_status, active_wave, notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'approved', 'active', %s, %s)
            """,
            (
                story_issue_number,
                intent.repo,
                epic_issue_number,
                str(story_payload.get("title") or f"Story {story_index}"),
                story_payload.get("lane") or epic_payload.get("lane"),
                story_payload.get("complexity") or "medium",
                story_payload.get("active_wave")
                or story_payload.get("wave")
                or f"wave-{story_index}",
                f"intake:{intent_id}:{story_key}",
            ),
        )

        story_work_ids[story_issue_number] = []
        tasks_payload = story_payload.get("tasks")
        if not isinstance(tasks_payload, list):
            tasks_payload = []
        for task_index, task_payload in enumerate(tasks_payload, start=1):
            if not isinstance(task_payload, dict):
                continue
            work_id = f"intent-{intent_id}-t{story_index}-{task_index}"
            planned_paths_raw = task_payload.get("planned_paths")
            planned_paths = [
                str(path)
                for path in planned_paths_raw
                if isinstance(path, str) and path.strip()
            ] if isinstance(planned_paths_raw, list) else []
            dod_payload = {
                "story_issue_numbers": [story_issue_number],
                "related_story_issue_numbers": [],
                "planned_paths": planned_paths,
            }
            cursor.execute(
                """
                INSERT INTO work_item (
                    id, repo, title, lane, wave, status, complexity,
                    source_issue_number, canonical_story_issue_number,
                    task_type, blocking_mode, dod_json
                )
                VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    work_id,
                    intent.repo,
                    str(task_payload.get("title") or f"Task {story_index}.{task_index}"),
                    task_payload.get("lane")
                    or story_payload.get("lane")
                    or epic_payload.get("lane")
                    or "Lane 01",
                    task_payload.get("wave") or f"wave-{story_index}",
                    story_payload.get("complexity") or "medium",
                    story_issue_number,
                    story_issue_number,
                    task_payload.get("task_type") or "core_path",
                    task_payload.get("blocking_mode") or "hard",
                    json.dumps(dod_payload, ensure_ascii=False),
                ),
            )
            story_work_ids[story_issue_number].append(work_id)
            cursor.execute(
                """
                INSERT INTO story_task_draft (
                    repo, story_issue_number, title, complexity, goal,
                    allowed_paths_json, dod_json, verification_json,
                    references_json, status, source_reason_code
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, 'proposed', 'natural-language-intake')
                """,
                (
                    intent.repo,
                    story_issue_number,
                    str(task_payload.get("title") or f"Task {story_index}.{task_index}"),
                    story_payload.get("complexity") or "medium",
                    str(task_payload.get("title") or f"Task {story_index}.{task_index}"),
                    json.dumps(planned_paths, ensure_ascii=False),
                    json.dumps(task_payload.get("dod") or [], ensure_ascii=False),
                    json.dumps(task_payload.get("verification") or [], ensure_ascii=False),
                    json.dumps([intent_id], ensure_ascii=False),
                ),
            )

    for story_payload in stories_payload:
        story_key = str(story_payload.get("story_key") or "")
        story_issue_number = story_issue_by_key.get(story_key)
        if story_issue_number is None:
            continue
        depends_on_story_keys = story_payload.get("depends_on_story_keys")
        if not isinstance(depends_on_story_keys, list):
            continue
        for depends_on_story_key in depends_on_story_keys:
            depends_on_issue_number = story_issue_by_key.get(str(depends_on_story_key))
            if depends_on_issue_number is None:
                continue
            cursor.execute(
                """
                INSERT INTO program_story_dependency (repo, story_issue_number, depends_on_story_issue_number)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (intent.repo, story_issue_number, depends_on_issue_number),
            )
            cursor.execute(
                """
                INSERT INTO story_dependency (story_issue_number, depends_on_story_issue_number)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (story_issue_number, depends_on_issue_number),
            )
            for work_id in story_work_ids.get(story_issue_number, []):
                for dependency_work_id in story_work_ids.get(depends_on_issue_number, []):
                    cursor.execute(
                        """
                        INSERT INTO work_dependency (work_id, depends_on_work_id)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (work_id, dependency_work_id),
                    )

    cursor.execute(
        UPDATE_INTENT_PROMOTION_SQL,
        (epic_issue_number, approver, approver, intent_id),
    )
    return epic_issue_number
