from stardrifter_orchestration_mvp.governance_state_cli import main


def test_governance_state_cli_updates_epic_execution_status(monkeypatch, capsys):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    class FakeRepository:
        def set_program_epic_execution_status(self, *, repo: str, issue_number: int, execution_status: str) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter", "--kind", "epic", "--issue-number", "19", "--execution-status", "done"],
        repository_builder=lambda *, dsn: FakeRepository(),
    )

    assert exit_code == 0
    assert captured == {
        "repo": "codefromkarl/stardrifter",
        "issue_number": 19,
        "execution_status": "done",
    }
    assert "updated epic #19 -> done" in capsys.readouterr().out


def test_governance_state_cli_updates_story_execution_status(monkeypatch, capsys):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    class FakeRepository:
        def set_program_story_execution_status(self, *, repo: str, issue_number: int, execution_status: str) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter", "--kind", "story", "--issue-number", "42", "--execution-status", "blocked"],
        repository_builder=lambda *, dsn: FakeRepository(),
    )

    assert exit_code == 0
    assert captured == {
        "repo": "codefromkarl/stardrifter",
        "issue_number": 42,
        "execution_status": "blocked",
    }
    assert "updated story #42 -> blocked" in capsys.readouterr().out


def test_governance_state_cli_supports_epic_state_propagation(monkeypatch, capsys):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    class FakeRepository:
        def set_program_epic_execution_status_with_propagation(self, *, repo: str, issue_number: int, execution_status: str) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    exit_code = main(
        [
            "--repo", "codefromkarl/stardrifter",
            "--kind", "epic",
            "--issue-number", "13",
            "--execution-status", "active",
            "--propagate",
        ],
        repository_builder=lambda *, dsn: FakeRepository(),
    )

    assert exit_code == 0
    assert captured == {
        "repo": "codefromkarl/stardrifter",
        "issue_number": 13,
        "execution_status": "active",
    }
    assert "updated epic #13 -> active" in capsys.readouterr().out


def test_governance_state_cli_supports_story_state_propagation(monkeypatch, capsys):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    class FakeRepository:
        def set_program_story_execution_status_with_propagation(self, *, repo: str, issue_number: int, execution_status: str) -> None:
            captured["repo"] = repo
            captured["issue_number"] = issue_number
            captured["execution_status"] = execution_status

    exit_code = main(
        [
            "--repo", "codefromkarl/stardrifter",
            "--kind", "story",
            "--issue-number", "21",
            "--execution-status", "done",
            "--propagate",
        ],
        repository_builder=lambda *, dsn: FakeRepository(),
    )

    assert exit_code == 0
    assert captured == {
        "repo": "codefromkarl/stardrifter",
        "issue_number": 21,
        "execution_status": "done",
    }
    assert "updated story #21 -> done" in capsys.readouterr().out
