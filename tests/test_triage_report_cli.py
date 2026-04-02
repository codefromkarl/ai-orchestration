from taskplane.models import CompletionAudit, GitHubTaskProjection, WorkItem
from taskplane.triage_report import TriageReport
from taskplane.triage_report_cli import main


def test_triage_report_cli_prints_summary(monkeypatch, capsys):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )

    def fake_repository_builder(*, dsn: str):
        return object()

    def fake_loader(*, connection, repo: str):
        return {
            "issues": [],
            "relations": [],
            "completion_audit": {},
            "projection": GitHubTaskProjection(
                work_items=[],
                story_task_ids={},
                needs_triage_issue_numbers=[60],
            ),
        }

    def fake_report_builder(*, issues, relations, completion_audit, projection):
        return TriageReport(
            unprojected_task_issue_numbers=[60],
            storys_without_projected_tasks=[29],
            anomalies_by_issue={60: ["missing-lane", "missing-parent-reference"]},
        )

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter"],
        repository_builder=fake_repository_builder,
        staging_loader=fake_loader,
        report_builder=fake_report_builder,
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "unprojected_tasks=1" in output
    assert "stories_without_projected_tasks=1" in output
