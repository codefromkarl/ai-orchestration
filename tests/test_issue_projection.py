from taskplane.github_importer import (
    build_completion_audit,
    extract_relation_candidates,
    normalize_github_issue,
)
from taskplane.issue_projection import (
    GitHubTaskProjection,
    build_projectable_story_task_counts,
    project_github_tasks_to_work_items,
)


def test_project_github_tasks_to_work_items_builds_story_to_task_mapping():
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
                "labels": [
                    {"name": "task"},
                    {"name": "lane:03"},
                    {"name": "complexity:low"},
                    {"name": "status:done"},
                ],
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
                "labels": [
                    {"name": "task"},
                    {"name": "lane:03"},
                    {"name": "complexity:low"},
                    {"name": "status:pending"},
                ],
            },
        ),
    ]
    relations = []
    for issue in issues:
        relations.extend(extract_relation_candidates(issue))
    completion_audit = build_completion_audit(issues, relations)

    projection = project_github_tasks_to_work_items(
        issues=issues,
        relations=relations,
        completion_audit=completion_audit,
    )

    assert isinstance(projection, GitHubTaskProjection)
    assert [item.id for item in projection.work_items] == ["issue-56", "issue-57"]
    assert projection.story_task_ids == {29: ["issue-56", "issue-57"]}
    assert projection.work_items[0].status == "done"
    assert projection.work_items[1].status == "pending"


def test_project_github_tasks_to_work_items_marks_missing_parent_tasks_for_triage():
    issues = [
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 60,
                "title": "[PROCESS] 建立人机协作开发规范",
                "body": "## 背景\n\nprocess work.\n",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/60",
                "labels": [
                    {"name": "task"},
                    {"name": "complexity:low"},
                    {"name": "status:in-progress"},
                ],
            },
        )
    ]
    relations = []
    completion_audit = build_completion_audit(issues, relations)

    projection = project_github_tasks_to_work_items(
        issues=issues,
        relations=relations,
        completion_audit=completion_audit,
    )

    assert projection.work_items == []
    assert projection.needs_triage_issue_numbers == [60]


def test_project_github_tasks_to_work_items_maps_wave0_impl_task_to_internal_governance_story():
    issues = [
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 74,
                "title": "[Wave0-IMPL] 将 freeze boundary 注册为 control-plane frozen targets",
                "body": "## 背景\n\nWave 0 governance task.\n",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/74",
                "labels": [
                    {"name": "task"},
                    {"name": "complexity:medium"},
                    {"name": "status:pending"},
                ],
            },
        )
    ]
    completion_audit = build_completion_audit(issues, [])

    projection = project_github_tasks_to_work_items(
        issues=issues,
        relations=[],
        completion_audit=completion_audit,
    )

    assert [item.id for item in projection.work_items] == ["issue-74"]
    assert projection.work_items[0].task_type == "governance"
    assert projection.work_items[0].canonical_story_issue_number == -1901
    assert projection.needs_triage_issue_numbers == []


def test_project_github_tasks_to_work_items_builds_explicit_dependencies():
    issues = [
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 24,
                "title": "[Story][02-A] Fleet simulation foundations",
                "body": "Part of #15.",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/24",
                "labels": [{"name": "story"}, {"name": "lane:02"}],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 29,
                "title": "[Story][03-C] Faction economy profile",
                "body": "Part of #15.\n\n## 依赖 Story\n\n- #24\n",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/29",
                "labels": [{"name": "story"}, {"name": "lane:03"}],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 44,
                "title": "[01-DOC] 上游 task",
                "body": "## 上级 Story\n\n- #24\n",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/44",
                "labels": [
                    {"name": "task"},
                    {"name": "lane:02"},
                    {"name": "status:done"},
                ],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 56,
                "title": "[03-DOC] 显式依赖",
                "body": "## 上级 Story\n\n- #29\n\n## 依赖 Task\n\n- #44\n",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/56",
                "labels": [
                    {"name": "task"},
                    {"name": "lane:03"},
                    {"name": "status:pending"},
                ],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 57,
                "title": "[03-DOC] 依赖 Story",
                "body": "## 上级 Story\n\n- #29\n\n## 依赖 Story\n\n- #24\n",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/57",
                "labels": [
                    {"name": "task"},
                    {"name": "lane:03"},
                    {"name": "status:pending"},
                ],
            },
        ),
    ]
    relations = []
    for issue in issues:
        relations.extend(extract_relation_candidates(issue))
    completion_audit = build_completion_audit(issues, relations)

    projection = project_github_tasks_to_work_items(
        issues=issues,
        relations=relations,
        completion_audit=completion_audit,
    )

    assert projection.story_dependencies == [(29, 24)]
    assert projection.story_task_ids == {24: ["issue-44"], 29: ["issue-56", "issue-57"]}
    assert [
        (dep.work_id, dep.depends_on_work_id) for dep in projection.work_dependencies
    ] == [
        ("issue-56", "issue-44"),
        ("issue-57", "issue-44"),
    ]


def test_project_github_tasks_to_work_items_uses_canonical_parent_for_multi_story_tasks():
    issues = [
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 30,
                "title": "[Story][04-A] Detection / contact trigger",
                "body": "Part of #16.",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/30",
                "labels": [{"name": "story"}, {"name": "lane:04"}],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 31,
                "title": "[Story][04-B] Scene family grounding",
                "body": "Part of #16.",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/31",
                "labels": [{"name": "story"}, {"name": "lane:04"}],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 32,
                "title": "[Story][04-C] Conflict escalation contract",
                "body": "Part of #16.",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/32",
                "labels": [{"name": "story"}, {"name": "lane:04"}],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 53,
                "title": "[04-DOC] 补充 04-A/B/C 子任务 status 标记",
                "body": "## 上级 Story\n\n- #30\n- #31\n- #32\n",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/53",
                "labels": [
                    {"name": "task"},
                    {"name": "lane:04"},
                    {"name": "complexity:low"},
                    {"name": "status:pending"},
                ],
            },
        ),
    ]
    relations = []
    for issue in issues:
        relations.extend(extract_relation_candidates(issue))
    completion_audit = build_completion_audit(issues, relations)

    projection = project_github_tasks_to_work_items(
        issues=issues,
        relations=relations,
        completion_audit=completion_audit,
    )

    assert projection.story_task_ids == {30: ["issue-53"]}
    assert projection.work_items[0].canonical_story_issue_number == 30
    assert projection.work_items[0].related_story_issue_numbers == (31, 32)
    assert projection.work_items[0].task_type == "documentation"
    assert projection.work_items[0].blocking_mode == "soft"


def test_project_github_tasks_to_work_items_projects_wave_governance_task_without_story_parent():
    issues = [
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 69,
                "title": "[Wave0-TASK] 冻结边界定义与签字确认",
                "body": (
                    "## DoD\n\n"
                    "- [ ] 在 repo 中创建 `docs/baselines/wave0-freeze.md` 记录上述清单\n"
                ),
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/69",
                "labels": [
                    {"name": "task"},
                    {"name": "status:pending"},
                    {"name": "complexity:low"},
                ],
            },
        ),
    ]
    completion_audit = build_completion_audit(issues, [])

    projection = project_github_tasks_to_work_items(
        issues=issues,
        relations=[],
        completion_audit=completion_audit,
    )

    assert projection.needs_triage_issue_numbers == []
    assert [item.id for item in projection.work_items] == ["issue-69"]
    assert projection.work_items[0].canonical_story_issue_number == -1901
    assert projection.work_items[0].task_type == "governance"
    assert projection.work_items[0].blocking_mode == "hard"
    assert projection.work_items[0].planned_paths == ("docs/baselines/wave0-freeze.md",)


def test_project_github_tasks_to_work_items_keeps_explicit_story_parent_for_governance_task():
    issues = [
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 42,
                "title": "[Story][W0-A] 文档分析与知识蒸馏",
                "body": "Part of #19.",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/42",
                "labels": [{"name": "story"}, {"name": "lane:01"}],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 69,
                "title": "[Wave0-TASK] 冻结边界定义与签字确认",
                "body": (
                    "Part of #19.\n\n"
                    "## 上级 Story\n\n"
                    "- #42\n\n"
                    "## 修改范围\n\n"
                    "- `docs/baselines/wave0-freeze.md`\n"
                ),
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/69",
                "labels": [
                    {"name": "task"},
                    {"name": "lane:01"},
                    {"name": "complexity:low"},
                    {"name": "status:pending"},
                ],
            },
        ),
    ]
    relations = []
    for issue in issues:
        relations.extend(extract_relation_candidates(issue))
    completion_audit = build_completion_audit(issues, relations)

    projection = project_github_tasks_to_work_items(
        issues=issues,
        relations=relations,
        completion_audit=completion_audit,
    )

    assert projection.needs_triage_issue_numbers == []
    assert [item.id for item in projection.work_items] == ["issue-69"]
    assert projection.work_items[0].canonical_story_issue_number == 42
    assert projection.story_task_ids == {42: ["issue-69"]}
    assert projection.work_items[0].task_type == "governance"
    assert projection.work_items[0].blocking_mode == "hard"


def test_project_github_tasks_to_work_items_classifies_wave_impl_task_as_core_path():
    issues = [
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 42,
                "title": "[Story][W0-A] 文档分析与知识蒸馏",
                "body": "Part of #19.",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/42",
                "labels": [{"name": "story"}, {"name": "lane:01"}],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 69,
                "title": "[Wave0-TASK] 冻结边界定义与签字确认",
                "body": (
                    "## 上级 Story\n\n"
                    "- #42\n\n"
                    "## 修改范围\n\n"
                    "- `docs/baselines/wave0-freeze.md`\n"
                ),
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/69",
                "labels": [
                    {"name": "task"},
                    {"name": "lane:01"},
                    {"name": "complexity:low"},
                    {"name": "status:done"},
                ],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 74,
                "title": "[Wave0-IMPL] 将 freeze boundary 注册为 control-plane frozen targets",
                "body": ("## 上级 Story\n\n- #42\n\n## 依赖 Task\n\n- #69\n"),
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/74",
                "labels": [
                    {"name": "task"},
                    {"name": "lane:01"},
                    {"name": "complexity:medium"},
                    {"name": "status:pending"},
                ],
            },
        ),
    ]
    relations = []
    for issue in issues:
        relations.extend(extract_relation_candidates(issue))
    completion_audit = build_completion_audit(issues, relations)

    projection = project_github_tasks_to_work_items(
        issues=issues,
        relations=relations,
        completion_audit=completion_audit,
    )

    issue_74 = next(item for item in projection.work_items if item.id == "issue-74")
    assert issue_74.canonical_story_issue_number == 42
    assert issue_74.task_type == "core_path"
    assert issue_74.blocking_mode == "hard"
    assert ("issue-74", "issue-69") in {
        (dependency.work_id, dependency.depends_on_work_id)
        for dependency in projection.work_dependencies
    }


def test_project_github_tasks_to_work_items_extracts_planned_paths_from_allowed_modify_section():
    issues = [
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 61,
                "title": "[02-IMPL] fleet logistics/crew/cargo backend runtime skeleton",
                "body": (
                    "## 上级 Story\n\n- #24\n\n"
                    "## 修改范围\n\n"
                    "- 允许修改：\n"
                    "- `src/stardrifter_engine/campaign/*`\n"
                    "- `src/stardrifter_engine/resources/*`\n"
                ),
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/61",
                "labels": [
                    {"name": "task"},
                    {"name": "lane:02"},
                    {"name": "complexity:medium"},
                    {"name": "status:pending"},
                ],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 24,
                "title": "[Story][02-A] Fleet truth model",
                "body": "Part of #14.",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/24",
                "labels": [{"name": "story"}, {"name": "lane:02"}],
            },
        ),
    ]
    relations = []
    for issue in issues:
        relations.extend(extract_relation_candidates(issue))
    completion_audit = build_completion_audit(issues, relations)

    projection = project_github_tasks_to_work_items(
        issues=issues,
        relations=relations,
        completion_audit=completion_audit,
    )

    assert projection.work_items[0].planned_paths == (
        "src/stardrifter_engine/campaign/",
        "src/stardrifter_engine/resources/",
    )


def test_project_github_tasks_to_work_items_projects_lane_08_issue_63_task():
    issues = [
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 72,
                "title": "[Story][08-A] Lane 08 execution anchor",
                "body": "Part of #63.",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/72",
                "labels": [{"name": "story"}, {"name": "lane:08"}],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 63,
                "title": "[08-DOC] Add minimal Lane 08 orchestration execution slice",
                "body": (
                    "Part of #63.\n\n"
                    "## 上级 Story\n\n"
                    "- #72\n\n"
                    "## 修改范围\n\n"
                    "- `tests/test_supervisor_loop.py`\n"
                ),
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/63",
                "labels": [
                    {"name": "task"},
                    {"name": "lane:08"},
                    {"name": "complexity:low"},
                    {"name": "status:pending"},
                ],
            },
        ),
    ]
    relations = []
    for issue in issues:
        relations.extend(extract_relation_candidates(issue))
    completion_audit = build_completion_audit(issues, relations)

    projection = project_github_tasks_to_work_items(
        issues=issues,
        relations=relations,
        completion_audit=completion_audit,
    )

    assert projection.needs_triage_issue_numbers == []
    assert projection.story_task_ids == {72: ["issue-63"]}
    assert [item.id for item in projection.work_items] == ["issue-63"]
    assert projection.work_items[0].lane == "Lane 08"
    assert projection.work_items[0].source_issue_number == 63
    assert projection.work_items[0].canonical_story_issue_number == 72
    assert projection.work_items[0].planned_paths == ("tests/test_supervisor_loop.py/",)


def test_build_projectable_story_task_counts_prefers_explicit_story_parent_for_governance_task():
    issues = [
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 42,
                "title": "[Story][W0-A] 文档分析与知识蒸馏",
                "body": "Part of #19.",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/42",
                "labels": [{"name": "story"}, {"name": "lane:01"}],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 60,
                "title": "[PROCESS] 建立人机协作开发规范 (CONTRIBUTING.md + AGENTS.md)",
                "body": "## 上级 Story\n\n- #42\n",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/60",
                "labels": [
                    {"name": "task"},
                    {"name": "lane:01"},
                    {"name": "status:done"},
                    {"name": "complexity:low"},
                ],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 69,
                "title": "[Wave0-TASK] 冻结边界定义与签字确认",
                "body": "## DoD\n\n- [ ] 在 repo 中创建 `docs/baselines/wave0-freeze.md`\n",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/69",
                "labels": [
                    {"name": "task"},
                    {"name": "status:pending"},
                    {"name": "complexity:low"},
                ],
            },
        ),
    ]

    counts = build_projectable_story_task_counts(issues=issues)

    assert counts[42] == 1
    assert counts[-1901] == 1


def test_project_github_tasks_to_work_items_ignores_forbidden_paths_when_building_planned_paths():
    issues = [
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 54,
                "title": "[04-DOC] 说明 pending_scene 当前实际状态",
                "body": (
                    "## 上级 Story\n\n- #30\n\n"
                    "## 修改范围\n\n"
                    "- 允许修改：\n"
                    "- `docs/domains/04-encounter-mediation/README.md`\n"
                    "- `docs/domains/04-encounter-mediation/execution-plan.md`\n"
                    "- 禁止修改：\n"
                    "- `src/stardrifter_engine/projections/godot_map_projection.py`\n"
                    "- `godot/strategic_map/*`\n"
                ),
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/54",
                "labels": [
                    {"name": "task"},
                    {"name": "lane:04"},
                    {"name": "complexity:low"},
                    {"name": "status:blocked"},
                ],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 30,
                "title": "[Story][04-A] Detection / contact trigger",
                "body": "Part of #16.",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/30",
                "labels": [{"name": "story"}, {"name": "lane:04"}],
            },
        ),
    ]
    relations = []
    for issue in issues:
        relations.extend(extract_relation_candidates(issue))
    completion_audit = build_completion_audit(issues, relations)

    projection = project_github_tasks_to_work_items(
        issues=issues,
        relations=relations,
        completion_audit=completion_audit,
    )

    assert projection.work_items[0].planned_paths == (
        "docs/domains/04-encounter-mediation/README.md",
        "docs/domains/04-encounter-mediation/execution-plan.md",
    )


def test_project_github_tasks_to_work_items_maps_known_baseline_doc_filenames():
    issues = [
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 49,
                "title": "[05-DOC] 将 combat-mainline 扩展任务分解为 05-F/G 子任务",
                "body": (
                    "## 上级 Story\n\n- #33\n\n"
                    "## 修改范围\n\n"
                    "- 允许修改：\n"
                    "- starsector-combat-mainline-migration-plan.md 与 Domain 05 文档\n"
                ),
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/49",
                "labels": [
                    {"name": "task"},
                    {"name": "lane:05"},
                    {"name": "complexity:medium"},
                    {"name": "status:pending"},
                ],
            },
        ),
        normalize_github_issue(
            "codefromkarl/stardrifter",
            {
                "number": 33,
                "title": "[Story][05-A] Combat loop shell",
                "body": "Part of #17.",
                "state": "OPEN",
                "url": "https://github.com/codefromkarl/stardrifter/issues/33",
                "labels": [{"name": "story"}, {"name": "lane:05"}],
            },
        ),
    ]
    relations = []
    for issue in issues:
        relations.extend(extract_relation_candidates(issue))
    completion_audit = build_completion_audit(issues, relations)

    projection = project_github_tasks_to_work_items(
        issues=issues,
        relations=relations,
        completion_audit=completion_audit,
    )

    assert projection.work_items[0].planned_paths == (
        "docs/domains/05-combat-handoff/",
        "docs/project/implementation/baselines/starsector-combat-mainline-migration-plan.md",
    )
