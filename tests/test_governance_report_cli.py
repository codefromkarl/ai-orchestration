from taskplane.governance_report_cli import main
from taskplane.governance_report_cli import _load_report_rows


def test_governance_report_cli_prints_summary(monkeypatch, capsys):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )

    class FakeRepository:
        pass

    rows = [
        {
            "epic_issue_number": 19,
            "epic_title": "[Epic][Wave 0] Freeze 基线锁定",
            "epic_execution_status": "active",
            "story_issue_number": 42,
            "story_title": "[Story][W0-A] 文档分析与知识蒸馏",
            "story_execution_status": "done",
            "story_task_count": 1,
            "story_active_task_count": 0,
        },
        {
            "epic_issue_number": 19,
            "epic_title": "[Epic][Wave 0] Freeze 基线锁定",
            "epic_execution_status": "active",
            "story_issue_number": -1901,
            "story_title": "[Internal][Wave0-G] Freeze Governance",
            "story_execution_status": "active",
            "story_task_count": 1,
            "story_active_task_count": 1,
        },
    ]

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter"],
        repository_builder=lambda *, dsn: FakeRepository(),
        report_loader=lambda **kwargs: rows,
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "[Epic #19]" in out
    assert "[Story #42]" in out
    assert "[Story #-1901]" in out
    assert "active_epics=1" in out


def test_governance_report_cli_marks_active_story_without_task_container(monkeypatch, capsys):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )

    rows = [
        {
            "epic_issue_number": 13,
            "epic_title": "[Epic][Lane 01] Campaign Topology 迁移",
            "epic_execution_status": "active",
            "story_issue_number": 22,
            "story_title": "[Story][01-B] Canonical geometry 入库",
            "story_execution_status": "active",
            "story_task_count": 0,
            "story_active_task_count": 0,
        }
    ]

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter"],
        repository_builder=lambda *, dsn: object(),
        report_loader=lambda **kwargs: rows,
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "tasks=0 active_tasks=0" in out
    assert "no-task-container" in out


def test_governance_report_cli_marks_decomposing_story(monkeypatch, capsys):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )

    rows = [
        {
            "epic_issue_number": 19,
            "epic_title": "[Epic][Wave 0] Freeze 基线锁定",
            "epic_execution_status": "active",
            "story_issue_number": 42,
            "story_title": "[Story][W0-A] 文档分析与知识蒸馏",
            "story_execution_status": "decomposing",
            "story_task_count": 0,
            "story_active_task_count": 0,
        }
    ]

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter"],
        repository_builder=lambda *, dsn: object(),
        report_loader=lambda **kwargs: rows,
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "awaiting-decomposition" in out


def test_load_report_rows_filters_by_report_repo():
    class FakeCursor:
        def __init__(self) -> None:
            self.sql = ""
            self.params = None

        def execute(self, sql, params) -> None:
            self.sql = sql
            self.params = params

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    class FakeConnection:
        def __init__(self) -> None:
            self.cursor_obj = FakeCursor()

        def cursor(self):
            return self.cursor_obj

    connection = FakeConnection()

    rows = _load_report_rows(connection=connection, repo="codefromkarl/stardrifter")

    assert rows == []
    assert "WHERE report.repo = %s" in connection.cursor_obj.sql
    assert connection.cursor_obj.params == ("codefromkarl/stardrifter",)
