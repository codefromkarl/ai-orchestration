from taskplane.attempt_report_cli import main

import json


def test_attempt_report_cli_prints_summary(monkeypatch, capsys):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
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


def test_attempt_report_cli_can_emit_json_summary(monkeypatch, capsys):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
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
            }
        ]

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter", "--format", "json"],
        repository_builder=fake_repository_builder,
        row_loader=fake_loader,
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "v1"
    assert payload["kind"] == "attempt_report"
    assert payload["repo"] == "codefromkarl/stardrifter"
    assert payload["summary"]["done_runs"] == 1
    assert payload["taxonomy"] == {
        "success": 1,
        "operator_blocked": 0,
        "protocol_failures": 0,
        "payload_failures": 0,
        "infra_failures": 0,
    }


def test_attempt_report_cli_can_emit_grouping_context(monkeypatch, capsys):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
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
            }
        ]

    exit_code = main(
        [
            "--repo",
            "codefromkarl/stardrifter",
            "--format",
            "json",
            "--suite",
            "smoke-core",
            "--scenario",
            "retry-then-success",
        ],
        repository_builder=fake_repository_builder,
        row_loader=fake_loader,
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["context"] == {
        "suite": "smoke-core",
        "scenario": "retry-then-success",
    }


def test_attempt_report_cli_text_output_includes_grouping_context(monkeypatch, capsys):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
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
            }
        ]

    exit_code = main(
        [
            "--repo",
            "codefromkarl/stardrifter",
            "--suite",
            "smoke-core",
            "--scenario",
            "retry-then-success",
        ],
        repository_builder=fake_repository_builder,
        row_loader=fake_loader,
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "suite=smoke-core" in output
    assert "scenario=retry-then-success" in output


def test_attempt_report_cli_text_output_includes_taxonomy(monkeypatch, capsys):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
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
                "result_payload_json": {"reason_code": "protocol_error"},
            },
        ]

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter"],
        repository_builder=fake_repository_builder,
        row_loader=fake_loader,
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "taxonomy.success=1" in output
    assert "taxonomy.operator_blocked=1" in output
    assert "taxonomy.protocol_failures=1" in output
