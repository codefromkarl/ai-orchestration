from stardrifter_orchestration_mvp.models import OperatorRequest
from stardrifter_orchestration_mvp.operator_request_cli import main


def test_operator_request_cli_lists_open_requests_for_repo(monkeypatch, capsys):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_repository_builder(*, dsn: str):
        captured["dsn"] = dsn

        class FakeRepository:
            def list_operator_requests(
                self,
                *,
                repo: str,
                epic_issue_number: int | None = None,
                include_closed: bool = False,
            ) -> list[OperatorRequest]:
                captured["repo"] = repo
                captured["epic_issue_number"] = epic_issue_number
                captured["include_closed"] = include_closed
                return [
                    OperatorRequest(
                        repo=repo,
                        epic_issue_number=13,
                        reason_code="progress_timeout",
                        summary="Epic #13 needs operator attention.",
                        remaining_story_issue_numbers=(43, 44),
                        blocked_story_issue_numbers=(41,),
                        status="open",
                    ),
                    OperatorRequest(
                        repo=repo,
                        epic_issue_number=21,
                        reason_code="all_remaining_stories_blocked",
                        summary="Epic #21 is fully blocked pending operator action.",
                        remaining_story_issue_numbers=(72,),
                        blocked_story_issue_numbers=(70, 71),
                        status="open",
                    ),
                ]

        return FakeRepository()

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter"],
        repository_builder=fake_repository_builder,
    )

    assert exit_code == 0
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/stardrifter"
    assert captured["repo"] == "codefromkarl/stardrifter"
    assert captured["epic_issue_number"] is None
    assert captured["include_closed"] is False
    assert capsys.readouterr().out == (
        "epic=13 reason=progress_timeout remaining=2 blocked=1 status=open summary=Epic #13 needs operator attention.\n"
        "epic=21 reason=all_remaining_stories_blocked remaining=1 blocked=2 status=open summary=Epic #21 is fully blocked pending operator action.\n"
    )


def test_operator_request_cli_prints_empty_state_when_no_open_requests(
    monkeypatch, capsys
):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_repository_builder(*, dsn: str):
        captured["dsn"] = dsn

        class FakeRepository:
            def list_operator_requests(
                self,
                *,
                repo: str,
                epic_issue_number: int | None = None,
                include_closed: bool = False,
            ) -> list[OperatorRequest]:
                captured["repo"] = repo
                captured["epic_issue_number"] = epic_issue_number
                captured["include_closed"] = include_closed
                return []

        return FakeRepository()

    exit_code = main(
        [
            "--repo",
            "codefromkarl/stardrifter",
            "--epic-issue-number",
            "13",
        ],
        repository_builder=fake_repository_builder,
    )

    assert exit_code == 0
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/stardrifter"
    assert captured["repo"] == "codefromkarl/stardrifter"
    assert captured["epic_issue_number"] == 13
    assert captured["include_closed"] is False
    assert capsys.readouterr().out == "no open operator requests\n"


def test_operator_request_cli_can_include_closed_requests(monkeypatch, capsys):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_repository_builder(*, dsn: str):
        captured["dsn"] = dsn

        class FakeRepository:
            def list_operator_requests(
                self,
                *,
                repo: str,
                epic_issue_number: int | None = None,
                include_closed: bool = False,
            ) -> list[OperatorRequest]:
                captured["repo"] = repo
                captured["epic_issue_number"] = epic_issue_number
                captured["include_closed"] = include_closed
                return [
                    OperatorRequest(
                        repo=repo,
                        epic_issue_number=13,
                        reason_code="progress_timeout",
                        summary="Epic #13 needs operator attention.",
                        remaining_story_issue_numbers=(43, 44),
                        blocked_story_issue_numbers=(41,),
                        status="open",
                    ),
                    OperatorRequest(
                        repo=repo,
                        epic_issue_number=13,
                        reason_code="progress_timeout",
                        summary="Epic #13 was acknowledged by an operator.",
                        remaining_story_issue_numbers=(43, 44),
                        blocked_story_issue_numbers=(41,),
                        status="closed",
                        closed_reason="acknowledged",
                    ),
                ]

        return FakeRepository()

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter", "--include-closed"],
        repository_builder=fake_repository_builder,
    )

    assert exit_code == 0
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/stardrifter"
    assert captured["repo"] == "codefromkarl/stardrifter"
    assert captured["epic_issue_number"] is None
    assert captured["include_closed"] is True
    assert capsys.readouterr().out == (
        "epic=13 reason=progress_timeout remaining=2 blocked=1 status=open summary=Epic #13 needs operator attention.\n"
        "epic=13 reason=progress_timeout remaining=2 blocked=1 status=closed summary=Epic #13 was acknowledged by an operator.\n"
    )
