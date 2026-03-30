from stardrifter_orchestration_mvp.github_importer import (
    build_completion_audit,
    extract_relation_candidates,
    normalize_github_issue,
)


def test_normalize_github_issue_imports_closed_issue_as_active():
    raw_issue = {
        "number": 43,
        "title": "[Story][W0-B] GitHub Project 结构初始化",
        "body": "## Background\n\nPart of #19.\n",
        "state": "CLOSED",
        "url": "https://github.com/codefromkarl/stardrifter/issues/43",
        "labels": [
            {"name": "story"},
            {"name": "lane:01"},
        ],
    }

    normalized = normalize_github_issue("codefromkarl/stardrifter", raw_issue)

    assert normalized.issue_number == 43
    assert normalized.github_state == "CLOSED"
    assert normalized.import_state == "active"
    assert normalized.issue_kind == "story"
    assert normalized.lane == "lane:01"
    assert normalized.explicit_parent_issue_numbers == [19]


def test_extract_relation_candidates_preserves_multi_parent_candidates():
    raw_issue = {
        "number": 47,
        "title": "[02-IMPL] fleet logistics/crew/cargo runtime 骨架实现",
        "body": "## 上级 Story\n\n- #24\n- #25\n- #26\n",
        "state": "OPEN",
        "url": "https://github.com/codefromkarl/stardrifter/issues/47",
        "labels": [
            {"name": "task"},
            {"name": "lane:02"},
            {"name": "complexity:high"},
        ],
    }

    normalized = normalize_github_issue("codefromkarl/stardrifter", raw_issue)
    relations = extract_relation_candidates(normalized)

    assert [relation.target_issue_number for relation in relations] == [24, 25, 26]
    assert all(relation.relation_type == "parent_candidate" for relation in relations)


def test_normalize_github_issue_extracts_explicit_story_and_task_dependencies():
    raw_issue = {
        "number": 61,
        "title": "[03-DOC] 依赖显式建模",
        "body": (
            "## 上级 Story\n\n- #29\n\n"
            "## 依赖 Story\n\n- #24\n- #25\n\n"
            "## 依赖 Task\n\n- #44\n- #53\n"
        ),
        "state": "OPEN",
        "url": "https://github.com/codefromkarl/stardrifter/issues/61",
        "labels": [
            {"name": "task"},
            {"name": "lane:03"},
            {"name": "complexity:low"},
        ],
    }

    normalized = normalize_github_issue("codefromkarl/stardrifter", raw_issue)
    relations = extract_relation_candidates(normalized)

    assert normalized.explicit_parent_issue_numbers == [29]
    assert normalized.explicit_story_dependency_issue_numbers == [24, 25]
    assert normalized.explicit_task_dependency_issue_numbers == [44, 53]
    assert [relation.relation_type for relation in relations] == [
        "parent_candidate",
        "story_dependency_candidate",
        "story_dependency_candidate",
        "task_dependency_candidate",
        "task_dependency_candidate",
    ]


def test_normalize_github_issue_ignores_issue_numbers_in_references_section():
    raw_issue = {
        "number": 58,
        "title": "[06-DOC] 定义 Lane INT 或修复 Handoff To 悬空引用",
        "body": (
            "## 背景\n\n这是一个文档修复任务。\n\n"
            "## 参考\n\n- #39\n- #40\n- #41\n"
        ),
        "state": "OPEN",
        "url": "https://github.com/codefromkarl/stardrifter/issues/58",
        "labels": [
            {"name": "task"},
            {"name": "lane:06"},
            {"name": "complexity:medium"},
        ],
    }

    normalized = normalize_github_issue("codefromkarl/stardrifter", raw_issue)
    relations = extract_relation_candidates(normalized)

    assert normalized.explicit_parent_issue_numbers == []
    assert relations == []
    assert "missing-parent-reference" in normalized.anomaly_codes


def test_normalize_github_issue_deduplicates_parent_numbers_from_parent_sections():
    raw_issue = {
        "number": 53,
        "title": "[04-DOC] 补充 04-A/B/C 子任务 status 标记",
        "body": (
            "## 上级 Story\n\n"
            "- #30\n- #31\n- #32\n- #30\n- #31\n- #32\n\n"
            "## 参考\n\n- #99\n"
        ),
        "state": "OPEN",
        "url": "https://github.com/codefromkarl/stardrifter/issues/53",
        "labels": [
            {"name": "task"},
            {"name": "lane:04"},
            {"name": "complexity:low"},
        ],
    }

    normalized = normalize_github_issue("codefromkarl/stardrifter", raw_issue)

    assert normalized.explicit_parent_issue_numbers == [30, 31, 32]


def test_build_completion_audit_marks_story_complete_only_when_all_children_done():
    issues = [
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 29,
                "title": "[Story][03-C] Faction economy profile",
                "body": "Part of #15.",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/29",
                "labels": [{"name": "story"}, {"name": "lane:03"}],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 56,
                "title": "[03-DOC] 为 03-C 三条开放项补充 wave 标记与后续 task 跟踪",
                "body": "## 上级 Story\n\n- #29\n",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/56",
                "labels": [{"name": "task"}, {"name": "status:done"}, {"name": "lane:03"}],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 57,
                "title": "[03-DOC] 在 DoD 下补充整体完成判定声明",
                "body": "## 上级 Story\n\n- #29\n",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/57",
                "labels": [{"name": "task"}, {"name": "status:pending"}, {"name": "lane:03"}],
            },
        ),
    ]
    relations = []
    for issue in issues:
        relations.extend(extract_relation_candidates(issue))

    audit = build_completion_audit(issues, relations)

    assert audit[56].derived_complete is True
    assert audit[57].derived_complete is False
    assert audit[29].derived_complete is False
    assert "child-issues-incomplete" in audit[29].reasons


def test_normalize_github_issue_infers_lane_for_wave_governance_task():
    raw_issue = {
        "number": 69,
        "title": "[Wave0-TASK] 冻结边界定义与签字确认",
        "body": "## 背景\n\nWave 0 governance task.\n",
        "state": "OPEN",
        "url": "https://github.com/codefromkarl/stardrifter/issues/69",
        "labels": [
            {"name": "task"},
            {"name": "status:pending"},
            {"name": "complexity:low"},
        ],
    }

    normalized = normalize_github_issue("codefromkarl/stardrifter", raw_issue)

    assert normalized.lane == "lane:INT"
    assert "missing-lane" not in normalized.anomaly_codes
    assert "missing-parent-reference" not in normalized.anomaly_codes
