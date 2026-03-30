from datetime import datetime, timezone

from stardrifter_orchestration_mvp.models import (
    EpicExecutionState,
    OperatorRequest,
    ProgramStory,
)
from stardrifter_orchestration_mvp.operator_request_ack_cli import main


def test_operator_request_ack_cli_closes_operator_request(monkeypatch, capsys):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_repository_builder(*, dsn: str):
        captured["dsn"] = dsn

        class FakeRepository:
            stored_state = EpicExecutionState(
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                status="awaiting_operator",
                completed_story_issue_numbers=(),
                blocked_story_issue_numbers=(),
                remaining_story_issue_numbers=(),
                blocked_reason_code="progress_timeout",
                operator_attention_required=True,
            )

            def close_operator_request(
                self,
                *,
                repo: str,
                epic_issue_number: int,
                reason_code: str,
                closed_reason: str,
            ) -> OperatorRequest | None:
                captured["repo"] = repo
                captured["epic_issue_number"] = epic_issue_number
                captured["reason_code"] = reason_code
                captured["closed_reason"] = closed_reason
                return OperatorRequest(
                    repo=repo,
                    epic_issue_number=epic_issue_number,
                    reason_code=reason_code,
                    summary="Epic #13 was acknowledged by an operator.",
                    remaining_story_issue_numbers=(43,),
                    blocked_story_issue_numbers=(),
                    status="closed",
                    opened_at=datetime(2026, 3, 1, 14, 30, tzinfo=timezone.utc),
                    closed_at=datetime(2026, 3, 1, 15, 45, tzinfo=timezone.utc),
                    closed_reason=closed_reason,
                )

            def get_epic_execution_state(
                self, *, repo: str, epic_issue_number: int
            ) -> EpicExecutionState | None:
                return self.stored_state

            def list_program_stories_for_epic(
                self, *, repo: str, epic_issue_number: int
            ) -> list[ProgramStory]:
                return []

            def list_operator_requests(
                self,
                *,
                repo: str,
                epic_issue_number: int | None = None,
                include_closed: bool = False,
            ) -> list[OperatorRequest]:
                return []

            def upsert_epic_execution_state(self, state: EpicExecutionState) -> None:
                self.stored_state = state

        return FakeRepository()

    exit_code = main(
        [
            "--repo",
            "codefromkarl/stardrifter",
            "--epic-issue-number",
            "13",
            "--reason-code",
            "progress_timeout",
            "--closed-reason",
            "acknowledged",
        ],
        repository_builder=fake_repository_builder,
    )

    assert exit_code == 0
    assert captured == {
        "dsn": "postgresql://user:pass@localhost:5432/stardrifter",
        "repo": "codefromkarl/stardrifter",
        "epic_issue_number": 13,
        "reason_code": "progress_timeout",
        "closed_reason": "acknowledged",
    }
    assert capsys.readouterr().out == (
        "closed operator request epic=13 reason=progress_timeout status=closed closed_reason=acknowledged\n"
        "mode=apply epic=13 status=awaiting_operator operator_attention=false open_requests=0 continue_ready=false\n"
    )


def test_operator_request_ack_cli_returns_not_found_when_request_is_missing(
    monkeypatch, capsys
):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )

    def fake_repository_builder(*, dsn: str):
        class FakeRepository:
            def close_operator_request(
                self,
                *,
                repo: str,
                epic_issue_number: int,
                reason_code: str,
                closed_reason: str,
            ) -> OperatorRequest | None:
                return None

        return FakeRepository()

    exit_code = main(
        [
            "--repo",
            "codefromkarl/stardrifter",
            "--epic-issue-number",
            "13",
            "--reason-code",
            "progress_timeout",
            "--closed-reason",
            "acknowledged",
        ],
        repository_builder=fake_repository_builder,
    )

    assert exit_code == 1
    assert capsys.readouterr().out == (
        "operator request not found for epic=13 reason=progress_timeout\n"
    )


def test_operator_request_ack_cli_refreshes_epic_runtime_after_closing_last_open_request(
    monkeypatch, capsys
):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    progress_at = datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc)
    stalled_since = datetime(2026, 3, 1, 13, 30, tzinfo=timezone.utc)

    def fake_repository_builder(*, dsn: str):
        assert dsn == "postgresql://user:pass@localhost:5432/stardrifter"

        class FakeRepository:
            def __init__(self) -> None:
                self.closed_requests: list[tuple[str, int, str, str]] = []
                self.stored_state = EpicExecutionState(
                    repo="codefromkarl/stardrifter",
                    epic_issue_number=13,
                    status="awaiting_operator",
                    completed_story_issue_numbers=(41,),
                    blocked_story_issue_numbers=(42,),
                    remaining_story_issue_numbers=(),
                    blocked_reason_code="all_remaining_stories_blocked",
                    operator_attention_required=True,
                    last_progress_at=progress_at,
                    stalled_since=stalled_since,
                )

            def close_operator_request(
                self,
                *,
                repo: str,
                epic_issue_number: int,
                reason_code: str,
                closed_reason: str,
            ) -> OperatorRequest | None:
                self.closed_requests.append(
                    (repo, epic_issue_number, reason_code, closed_reason)
                )
                return OperatorRequest(
                    repo=repo,
                    epic_issue_number=epic_issue_number,
                    reason_code=reason_code,
                    summary="Epic #13 was acknowledged by an operator.",
                    remaining_story_issue_numbers=(),
                    blocked_story_issue_numbers=(42,),
                    status="closed",
                    opened_at=datetime(2026, 3, 1, 14, 30, tzinfo=timezone.utc),
                    closed_at=datetime(2026, 3, 1, 15, 45, tzinfo=timezone.utc),
                    closed_reason=closed_reason,
                )

            def get_epic_execution_state(
                self, *, repo: str, epic_issue_number: int
            ) -> EpicExecutionState | None:
                assert repo == "codefromkarl/stardrifter"
                assert epic_issue_number == 13
                return self.stored_state

            def list_program_stories_for_epic(
                self, *, repo: str, epic_issue_number: int
            ) -> list[ProgramStory]:
                assert repo == "codefromkarl/stardrifter"
                assert epic_issue_number == 13
                return [
                    ProgramStory(
                        issue_number=41,
                        repo=repo,
                        epic_issue_number=epic_issue_number,
                        title="Story 41",
                        lane="Lane 01",
                        complexity="medium",
                        program_status="approved",
                        execution_status="done",
                    ),
                    ProgramStory(
                        issue_number=42,
                        repo=repo,
                        epic_issue_number=epic_issue_number,
                        title="Story 42",
                        lane="Lane 01",
                        complexity="medium",
                        program_status="approved",
                        execution_status="planned",
                    ),
                ]

            def list_operator_requests(
                self,
                *,
                repo: str,
                epic_issue_number: int | None = None,
                include_closed: bool = False,
            ) -> list[OperatorRequest]:
                assert repo == "codefromkarl/stardrifter"
                assert epic_issue_number == 13
                assert include_closed is False
                return []

            def upsert_epic_execution_state(self, state: EpicExecutionState) -> None:
                self.stored_state = state

        return FakeRepository()

    exit_code = main(
        [
            "--repo",
            "codefromkarl/stardrifter",
            "--epic-issue-number",
            "13",
            "--reason-code",
            "all_remaining_stories_blocked",
            "--closed-reason",
            "resolved_in_governance",
        ],
        repository_builder=fake_repository_builder,
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().splitlines() == [
        "closed operator request epic=13 reason=all_remaining_stories_blocked status=closed closed_reason=resolved_in_governance",
        "mode=apply epic=13 status=awaiting_operator operator_attention=false open_requests=0 continue_ready=true",
    ]
