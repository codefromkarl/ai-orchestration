from __future__ import annotations

from pathlib import Path


def test_workflow_link_registers_repo_and_updates_taskplane_toml(tmp_path, monkeypatch):
    from taskplane.workflow_cli import main

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    config_path = tmp_path / "taskplane.toml"
    config_path.write_text(
        """
[postgres]
dsn = "postgresql://user:pass@localhost:5432/taskplane"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(repo_dir)
    monkeypatch.setenv("TASKPLANE_CONFIG", str(config_path))

    registered: dict[str, object] = {}

    def fake_repo_locator(cwd: Path) -> str:
        assert cwd == repo_dir
        return "owner/repo"

    def fake_connector(dsn: str):
        assert dsn == "postgresql://user:pass@localhost:5432/taskplane"
        registered["dsn"] = dsn
        return object()

    def fake_register_repo(
        connection, *, repo: str, workdir: Path, log_dir: Path
    ) -> bool:
        registered["repo"] = repo
        registered["workdir"] = workdir
        registered["log_dir"] = log_dir
        return True

    exit_code = main(
        ["link"],
        repo_locator=fake_repo_locator,
        connector=fake_connector,
        register_repo=fake_register_repo,
    )

    assert exit_code == 0
    assert registered["repo"] == "owner/repo"
    assert registered["workdir"] == repo_dir.resolve()
    assert registered["log_dir"] == (repo_dir / ".taskplane" / "logs").resolve()

    config_text = config_path.read_text(encoding="utf-8")
    assert '"owner/repo" = "' in config_text
    assert str(repo_dir.resolve()) in config_text
    assert str((repo_dir / ".taskplane" / "logs").resolve()) in config_text


def test_workflow_intake_routes_review_actions_and_answers(monkeypatch, capsys):
    from taskplane.workflow_cli import main

    calls: list[tuple[str, dict[str, str]]] = []

    def fake_repo_locator(cwd: Path) -> str:
        return "owner/repo"

    class FakeIntent:
        def __init__(self, *, status: str, questions: tuple[str, ...] = ()) -> None:
            self.id = "intent-1"
            self.repo = "owner/repo"
            self.status = status
            self.summary = "summary"
            self.clarification_questions = questions
            self.proposal_json = {"epic": {}, "stories": []}
            self.promoted_epic_issue_number = None
            self.approved_by = None
            self.reviewed_by = None
            self.review_action = None
            self.review_feedback = None

    class FakeService:
        def submit_intent(self, *, repo: str, prompt: str):
            calls.append(("submit", {"repo": repo, "prompt": prompt}))
            return FakeIntent(status="awaiting_clarification", questions=("Q1",))

        def answer_intent(self, *, intent_id: str, answer: str):
            calls.append(("answer", {"intent_id": intent_id, "answer": answer}))
            return FakeIntent(status="awaiting_review")

        def approve_intent(self, *, intent_id: str, approver: str):
            calls.append(("approve", {"intent_id": intent_id, "approver": approver}))
            return FakeIntent(status="promoted")

        def reject_intent(self, *, intent_id: str, reviewer: str, reason: str):
            calls.append(
                (
                    "reject",
                    {"intent_id": intent_id, "reviewer": reviewer, "reason": reason},
                )
            )
            return FakeIntent(status="rejected")

        def revise_intent(self, *, intent_id: str, reviewer: str, feedback: str):
            calls.append(
                (
                    "revise",
                    {
                        "intent_id": intent_id,
                        "reviewer": reviewer,
                        "feedback": feedback,
                    },
                )
            )
            return FakeIntent(status="awaiting_clarification", questions=("Q2",))

    service = FakeService()

    assert (
        main(
            ["intake", "Build auth flow"],
            intake_service_builder=lambda: service,
            repo_locator=fake_repo_locator,
        )
        == 0
    )
    assert (
        main(
            ["intake", "--intent", "intent-1", "--answer", "Use JWT"],
            intake_service_builder=lambda: service,
        )
        == 0
    )
    assert (
        main(
            ["intake", "--intent", "intent-1", "--approve"],
            intake_service_builder=lambda: service,
        )
        == 0
    )
    assert (
        main(
            ["intake", "--intent", "intent-1", "--reject", "Too broad"],
            intake_service_builder=lambda: service,
        )
        == 0
    )
    assert (
        main(
            ["intake", "--intent", "intent-1", "--revise", "Clarify MVP"],
            intake_service_builder=lambda: service,
        )
        == 0
    )

    assert calls == [
        ("submit", {"repo": "owner/repo", "prompt": "Build auth flow"}),
        ("answer", {"intent_id": "intent-1", "answer": "Use JWT"}),
        ("approve", {"intent_id": "intent-1", "approver": "operator"}),
        (
            "reject",
            {"intent_id": "intent-1", "reviewer": "operator", "reason": "Too broad"},
        ),
        (
            "revise",
            {
                "intent_id": "intent-1",
                "reviewer": "operator",
                "feedback": "Clarify MVP",
            },
        ),
    ]

    output = capsys.readouterr().out
    assert "需要你确认 / 补充" in output
    assert '/tp-intake intent=intent-1 answer="..."' in output


def test_workflow_status_summarizes_running_blocked_and_human_actions(capsys):
    from taskplane.workflow_cli import main

    exit_code = main(
        ["status", "--repo", "owner/repo"],
        status_loader=lambda repo: {
            "repo": repo,
            "summary": {
                "task_count": 5,
                "in_progress_task_count": 1,
                "blocked_task_count": 2,
                "running_job_count": 1,
            },
            "task_status_counts": [
                {"status": "pending", "count": 2},
                {"status": "in_progress", "count": 1},
                {"status": "blocked", "count": 2},
            ],
            "jobs": [
                {
                    "id": 7,
                    "job_kind": "story_runner",
                    "status": "running",
                    "story_issue_number": 123,
                    "work_id": None,
                    "worker_name": "story-runner",
                }
            ],
            "intents": [
                {
                    "id": "intent-1",
                    "status": "awaiting_clarification",
                    "summary": "Need scope",
                    "clarification_questions_json": ["Web only?"],
                },
                {
                    "id": "intent-2",
                    "status": "awaiting_review",
                    "summary": "Ready for review",
                    "clarification_questions_json": [],
                },
            ],
            "blocked_tasks": [
                {
                    "id": "task-1",
                    "title": "Blocked by dependency",
                    "blocked_reason": "dependency:task-0",
                    "decision_required": False,
                },
                {
                    "id": "task-2",
                    "title": "Needs human decision",
                    "blocked_reason": "waiting_operator",
                    "decision_required": True,
                },
            ],
            "operator_requests": [
                {
                    "epic_issue_number": 42,
                    "reason_code": "progress_timeout",
                    "summary": "Epic needs operator attention",
                }
            ],
        },
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Taskplane 状态: owner/repo" in output
    assert "running jobs: 1" in output
    assert "blocked tasks: 2" in output
    assert "intent-1" in output
    assert '/tp-intake intent=intent-1 answer="..."' in output
    assert "/tp-intake intent=intent-2 approve" in output
    assert "/tp-intake request=epic:42:progress_timeout approve" in output
