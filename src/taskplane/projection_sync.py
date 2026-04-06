from __future__ import annotations

import json
from typing import Any

from .github_importer import build_completion_audit, extract_relation_candidates
from .issue_projection import project_github_tasks_to_work_items
from .models import (
    CompletionAudit,
    GitHubNormalizedIssue,
    GitHubRelationCandidate,
    GitHubTaskProjection,
)

WAVE0_FROZEN_TARGET_PATHS: tuple[str, ...] = (
    "docs/baselines/wave0-freeze.md",
    "data/campaign/authored/campaign_map.json",
    "data/campaign/authored/campaign_systems.json",
    "data/campaign/authored/campaign_markets.json",
    "data/campaign/authored/campaign_hazards.json",
    "data/campaign/authored/campaign_transit_nodes.json",
    "data/campaign/authored/campaign_abilities.json",
    "data/campaign/authored/campaign_overrides.json",
    "data/campaign/authored/campaign_faction_economy.json",
    "data/campaign/authored/campaign_commodities.json",
    "data/campaign/authored/campaign_industries.json",
    "data/campaign/authored/campaign_submarkets.json",
    "godot/bridge/command_bridge.gd",
    "src/stardrifter_engine/services/world_query_service.py",
    "src/stardrifter_engine/campaign/authored_repository.py",
)
FROZEN_TARGET_PREFIXES: tuple[str, ...] = (
    "docs/authority/",
)


def load_projection_from_staging(
    *,
    connection: Any,
    repo: str,
) -> GitHubTaskProjection:
    issues = _load_normalized_issues(connection=connection, repo=repo)
    relations = _load_relation_candidates(connection=connection, repo=repo)
    completion_audit = _load_completion_audit(connection=connection, repo=repo)
    if not completion_audit:
        completion_audit = build_completion_audit(issues, relations)
    return project_github_tasks_to_work_items(
        issues=issues,
        relations=relations,
        completion_audit=completion_audit,
    )


def sync_projection_to_control_plane(
    *,
    connection: Any,
    repo: str,
    projection: GitHubTaskProjection,
) -> None:
    with connection.cursor() as cursor:
        source_issue_numbers = [
            work_item.source_issue_number
            for work_item in projection.work_items
            if work_item.source_issue_number is not None
        ]
        cursor.execute(
            """
            DELETE FROM work_dependency
            WHERE work_id IN (
                SELECT id
                FROM work_item
                WHERE repo = %s
            )
               OR depends_on_work_id IN (
                SELECT id
                FROM work_item
                WHERE repo = %s
            )
            """,
            (repo, repo),
        )
        cursor.execute(
            """
            DELETE FROM story_dependency
            WHERE story_issue_number IN (
                SELECT DISTINCT jsonb_array_elements_text(dod_json->'story_issue_numbers')::int
                FROM work_item
                WHERE repo = %s
            )
            """,
            (repo,),
        )
        cursor.execute(
            """
            DELETE FROM work_target
            WHERE work_id IN (
                SELECT id
                FROM work_item
                WHERE repo = %s
            )
            """,
            (repo,),
        )
        if source_issue_numbers:
            cursor.execute(
                """
                DELETE FROM work_item
                WHERE repo = %s
                  AND source_issue_number <> ALL(%s)
                """,
                (repo, source_issue_numbers),
            )
        else:
            cursor.execute(
                """
                DELETE FROM work_item
                WHERE repo = %s
                """,
                (repo,),
            )

        for work_item in projection.work_items:
            cursor.execute(
                """
                INSERT INTO work_item (
                    id,
                    repo,
                    title,
                    lane,
                    wave,
                    status,
                    complexity,
                    source_issue_number,
                    canonical_story_issue_number,
                    task_type,
                    blocking_mode,
                    dod_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    repo = EXCLUDED.repo,
                    title = EXCLUDED.title,
                    lane = EXCLUDED.lane,
                    wave = EXCLUDED.wave,
                    complexity = EXCLUDED.complexity,
                    source_issue_number = EXCLUDED.source_issue_number,
                    canonical_story_issue_number = EXCLUDED.canonical_story_issue_number,
                    task_type = EXCLUDED.task_type,
                    blocking_mode = EXCLUDED.blocking_mode,
                    dod_json = EXCLUDED.dod_json,
                    status = work_item.status,
                    blocked_reason = work_item.blocked_reason,
                    decision_required = work_item.decision_required,
                    updated_at = NOW()
                """,
                (
                    work_item.id,
                    repo,
                    work_item.title,
                    work_item.lane,
                    work_item.wave,
                    work_item.status,
                    work_item.complexity,
                    work_item.source_issue_number,
                    work_item.canonical_story_issue_number,
                    work_item.task_type,
                    work_item.blocking_mode,
                    json.dumps(
                        {
                            "story_issue_numbers": list(work_item.story_issue_numbers),
                            "related_story_issue_numbers": list(
                                work_item.related_story_issue_numbers
                            ),
                            "planned_paths": list(work_item.planned_paths),
                            "repo": repo,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            for target_path in _deduplicate_paths(work_item.planned_paths):
                is_frozen = _is_frozen_target(target_path)
                cursor.execute(
                    """
                    INSERT INTO work_target (
                        work_id,
                        target_path,
                        target_type,
                        owner_lane,
                        is_frozen,
                        requires_human_approval
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        work_item.id,
                        target_path,
                        _infer_target_type(target_path),
                        work_item.lane,
                        is_frozen,
                        is_frozen,
                    ),
                )

        for dependency in projection.work_dependencies:
            cursor.execute(
                """
                INSERT INTO work_dependency (work_id, depends_on_work_id)
                VALUES (%s, %s)
                ON CONFLICT (work_id, depends_on_work_id) DO NOTHING
                """,
                (dependency.work_id, dependency.depends_on_work_id),
            )

        for (
            story_issue_number,
            depends_on_story_issue_number,
        ) in projection.story_dependencies:
            cursor.execute(
                """
                INSERT INTO story_dependency (story_issue_number, depends_on_story_issue_number)
                VALUES (%s, %s)
                ON CONFLICT (story_issue_number, depends_on_story_issue_number) DO NOTHING
                """,
                (story_issue_number, depends_on_story_issue_number),
            )

    connection.commit()


def _deduplicate_paths(paths: tuple[str, ...]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for path in paths:
        normalized = path.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _infer_target_type(path: str) -> str:
    normalized = path.rstrip("/")
    if normalized.startswith("tests/") or normalized.endswith("_test.py"):
        return "test"
    if normalized.startswith("docs/") or normalized.endswith(".md"):
        return "doc"
    if "." not in normalized.rsplit("/", 1)[-1]:
        return "dir"
    return "file"


def _is_frozen_target(path: str) -> bool:
    return path in WAVE0_FROZEN_TARGET_PATHS or path.startswith(
        FROZEN_TARGET_PREFIXES
    )


def _load_normalized_issues(
    *, connection: Any, repo: str
) -> list[GitHubNormalizedIssue]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT repo, issue_number, title, body, url, github_state, import_state,
                   issue_kind, lane, complexity, status_label,
                   explicit_parent_issue_numbers,
                   explicit_story_dependency_issue_numbers,
                   explicit_task_dependency_issue_numbers,
                   anomaly_codes
            FROM github_issue_normalized
            WHERE repo = %s
            ORDER BY issue_number
            """,
            (repo,),
        )
        rows = cursor.fetchall()
    return [
        GitHubNormalizedIssue(
            repo=row["repo"],
            issue_number=row["issue_number"],
            title=row["title"],
            body=row["body"],
            url=row["url"],
            github_state=row["github_state"],
            import_state=row["import_state"],
            issue_kind=row["issue_kind"],
            lane=row["lane"],
            complexity=row["complexity"],
            status_label=row["status_label"],
            explicit_parent_issue_numbers=list(
                row["explicit_parent_issue_numbers"] or []
            ),
            explicit_story_dependency_issue_numbers=list(
                row.get("explicit_story_dependency_issue_numbers") or []
            ),
            explicit_task_dependency_issue_numbers=list(
                row.get("explicit_task_dependency_issue_numbers") or []
            ),
            anomaly_codes=list(row["anomaly_codes"] or []),
        )
        for row in rows
    ]


def _load_relation_candidates(
    *, connection: Any, repo: str
) -> list[GitHubRelationCandidate]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_issue_number, target_issue_number, relation_type, confidence, evidence_text
            FROM github_issue_relation
            WHERE repo = %s
            ORDER BY source_issue_number, target_issue_number
            """,
            (repo,),
        )
        rows = cursor.fetchall()
    return [
        GitHubRelationCandidate(
            source_issue_number=row["source_issue_number"],
            target_issue_number=row["target_issue_number"],
            relation_type=row["relation_type"],
            confidence=float(row["confidence"]),
            evidence_text=row["evidence_text"],
        )
        for row in rows
    ]


def _load_completion_audit(*, connection: Any, repo: str) -> dict[int, CompletionAudit]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT issue_number, derived_complete, reasons
            FROM github_issue_completion_audit
            WHERE repo = %s
            """,
            (repo,),
        )
        rows = cursor.fetchall()
    return {
        row["issue_number"]: CompletionAudit(
            issue_number=row["issue_number"],
            derived_complete=row["derived_complete"],
            reasons=list(row["reasons"] or []),
        )
        for row in rows
    }
