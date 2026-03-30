from stardrifter_orchestration_mvp.attempt_report_cli import main


def test_attempt_report_cli_prints_summary(monkeypatch, capsys):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )

    def fake_repository_builder(*, dsn: str):
        return object()

    def fake_loader(*, connection, repo: str):
        return [
            {
                "work_id": "task-1",
                "status": "done",
                "result_payload_json": {"outcome": "done"},
            },
            {
                "work_id": "task-2",
                "status": "blocked",
                "result_payload_json": {"outcome": "needs_decision"},
            },
            {
                "work_id": "task-3",
                "status": "blocked",
                "result_payload_json": {"reason_code": "timeout"},
            },
        ]

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter"],
        repository_builder=fake_repository_builder,
        row_loader=fake_loader,
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "repo=codefromkarl/stardrifter total_runs=3" in output
    assert "done_runs=1" in output
    assert "needs_decision_runs=1" in output
    assert "timeout_runs=1" in output
    assert "first_attempt_success_runs=1" in output
    assert "eventual_success_runs=1" in output
