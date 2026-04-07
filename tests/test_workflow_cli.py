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


def test_workflow_link_writes_repo_default_executor_when_configured(
    tmp_path, monkeypatch
):
    from taskplane.workflow_cli import main
    from taskplane.settings import TaskplaneConfig

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

    def fake_repo_locator(cwd: Path) -> str:
        assert cwd == repo_dir
        return "owner/repo"

    def fake_connector(dsn: str):
        assert dsn == "postgresql://user:pass@localhost:5432/taskplane"
        return object()

    exit_code = main(
        ["link"],
        config_loader=lambda: TaskplaneConfig(
            source_path=config_path,
            postgres_dsn="postgresql://user:pass@localhost:5432/taskplane",
            workflow_repo_default_executor={"owner/repo": "opencode"},
        ),
        repo_locator=fake_repo_locator,
        connector=fake_connector,
        register_repo=lambda *args, **kwargs: True,
    )

    assert exit_code == 0
    config_text = config_path.read_text(encoding="utf-8")
    assert "[workflow.repo_default_executor]" in config_text
    assert '"owner/repo" = "opencode"' in config_text


def test_workflow_start_uses_orchestrator_service(monkeypatch, capsys):
    from taskplane.workflow_cli import main
    from taskplane.settings import TaskplaneConfig

    captured: dict[str, object] = {}

    class SessionStub:
        id = "orch-1"
        repo = "owner/repo"
        host_tool = "claude_code"

    def fake_start(**kwargs):
        captured.update(kwargs)
        return type(
            "StartResult",
            (),
            {
                "session": SessionStub(),
                "launched_jobs": [{"id": 11, "job_kind": "story_worker"}],
                "watched_story_issue_numbers": [123],
            },
        )()

    exit_code = main(
        ["start", "--repo", "owner/repo", "--host-tool", "claude_code"],
        config_loader=lambda: TaskplaneConfig(
            postgres_dsn="postgresql://user:pass@localhost:5432/taskplane"
        ),
        repository_builder=lambda **kwargs: object(),
        orchestrator_start=fake_start,
    )

    assert exit_code == 0
    assert captured["repo"] == "owner/repo"
    assert captured["host_tool"] == "claude_code"
    assert "orch-1" in capsys.readouterr().out


def test_workflow_watch_uses_orchestrator_service(capsys):
    from taskplane.workflow_cli import main
    from taskplane.settings import TaskplaneConfig

    class SessionStub:
        id = "orch-1"
        repo = "owner/repo"
        host_tool = "claude_code"

    exit_code = main(
        ["watch", "--session", "orch-1"],
        config_loader=lambda: TaskplaneConfig(
            postgres_dsn="postgresql://user:pass@localhost:5432/taskplane"
        ),
        repository_builder=lambda **kwargs: object(),
        orchestrator_watch=lambda **kwargs: {
            "session": SessionStub(),
            "current_phase": "verify",
            "canonical_loop": [
                "observe",
                "plan",
                "act",
                "verify",
                "decide_next",
            ],
            "compact_summary": {
                "objective_summary": "Advance repo owner/repo through orchestrator session",
                "plan_summary": "Validate current story execution and pending operator work before deciding the next action.",
                "handoff_summary": "1 blocked task(s), 1 pending intent(s), 1 running job(s).",
            },
            "decision_state": {
                "decision": "verify",
                "reason": "running jobs need verification before the next transition",
                "requires_operator": False,
                "current_phase": "verify",
            },
            "jobs": [{"id": 11, "status": "running", "job_kind": "story_worker"}],
            "blocked_tasks": [
                type(
                    "BlockedTask",
                    (),
                    {
                        "id": "task-1",
                        "title": "Needs operator decision",
                        "blocked_reason": "waiting_operator",
                        "decision_required": True,
                    },
                )()
            ],
            "operator_requests": [
                type(
                    "OpenRequest",
                    (),
                    {"epic_issue_number": 42, "reason_code": "progress_timeout"},
                )()
            ],
            "intents": [
                type(
                    "OpenIntent",
                    (),
                    {
                        "id": "intent-1",
                        "status": "awaiting_clarification",
                        "summary": "Need scope",
                    },
                )()
            ],
            "recommended_actions": [
                '/tp-handle --session orch-1 --intent intent-1 --answer "..."'
            ],
        },
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "orch-1" in output
    assert "story_worker" in output
    assert "progress_timeout" in output
    assert "intent-1" in output
    assert "task-1" in output
    assert "current phase: verify" in output
    assert "canonical loop: observe -> plan -> act -> verify -> decide_next" in output
    assert "objective: Advance repo owner/repo through orchestrator session" in output
    assert "decision: verify" in output
    assert (
        "decision reason: running jobs need verification before the next transition"
        in output
    )
    assert "requires operator: no" in output
    assert "/tp-handle --session orch-1 --intent intent-1 --answer" in output


def test_workflow_handle_uses_orchestrator_service(capsys):
    from taskplane.workflow_cli import main
    from taskplane.settings import TaskplaneConfig

    exit_code = main(
        [
            "handle",
            "--session",
            "orch-1",
            "--repo",
            "owner/repo",
            "--request",
            "epic:42:progress_timeout",
            "--approve",
        ],
        config_loader=lambda: TaskplaneConfig(
            postgres_dsn="postgresql://user:pass@localhost:5432/taskplane"
        ),
        repository_builder=lambda **kwargs: object(),
        orchestrator_handle=lambda **kwargs: {
            "action": "ack_operator_request",
            "closed_request": type(
                "ClosedRequest",
                (),
                {
                    "epic_issue_number": 42,
                    "reason_code": "progress_timeout",
                    "closed_reason": "approved",
                },
            )(),
        },
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "ack_operator_request" in output
    assert "progress_timeout" in output


def test_workflow_handle_can_answer_intent(capsys):
    from taskplane.workflow_cli import main
    from taskplane.settings import TaskplaneConfig

    exit_code = main(
        [
            "handle",
            "--session",
            "orch-1",
            "--intent",
            "intent-1",
            "--answer",
            "Use JWT",
        ],
        config_loader=lambda: TaskplaneConfig(
            postgres_dsn="postgresql://user:pass@localhost:5432/taskplane"
        ),
        repository_builder=lambda **kwargs: object(),
        orchestrator_handle=lambda **kwargs: {
            "action": "answer_intent",
            "intent": type(
                "Intent", (), {"id": "intent-1", "status": "awaiting_review"}
            )(),
        },
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "answer_intent" in output
    assert "intent-1" in output
