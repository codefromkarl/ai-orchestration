from taskplane.import_cli import main as import_main
from taskplane.models import GitHubTaskProjection, WorkItem
from taskplane.projection_sync_cli import main


def test_projection_sync_cli_loads_repo_and_syncs_projection(monkeypatch, capsys):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_repository_builder(*, dsn: str):
        captured["dsn"] = dsn
        return {"connection": "ok"}

    def fake_loader(*, connection, repo: str):
        captured["connection"] = connection
        captured["repo"] = repo
        return GitHubTaskProjection(
            work_items=[
                WorkItem(
                    id="issue-56",
                    title="task 56",
                    lane="Lane 03",
                    wave="unassigned",
                    status="done",
                    source_issue_number=56,
                    story_issue_numbers=(29,),
                )
            ],
            story_task_ids={29: ["issue-56"]},
            needs_triage_issue_numbers=[60],
        )

    def fake_syncer(*, connection, repo: str, projection):
        captured["sync_repo"] = repo
        captured["projection"] = projection

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter"],
        repository_builder=fake_repository_builder,
        projection_loader=fake_loader,
        syncer=fake_syncer,
    )

    assert exit_code == 0
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/stardrifter"
    assert captured["repo"] == "codefromkarl/stardrifter"
    assert captured["sync_repo"] == "codefromkarl/stardrifter"
    assert captured["projection"].needs_triage_issue_numbers == [60]
    assert "synced 1 work items" in capsys.readouterr().out
