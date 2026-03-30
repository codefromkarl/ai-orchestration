from stardrifter_orchestration_mvp.governance_sync_cli import main
from stardrifter_orchestration_mvp.models import ProgramEpic, ProgramGovernanceProjection, ProgramStory


def test_governance_sync_cli_loads_issues_and_persists_projection(monkeypatch, capsys):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_repository_builder(*, dsn: str):
        captured["dsn"] = dsn
        return {"connection": "ok"}

    def fake_issues_loader(*, connection, repo: str):
        captured["connection"] = connection
        captured["repo"] = repo
        return ["issues"]

    def fake_projection_builder(*, repo: str, issues):
        captured["projection_repo"] = repo
        captured["issues"] = issues
        return ProgramGovernanceProjection(
            epics=[
                ProgramEpic(
                    issue_number=19,
                    repo=repo,
                    title="[Epic][Wave 0] Freeze 基线锁定",
                    lane="lane:01",
                    program_status="approved",
                    execution_status="active",
                )
            ],
            stories=[
                ProgramStory(
                    issue_number=42,
                    repo=repo,
                    epic_issue_number=19,
                    title="[Story][W0-A] 文档分析与知识蒸馏",
                    lane="lane:01",
                    complexity=None,
                    program_status="approved",
                    execution_status="active",
                )
            ],
        )

    def fake_syncer(*, connection, repo: str, projection):
        captured["sync_repo"] = repo
        captured["projection"] = projection

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter"],
        repository_builder=fake_repository_builder,
        issues_loader=fake_issues_loader,
        projection_builder=fake_projection_builder,
        syncer=fake_syncer,
    )

    assert exit_code == 0
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/stardrifter"
    assert captured["repo"] == "codefromkarl/stardrifter"
    assert captured["sync_repo"] == "codefromkarl/stardrifter"
    assert len(captured["projection"].epics) == 1
    assert "synced 1 epics and 1 stories" in capsys.readouterr().out
