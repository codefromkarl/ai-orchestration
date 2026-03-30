from datetime import datetime, timezone

from stardrifter_orchestration_mvp.models import OperatorRequest
from stardrifter_orchestration_mvp.operator_request_report_cli import main


def test_operator_request_report_cli_groups_open_requests_by_reason(monkeypatch, capsys):
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
                        epic_issue_number=21,
                        reason_code="progress_timeout",
                        summary="Epic #21 needs operator attention.",
                        status="open",
                        opened_at=datetime(2026, 3, 24, 10, 30, tzinfo=timezone.utc),
                    ),
                    OperatorRequest(
                        repo=repo,
                        epic_issue_number=13,
                        reason_code="all_remaining_stories_blocked",
                        summary="Epic #13 is fully blocked.",
                        status="open",
                        opened_at=datetime(2026, 3, 23, 8, 0, tzinfo=timezone.utc),
                    ),
                    OperatorRequest(
                        repo=repo,
                        epic_issue_number=22,
                        reason_code="progress_timeout",
                        summary="Epic #22 has timed out.",
                        status="open",
                        opened_at=None,
                    ),
                    OperatorRequest(
                        repo=repo,
                        epic_issue_number=21,
                        reason_code="progress_timeout",
                        summary="Epic #21 still needs operator attention.",
                        status="open",
                        opened_at=datetime(2026, 3, 25, 9, 15, tzinfo=timezone.utc),
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
        "reason=all_remaining_stories_blocked requests=1 epics=1 oldest_epic=13 oldest_opened_at=2026-03-23T08:00:00+00:00\n"
        "reason=progress_timeout requests=3 epics=2 oldest_epic=21 oldest_opened_at=2026-03-24T10:30:00+00:00\n"
    )


def test_operator_request_report_cli_prints_empty_state(monkeypatch, capsys):
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
        ["--repo", "codefromkarl/stardrifter"],
        repository_builder=fake_repository_builder,
    )

    assert exit_code == 0
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/stardrifter"
    assert captured["repo"] == "codefromkarl/stardrifter"
    assert captured["epic_issue_number"] is None
    assert captured["include_closed"] is False
    assert capsys.readouterr().out == "no open operator requests\n"
