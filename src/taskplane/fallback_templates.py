from __future__ import annotations

from typing import Any


def default_fallback_payload_for_story(
    *,
    lane: str,
    story_issue_number: int,
    implementation_story: bool,
) -> dict[str, Any]:
    if implementation_story:
        return {
            "outcome": "decomposed",
            "summary": "created fallback implementation task skeleton for weak-input story",
            "tasks": [
                {
                    "title": f"[{lane}-IMPL] establish minimal implementation path for Story #{story_issue_number}",
                    "complexity": "medium",
                    "goal": (
                        f"为 Story #{story_issue_number} 建立最小可执行的 implementation task，"
                        "确保弱输入 implementation story 也能进入可投影 task 流程。"
                    ),
                    "allowed_paths": default_allowed_paths_for_lane(lane),
                    "dod": [
                        "存在至少一个挂在当前 Story 下的可投影 implementation task",
                        "该 task 为当前 lane 提供最小实现切入点",
                    ],
                    "verification": [
                        "运行当前 lane 相关的 targeted unit/projection tests",
                        "确认 refresh 后 Story 拥有至少一个 canonical task",
                    ],
                    "references": [
                        f"Story #{story_issue_number}",
                        default_execution_plan_reference_for_lane(lane),
                    ],
                },
                {
                    "title": f"[{lane}-TEST] add focused verification for Story #{story_issue_number}",
                    "complexity": "low",
                    "goal": (
                        f"为 Story #{story_issue_number} 建立最小 focused verification task，"
                        "验证 fallback implementation path 的可交付性。"
                    ),
                    "allowed_paths": default_test_paths_for_lane(lane),
                    "dod": [
                        "存在至少一个挂在当前 Story 下的 focused verification task",
                        "验证路径与 implementation task 对齐",
                    ],
                    "verification": [
                        "运行当前 lane 相关的 targeted tests",
                        "确认 fallback task 被正常投影到控制面",
                    ],
                    "references": [
                        f"Story #{story_issue_number}",
                        default_execution_plan_reference_for_lane(lane),
                    ],
                },
            ],
        }

    return {
        "outcome": "decomposed",
        "summary": "created fallback verification task for weak-input story",
        "tasks": [
            {
                "title": f"[{lane}-TEST] establish verification closure for Story #{story_issue_number}",
                "complexity": "medium",
                "goal": (
                    f"为 Story #{story_issue_number} 建立最小可执行的 verification closure task，"
                    "确保弱输入 story 也能进入可投影 task 流程。"
                ),
                "allowed_paths": default_test_paths_for_lane(lane),
                "dod": [
                    "存在至少一个挂在当前 Story 下的可投影 verification task",
                    "该 task 为当前 lane 提供 focused 执行入口",
                ],
                "verification": [
                    "运行当前 lane 相关的 targeted tests 或 test runners",
                    "确认 refresh 后 Story 拥有至少一个 canonical task",
                ],
                "references": [
                    f"Story #{story_issue_number}",
                    default_execution_plan_reference_for_lane(lane),
                ],
            }
        ],
    }


def default_allowed_paths_for_lane(lane: str) -> list[str]:
    if lane == "06":
        return [
            "src/stardrifter_engine/projections/",
            "src/stardrifter_engine/services/",
            "godot/root/",
            "godot/test_runners/",
            "tests/unit/",
            "tests/projections/",
        ]
    if lane == "05":
        return [
            "src/stardrifter_engine/campaign/",
            "src/stardrifter_engine/combat/",
            "godot/root/",
            "tests/unit/",
        ]
    if lane == "02":
        return [
            "src/stardrifter_engine/campaign/",
            "src/stardrifter_engine/resources/",
            "tests/unit/",
        ]
    return ["src/", "tests/"]


def default_test_paths_for_lane(lane: str) -> list[str]:
    if lane == "06":
        return [
            "tests/unit/",
            "tests/projections/",
            "godot/test_runners/",
            "docs/domains/06-projection-save-replay/",
        ]
    if lane == "05":
        return ["tests/unit/", "godot/test_runners/", "docs/domains/05-combat/"]
    if lane == "02":
        return ["tests/unit/", "docs/domains/02-fleet-simulation/"]
    return ["tests/"]


def default_execution_plan_reference_for_lane(lane: str) -> str:
    if lane == "06":
        return "docs/domains/06-projection-save-replay/execution-plan.md"
    if lane == "05":
        return "docs/domains/05-combat/execution-plan.md"
    if lane == "02":
        return "docs/domains/02-fleet-simulation/execution-plan.md"
    return "Story execution plan reference required"
