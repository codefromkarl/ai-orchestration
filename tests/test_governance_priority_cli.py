from stardrifter_orchestration_mvp.governance_priority_cli import main


def test_governance_priority_cli_prints_recommendations(monkeypatch, capsys):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )

    snapshot = {
        "active_tasks": [
            {
                "source_issue_number": 69,
                "title": "[Wave0-TASK] 冻结边界定义与签字确认",
                "task_type": "governance",
                "blocking_mode": "hard",
                "status": "pending",
                "story_issue_number": -1901,
                "epic_issue_number": 19,
            }
        ],
        "decomposition_queue": [
            {
                "story_issue_number": 42,
                "story_title": "[Story][W0-A] 文档分析与知识蒸馏",
                "epic_issue_number": 19,
                "execution_status": "decomposing",
                "story_task_count": 0,
            }
        ],
        "refinement_queue": [],
        "gated_epics": [
            {
                "issue_number": 13,
                "title": "[Epic][Lane 01] Campaign Topology 迁移",
                "blocked_dependency_count": 0,
                "active_dependencies": ["#19(active)"],
            },
            {
                "issue_number": 14,
                "title": "[Epic][Lane 02] Fleet Simulation 迁移",
                "blocked_dependency_count": 1,
                "blocked_dependencies": ["#13(gated)"],
            },
        ],
        "planned_epics": [
            {
                "issue_number": 62,
                "title": "[Epic][Lane 07] Data Foundation 数据加载层",
                "execution_status": "planned",
            }
        ],
    }

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter"],
        repository_builder=lambda *, dsn: object(),
        snapshot_loader=lambda **kwargs: snapshot,
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[Priority Now]" in out
    assert "execute task #69" in out
    assert "split story #42" in out
    assert "awaiting-task-decomposition" in out
    assert "[Priority Next]" in out
    assert "activate epic #13" in out
    assert "[Blocked Chain]" in out
    assert "#13(gated)" in out
    assert "[Planned In Tree]" in out
    assert "epic #62" in out


def test_governance_priority_cli_prints_none_sections(monkeypatch, capsys):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )

    empty_snapshot = {
        "active_tasks": [],
        "decomposition_queue": [],
        "refinement_queue": [],
        "gated_epics": [],
        "planned_epics": [],
    }

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter"],
        repository_builder=lambda *, dsn: object(),
        snapshot_loader=lambda **kwargs: empty_snapshot,
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert out.count("none") >= 3
