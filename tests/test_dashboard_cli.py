from stardrifter_orchestration_mvp.models import EpicExecutionState, OperatorRequest
from stardrifter_orchestration_mvp.dashboard_cli import _state_from_rows, main


def test_dashboard_cli_prints_repo_summary_operator_summary_and_epic_runtime_rows(
    monkeypatch, capsys
):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}
    epic_state_calls: list[tuple[str, int]] = []

    def fake_repository_builder(*, dsn: str):
        captured["dsn"] = dsn

        class FakeRepository:
            _connection = object()

            def list_operator_requests(
                self,
                *,
                repo: str,
                epic_issue_number: int | None = None,
                include_closed: bool = False,
            ) -> list[OperatorRequest]:
                captured["operator_repo"] = repo
                captured["operator_epic_issue_number"] = epic_issue_number
                captured["operator_include_closed"] = include_closed
                return [
                    OperatorRequest(
                        repo=repo,
                        epic_issue_number=21,
                        reason_code="progress_timeout",
                        summary="Epic #21 needs operator attention.",
                        status="open",
                    ),
                    OperatorRequest(
                        repo=repo,
                        epic_issue_number=21,
                        reason_code="progress_timeout",
                        summary="Epic #21 still needs operator attention.",
                        status="open",
                    ),
                    OperatorRequest(
                        repo=repo,
                        epic_issue_number=13,
                        reason_code="all_remaining_stories_blocked",
                        summary="Epic #13 is fully blocked.",
                        status="open",
                    ),
                ]

            def get_epic_execution_state(
                self, *, repo: str, epic_issue_number: int
            ) -> EpicExecutionState | None:
                epic_state_calls.append((repo, epic_issue_number))
                states = {
                    13: EpicExecutionState(
                        repo=repo,
                        epic_issue_number=13,
                        status="awaiting_operator",
                        operator_attention_required=True,
                        blocked_story_issue_numbers=(1301,),
                        remaining_story_issue_numbers=(1302, 1303),
                    ),
                    21: EpicExecutionState(
                        repo=repo,
                        epic_issue_number=21,
                        status="active",
                        operator_attention_required=True,
                        remaining_story_issue_numbers=(2101, 2102),
                    ),
                }
                return states.get(epic_issue_number)

        return FakeRepository()

    def fake_report_loader(*, connection, repo: str):
        captured["report_connection"] = connection
        captured["report_repo"] = repo
        return [
            {
                "epic_issue_number": 21,
                "epic_title": "Epic Twenty One",
                "epic_execution_status": "active",
                "story_issue_number": 2101,
                "story_title": "Story A",
                "story_execution_status": "active",
            },
            {
                "epic_issue_number": 13,
                "epic_title": "Epic Thirteen",
                "epic_execution_status": "blocked",
                "story_issue_number": 1301,
                "story_title": "Story B",
                "story_execution_status": "blocked",
            },
            {
                "epic_issue_number": 21,
                "epic_title": "Epic Twenty One",
                "epic_execution_status": "active",
                "story_issue_number": 2102,
                "story_title": "Story C",
                "story_execution_status": "planned",
            },
        ]

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter"],
        repository_builder=fake_repository_builder,
        report_loader=fake_report_loader,
    )

    assert exit_code == 0
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/stardrifter"
    assert captured["report_repo"] == "codefromkarl/stardrifter"
    assert captured["operator_repo"] == "codefromkarl/stardrifter"
    assert captured["operator_epic_issue_number"] is None
    assert captured["operator_include_closed"] is False
    assert epic_state_calls == [
        ("codefromkarl/stardrifter", 13),
        ("codefromkarl/stardrifter", 21),
    ]
    assert capsys.readouterr().out == (
        "repo=codefromkarl/stardrifter active_epics=1 rows=3 open_operator_requests=3\n"
        "operator_reason=all_remaining_stories_blocked requests=1 epics=1\n"
        "operator_reason=progress_timeout requests=2 epics=1\n"
        "epic=13 runtime_status=awaiting_operator operator_attention=true open_requests=1\n"
        "epic=21 runtime_status=active operator_attention=true open_requests=2\n"
    )


def test_dashboard_cli_prints_only_zero_summary_when_no_data(monkeypatch, capsys):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_repository_builder(*, dsn: str):
        captured["dsn"] = dsn

        class FakeRepository:
            _connection = object()

            def list_operator_requests(
                self,
                *,
                repo: str,
                epic_issue_number: int | None = None,
                include_closed: bool = False,
            ) -> list[OperatorRequest]:
                captured["operator_repo"] = repo
                captured["operator_epic_issue_number"] = epic_issue_number
                captured["operator_include_closed"] = include_closed
                return []

            def get_epic_execution_state(
                self, *, repo: str, epic_issue_number: int
            ) -> EpicExecutionState | None:
                raise AssertionError("no epic state lookup expected when no rows exist")

        return FakeRepository()

    def fake_report_loader(*, connection, repo: str):
        captured["report_connection"] = connection
        captured["report_repo"] = repo
        return []

    exit_code = main(
        ["--repo", "codefromkarl/stardrifter"],
        repository_builder=fake_repository_builder,
        report_loader=fake_report_loader,
    )

    assert exit_code == 0
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/stardrifter"
    assert captured["report_repo"] == "codefromkarl/stardrifter"
    assert captured["operator_repo"] == "codefromkarl/stardrifter"
    assert captured["operator_epic_issue_number"] is None
    assert captured["operator_include_closed"] is False
    assert capsys.readouterr().out == (
        "repo=codefromkarl/stardrifter active_epics=0 rows=0 open_operator_requests=0\n"
    )


def test_state_from_rows_falls_back_to_backlog_for_non_runtime_governance_status():
    state = _state_from_rows(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        rows=[
            {
                "epic_issue_number": 13,
                "epic_execution_status": "blocked",
            }
        ],
    )

    assert state == EpicExecutionState(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        status="backlog",
        operator_attention_required=False,
    )
