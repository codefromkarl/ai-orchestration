from __future__ import annotations

from typing import Any


DEFAULT_WEIGHTS: dict[str, float] = {
    "orphan_ratio": 0.25,
    "decomposition_depth": 0.20,
    "blocked_ratio": 0.25,
    "decision_ratio": 0.15,
    "stale_epic_ratio": 0.15,
}


def load_health_metrics(
    *,
    connection: Any,
    repo: str,
) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS total FROM work_item WHERE repo = %s",
            (repo,),
        )
        total_items = (cursor.fetchone() or {}).get("total", 0) or 0

        cursor.execute(
            "SELECT COUNT(*) AS total FROM v_orphan_work_items WHERE repo = %s",
            (repo,),
        )
        orphan_count = (cursor.fetchone() or {}).get("total", 0) or 0

        cursor.execute(
            "SELECT COUNT(*) AS total FROM v_epic_decomposition_queue WHERE repo = %s",
            (repo,),
        )
        epic_decomp = (cursor.fetchone() or {}).get("total", 0) or 0

        cursor.execute(
            "SELECT COUNT(*) AS total FROM v_story_decomposition_queue WHERE repo = %s",
            (repo,),
        )
        story_decomp = (cursor.fetchone() or {}).get("total", 0) or 0

        cursor.execute(
            "SELECT COUNT(*) AS total FROM v_active_task_queue WHERE repo = %s AND status = 'blocked'",
            (repo,),
        )
        blocked_count = (cursor.fetchone() or {}).get("total", 0) or 0

        cursor.execute(
            "SELECT COUNT(*) AS total FROM v_active_task_queue WHERE repo = %s",
            (repo,),
        )
        active_task_count = (cursor.fetchone() or {}).get("total", 0) or 0

        cursor.execute(
            "SELECT COUNT(*) AS total FROM v_active_task_queue WHERE repo = %s AND decision_required = true",
            (repo,),
        )
        decision_count = (cursor.fetchone() or {}).get("total", 0) or 0

        cursor.execute(
            "SELECT COUNT(*) AS total FROM program_epic WHERE repo = %s AND execution_status NOT IN ('done', 'backlog')",
            (repo,),
        )
        active_epic_count = (cursor.fetchone() or {}).get("total", 0) or 0

    return {
        "total_items": total_items,
        "orphan_count": orphan_count,
        "epic_decomposition_queue": epic_decomp,
        "story_decomposition_queue": story_decomp,
        "blocked_count": blocked_count,
        "active_task_count": active_task_count,
        "decision_count": decision_count,
        "active_epic_count": active_epic_count,
    }


def compute_health_score(
    *,
    metrics: dict[str, Any],
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    w = weights or DEFAULT_WEIGHTS
    total = max(1, metrics["total_items"])
    active = max(1, metrics["active_task_count"])

    orphan_ratio = metrics["orphan_count"] / total
    decomp_depth = min(
        1.0,
        (metrics["epic_decomposition_queue"] + metrics["story_decomposition_queue"])
        / max(1, metrics["active_epic_count"] * 3),
    )
    blocked_ratio = metrics["blocked_count"] / active
    decision_ratio = metrics["decision_count"] / active
    stale_ratio = min(
        1.0, metrics["epic_decomposition_queue"] / max(1, metrics["active_epic_count"])
    )

    signals = {
        "orphan_ratio": {
            "value": round(orphan_ratio, 4),
            "weight": w["orphan_ratio"],
            "score": round(max(0, 1 - orphan_ratio * 5), 3),
        },
        "decomposition_depth": {
            "value": metrics["epic_decomposition_queue"]
            + metrics["story_decomposition_queue"],
            "weight": w["decomposition_depth"],
            "score": round(max(0, 1 - decomp_depth), 3),
        },
        "blocked_ratio": {
            "value": round(blocked_ratio, 4),
            "weight": w["blocked_ratio"],
            "score": round(max(0, 1 - blocked_ratio * 3), 3),
        },
        "decision_ratio": {
            "value": round(decision_ratio, 4),
            "weight": w["decision_ratio"],
            "score": round(max(0, 1 - decision_ratio * 2), 3),
        },
        "stale_epic_ratio": {
            "value": round(stale_ratio, 4),
            "weight": w["stale_epic_ratio"],
            "score": round(max(0, 1 - stale_ratio), 3),
        },
    }

    overall = sum(s["score"] * s["weight"] for s in signals.values())
    overall = round(min(1.0, max(0.0, overall)), 3)

    if overall >= 0.9:
        grade = "A"
    elif overall >= 0.75:
        grade = "B"
    elif overall >= 0.6:
        grade = "C"
    elif overall >= 0.4:
        grade = "D"
    else:
        grade = "F"

    return {"overall_score": overall, "grade": grade, "signals": signals}


def build_health_response(
    *,
    repo: str,
    metrics: dict[str, Any],
    health: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    return {
        "repo": repo,
        "generated_at": generated_at,
        "overall_score": health["overall_score"],
        "grade": health["grade"],
        "metrics": {
            "total_items": metrics["total_items"],
            "orphan_count": metrics["orphan_count"],
            "epic_decomposition_queue": metrics["epic_decomposition_queue"],
            "story_decomposition_queue": metrics["story_decomposition_queue"],
            "blocked_count": metrics["blocked_count"],
            "decision_count": metrics["decision_count"],
        },
        "signals": health["signals"],
    }
