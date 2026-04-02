from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from typing import Any

import pytest

from taskplane.models import WorkClaim, WorkItem, WorkStatus


def _sample_work_item(*, status: WorkStatus = "blocked") -> WorkItem:
    return WorkItem(
        id="task-1",
        repo="codefromkarl/stardrifter",
        title="Retry task",
        lane="lane-1",
        wave="wave-1",
        status=status,
        source_issue_number=101,
        attempt_count=3,
        last_failure_reason="timeout",
        next_eligible_at="2026-03-25T10:00:00+00:00",
        blocked_reason="timeout",
        decision_required=False,
    )


def test_run_epic_split_action_uses_repo_specific_workdir(tmp_path):
    from taskplane.console_actions import (
        ConsoleActionSettings,
        run_epic_split_action,
    )

    captured: dict[str, object] = {}

    class FakeConnection:
        def commit(self):
            return None

    def fake_repository_builder(*, dsn: str):
        captured["dsn"] = dsn
        return type("Repo", (), {"_connection": FakeConnection()})()

    class FakeProcess:
        pid = 4242

    def fake_command_builder(
        *,
        dsn: str,
        repo: str,
        epic_issue_number: int,
        project_dir: Path,
    ):
        captured["dsn"] = dsn
        captured["repo"] = repo
        captured["epic_issue_number"] = epic_issue_number
        captured["workdir"] = project_dir
        return "epic-command"

    def fake_launcher(command: str, log_path: Path):
        captured["command"] = command
        captured["log_path"] = log_path
        return FakeProcess()

    def fake_job_inserter(**kwargs):
        captured["job"] = kwargs

    payload = run_epic_split_action(
        repo="codefromkarl/stardrifter",
        epic_issue_number=42,
        settings=ConsoleActionSettings(
            dsn="postgresql://user:pass@localhost/db",
            repo_workdirs={"codefromkarl/stardrifter": str(tmp_path)},
            repo_log_dirs={"codefromkarl/stardrifter": str(tmp_path / "logs")},
        ),
        repository_builder=fake_repository_builder,
        epic_command_builder=fake_command_builder,
        process_launcher=fake_launcher,
        job_inserter=fake_job_inserter,
        running_job_loader=lambda *, connection, repo: [],
    )

    assert payload["accepted"] is True
    assert payload["action"] == "split_epic"
    assert payload["repo"] == "codefromkarl/stardrifter"
    assert payload["epic_issue_number"] == 42
    assert payload["job"]["pid"] == 4242
    assert captured["workdir"] == tmp_path
    assert captured["command"] == "epic-command"
    assert captured["job"]["job_kind"] == "epic_decomposition"
    assert captured["job"]["story_issue_number"] == 42
    assert captured["job"]["launch_backend"] == "console"
    assert payload["job"]["worker_name"] == "console-epic-42"


def test_run_story_split_action_uses_repo_specific_workdir(tmp_path):
    from taskplane.console_actions import (
        ConsoleActionSettings,
        run_story_split_action,
    )

    captured: dict[str, object] = {}

    class FakeConnection:
        def commit(self):
            return None

    def fake_repository_builder(*, dsn: str):
        captured["dsn"] = dsn
        return type("Repo", (), {"_connection": FakeConnection()})()

    class FakeProcess:
        pid = 5656

    def fake_command_builder(
        *,
        dsn: str,
        repo: str,
        story_issue_number: int,
        project_dir: Path,
    ):
        captured["dsn"] = dsn
        captured["repo"] = repo
        captured["story_issue_number"] = story_issue_number
        captured["workdir"] = project_dir
        return "story-command"

    def fake_launcher(command: str, log_path: Path):
        captured["command"] = command
        captured["log_path"] = log_path
        return FakeProcess()

    def fake_job_inserter(**kwargs):
        captured["job"] = kwargs

    payload = run_story_split_action(
        repo="codefromkarl/stardrifter",
        story_issue_number=77,
        settings=ConsoleActionSettings(
            dsn="postgresql://user:pass@localhost/db",
            repo_workdirs={"codefromkarl/stardrifter": str(tmp_path)},
            repo_log_dirs={"codefromkarl/stardrifter": str(tmp_path / "logs")},
        ),
        repository_builder=fake_repository_builder,
        story_command_builder=fake_command_builder,
        process_launcher=fake_launcher,
        job_inserter=fake_job_inserter,
        running_job_loader=lambda *, connection, repo: [],
    )

    assert payload["accepted"] is True
    assert payload["action"] == "split_story"
    assert payload["story_issue_number"] == 77
    assert payload["job"]["pid"] == 5656
    assert captured["workdir"] == tmp_path
    assert captured["command"] == "story-command"
    assert captured["job"]["job_kind"] == "story_decomposition"
    assert captured["job"]["story_issue_number"] == 77
    assert captured["job"]["launch_backend"] == "console"
    assert payload["job"]["worker_name"] == "console-story-77"


def test_retry_task_action_requeues_blocked_task_and_syncs_ready_states():
    from taskplane.console_actions import run_task_retry_action

    calls: list[tuple[Any, ...]] = []
    work_item = _sample_work_item(status="blocked")
    active_claim = WorkClaim(
        work_id="task-1",
        worker_name="worker-a",
        workspace_path="/tmp/work",
        branch_name="branch-a",
        lease_token="lease",
        lease_expires_at="3026-03-25T10:00:00+00:00",
        claimed_paths=("src",),
    )

    class FakeRepository:
        def get_work_item(self, work_id: str):
            assert work_id == "task-1"
            nonlocal work_item
            return work_item

        def list_active_work_claims(self):
            return [active_claim]

        def delete_work_claim(self, work_id: str):
            calls.append(("delete_work_claim", work_id))

        def update_work_status(self, work_id: str, status: str, **kwargs):
            calls.append(("update_work_status", work_id, status, kwargs))
            nonlocal work_item
            work_item = replace(
                work_item,
                status=status,
                blocked_reason=kwargs.get("blocked_reason"),
                decision_required=kwargs.get("decision_required", False),
                next_eligible_at=kwargs.get("next_eligible_at"),
            )

        def sync_ready_states(self):
            calls.append(("sync_ready_states",))
            nonlocal work_item
            work_item = replace(work_item, status="ready")

    payload = run_task_retry_action(
        repo="codefromkarl/stardrifter",
        work_id="task-1",
        repository=FakeRepository(),
    )

    assert payload["accepted"] is True
    assert payload["previous_status"] == "blocked"
    assert payload["new_status"] == "ready"
    assert calls[0] == ("delete_work_claim", "task-1")
    assert calls[1][0] == "update_work_status"
    assert calls[1][2] == "pending"
    assert calls[1][3]["blocked_reason"] is None
    assert calls[1][3]["decision_required"] is False
    assert calls[1][3]["next_eligible_at"] is None
    assert calls[2] == ("sync_ready_states",)


def test_retry_task_action_rejects_active_in_progress_task():
    from taskplane.console_actions import (
        ConsoleActionConflictError,
        run_task_retry_action,
    )

    class FakeRepository:
        def get_work_item(self, work_id: str):
            return _sample_work_item(status="in_progress")

        def list_active_work_claims(self):
            return []

    with pytest.raises(ConsoleActionConflictError):
        run_task_retry_action(
            repo="codefromkarl/stardrifter",
            work_id="task-1",
            repository=FakeRepository(),
        )


def test_run_epic_split_action_rejects_epic_already_decomposing(tmp_path):
    from taskplane.console_actions import (
        ConsoleActionConflictError,
        ConsoleActionSettings,
        run_epic_split_action,
    )

    class FakeRepository:
        def __init__(self):
            self.calls: list[tuple[Any, ...]] = []

        def get_program_epic(self, *, repo: str, issue_number: int):
            self.calls.append(("get_program_epic", repo, issue_number))
            return {
                "issue_number": issue_number,
                "execution_status": "decomposing",
                "title": "Epic A",
            }

    repository = FakeRepository()

    with pytest.raises(ConsoleActionConflictError):
        run_epic_split_action(
            repo="codefromkarl/stardrifter",
            epic_issue_number=42,
            settings=ConsoleActionSettings(
                dsn="postgresql://user:pass@localhost/db",
                repo_workdirs={"codefromkarl/stardrifter": str(tmp_path)},
                repo_log_dirs={"codefromkarl/stardrifter": str(tmp_path / "logs")},
            ),
            repository_builder=lambda *, dsn: repository,
            epic_command_builder=lambda **kwargs: pytest.fail(
                "command builder should not be called"
            ),
        )


def test_run_story_split_action_rejects_story_already_active_with_tasks(tmp_path):
    from taskplane.console_actions import (
        ConsoleActionConflictError,
        ConsoleActionSettings,
        run_story_split_action,
    )

    class FakeRepository:
        def get_program_story(self, *, repo: str, issue_number: int):
            return {
                "issue_number": issue_number,
                "execution_status": "active",
                "title": "Story A",
                "task_count": 3,
            }

    with pytest.raises(ConsoleActionConflictError):
        run_story_split_action(
            repo="codefromkarl/stardrifter",
            story_issue_number=77,
            settings=ConsoleActionSettings(
                dsn="postgresql://user:pass@localhost/db",
                repo_workdirs={"codefromkarl/stardrifter": str(tmp_path)},
                repo_log_dirs={"codefromkarl/stardrifter": str(tmp_path / "logs")},
            ),
            repository_builder=lambda *, dsn: FakeRepository(),
            story_command_builder=lambda **kwargs: pytest.fail(
                "command builder should not be called"
            ),
        )


def test_run_epic_split_action_rejects_existing_running_epic_job(tmp_path):
    from taskplane.console_actions import (
        ConsoleActionConflictError,
        ConsoleActionSettings,
        run_epic_split_action,
    )

    class FakeConnection:
        pass

    class FakeRepository:
        _connection = FakeConnection()

        def get_program_epic(self, *, repo: str, issue_number: int):
            return {
                "issue_number": issue_number,
                "execution_status": "backlog",
                "title": "Epic A",
            }

    with pytest.raises(ConsoleActionConflictError):
        run_epic_split_action(
            repo="codefromkarl/stardrifter",
            epic_issue_number=42,
            settings=ConsoleActionSettings(
                dsn="postgresql://user:pass@localhost/db",
                repo_workdirs={"codefromkarl/stardrifter": str(tmp_path)},
                repo_log_dirs={"codefromkarl/stardrifter": str(tmp_path / "logs")},
            ),
            repository_builder=lambda *, dsn: FakeRepository(),
            running_job_loader=lambda *, connection, repo: [
                {
                    "job_kind": "epic_decomposition",
                    "story_issue_number": 42,
                    "status": "running",
                }
            ],
            epic_command_builder=lambda **kwargs: pytest.fail(
                "command builder should not be called"
            ),
        )


def test_run_story_split_action_rejects_existing_running_story_job(tmp_path):
    from taskplane.console_actions import (
        ConsoleActionConflictError,
        ConsoleActionSettings,
        run_story_split_action,
    )

    class FakeConnection:
        pass

    class FakeRepository:
        _connection = FakeConnection()

        def get_program_story(self, *, repo: str, issue_number: int):
            return {
                "issue_number": issue_number,
                "execution_status": "planned",
                "title": "Story A",
                "task_count": 0,
            }

    with pytest.raises(ConsoleActionConflictError):
        run_story_split_action(
            repo="codefromkarl/stardrifter",
            story_issue_number=77,
            settings=ConsoleActionSettings(
                dsn="postgresql://user:pass@localhost/db",
                repo_workdirs={"codefromkarl/stardrifter": str(tmp_path)},
                repo_log_dirs={"codefromkarl/stardrifter": str(tmp_path / "logs")},
            ),
            repository_builder=lambda *, dsn: FakeRepository(),
            running_job_loader=lambda *, connection, repo: [
                {
                    "job_kind": "story_decomposition",
                    "story_issue_number": 77,
                    "status": "running",
                }
            ],
            story_command_builder=lambda **kwargs: pytest.fail(
                "command builder should not be called"
            ),
        )


def test_retry_task_action_preserves_failure_context_fields():
    from taskplane.console_actions import run_task_retry_action

    work_item = _sample_work_item(status="blocked")

    class FakeRepository:
        def get_work_item(self, work_id: str):
            return work_item

        def list_active_work_claims(self):
            return []

        def update_work_status(self, work_id: str, status: str, **kwargs):
            nonlocal work_item
            work_item = replace(
                work_item,
                status=status,
                blocked_reason=kwargs.get("blocked_reason"),
                decision_required=kwargs.get("decision_required", False),
                next_eligible_at=kwargs.get("next_eligible_at"),
            )

        def sync_ready_states(self):
            nonlocal work_item
            work_item = replace(work_item, status="ready")

    payload = run_task_retry_action(
        repo="codefromkarl/stardrifter",
        work_id="task-1",
        repository=FakeRepository(),
    )

    assert payload["retry_context"]["attempt_count"] == 3
    assert payload["retry_context"]["last_failure_reason"] == "timeout"
    assert payload["retry_context"]["blocked_reason"] is None
    assert payload["retry_context"]["decision_required"] is False
