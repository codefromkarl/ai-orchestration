from __future__ import annotations

from typing import Any

HIGH_CONFIDENCE_THRESHOLD = 0.85


def load_orphans(
    *,
    connection: Any,
    repo: str,
) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                voi.id,
                voi.source_issue_number,
                voi.title,
                voi.status,
                voi.orphan_reason,
                gin.issue_kind,
                gin.explicit_parent_issue_numbers
            FROM v_orphan_work_items voi
            LEFT JOIN github_issue_normalized gin
              ON gin.repo = voi.repo
             AND gin.issue_number = voi.source_issue_number
            WHERE voi.repo = %s
            ORDER BY voi.source_issue_number
            """,
            (repo,),
        )
        return list(cursor.fetchall())


def load_parent_hints(
    *,
    connection: Any,
    repo: str,
    issue_numbers: list[int],
) -> dict[int, list[dict[str, Any]]]:
    if not issue_numbers:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                r.source_issue_number,
                r.target_issue_number,
                r.relation_type,
                r.confidence,
                gin_target.issue_kind AS target_kind
            FROM github_issue_relation r
            LEFT JOIN github_issue_normalized gin_target
              ON gin_target.repo = r.repo
             AND gin_target.issue_number = r.target_issue_number
            WHERE r.repo = %s
              AND r.source_issue_number = ANY(%s)
            ORDER BY r.confidence DESC
            """,
            (repo, issue_numbers),
        )
        rows = list(cursor.fetchall())
    hints: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        src = row["source_issue_number"]
        hints.setdefault(src, []).append(dict(row))
    return hints


def find_parent_candidates(
    *,
    orphan: dict[str, Any],
    hints: list[dict[str, Any]],
    issue_kind: str | None,
) -> list[dict[str, Any]]:
    candidates = []
    for hint in hints:
        target_kind = hint.get("target_kind") or ""
        rel_type = hint.get("relation_type") or ""
        confidence = float(hint.get("confidence") or 0)

        if issue_kind == "task" and target_kind == "story":
            candidates.append(
                {
                    "parent_issue": hint["target_issue_number"],
                    "parent_kind": "story",
                    "confidence": confidence,
                    "reason": f"relation:{rel_type}",
                }
            )
        elif issue_kind == "story" and target_kind == "epic":
            candidates.append(
                {
                    "parent_issue": hint["target_issue_number"],
                    "parent_kind": "epic",
                    "confidence": confidence,
                    "reason": f"relation:{rel_type}",
                }
            )

    explicit_parents = orphan.get("explicit_parent_issue_numbers") or []
    if explicit_parents:
        for parent_num in explicit_parents:
            if not any(c["parent_issue"] == parent_num for c in candidates):
                candidates.append(
                    {
                        "parent_issue": parent_num,
                        "parent_kind": "unknown",
                        "confidence": 0.8,
                        "reason": "explicit_parent",
                    }
                )

    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates


def resolve_orphans(
    *,
    connection: Any,
    repo: str,
    threshold: float = HIGH_CONFIDENCE_THRESHOLD,
    dry_run: bool = False,
) -> dict[str, Any]:
    orphans = load_orphans(connection=connection, repo=repo)
    if not orphans:
        return {"repo": repo, "resolved": 0, "queued_for_review": 0, "actions": []}

    issue_numbers = [
        o["source_issue_number"] for o in orphans if o.get("source_issue_number")
    ]
    hints = load_parent_hints(
        connection=connection, repo=repo, issue_numbers=issue_numbers
    )

    resolved = 0
    queued = 0
    actions = []

    for orphan in orphans:
        issue_num = orphan.get("source_issue_number")
        if not issue_num:
            continue

        issue_kind = orphan.get("issue_kind") or "task"
        orphan_hints = hints.get(issue_num, [])
        candidates = find_parent_candidates(
            orphan=orphan,
            hints=orphan_hints,
            issue_kind=issue_kind,
        )

        best = candidates[0] if candidates else None

        if best and best["confidence"] >= threshold:
            if not dry_run:
                _attach_orphan(
                    connection=connection,
                    repo=repo,
                    orphan_issue=issue_num,
                    parent_issue=best["parent_issue"],
                    issue_kind=issue_kind,
                )
            resolved += 1
            actions.append(
                {
                    "orphan_issue": issue_num,
                    "action": "attached",
                    "target": best["parent_issue"],
                    "parent_kind": best["parent_kind"],
                    "confidence": best["confidence"],
                    "reason": best["reason"],
                }
            )
        else:
            queued += 1
            actions.append(
                {
                    "orphan_issue": issue_num,
                    "action": "queued",
                    "reason": "no_confident_match",
                    "best_candidate": best,
                }
            )

    if not dry_run:
        connection.commit()

    return {
        "repo": repo,
        "resolved": resolved,
        "queued_for_review": queued,
        "actions": actions,
    }


def _attach_orphan(
    *,
    connection: Any,
    repo: str,
    orphan_issue: int,
    parent_issue: int,
    issue_kind: str,
) -> None:
    if issue_kind == "task":
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE work_item
                SET canonical_story_issue_number = %s
                WHERE repo = %s
                  AND source_issue_number = %s
                  AND canonical_story_issue_number IS NULL
                """,
                (parent_issue, repo, orphan_issue),
            )
    elif issue_kind == "story":
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE program_story
                SET epic_issue_number = %s
                WHERE repo = %s
                  AND issue_number = %s
                """,
                (parent_issue, repo, orphan_issue),
            )
