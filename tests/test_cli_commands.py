from pathlib import Path

from taskplane.cli import main
from taskplane.models import (
    ExecutionGuardrailContext,
    VerificationEvidence,
)
from taskplane.worker import ExecutionResult, WorkerCycleResult


def _fake_executor(*args, **kwargs) -> ExecutionResult:
    return ExecutionResult(success=True, summary="ok")


def _fake_verifier(*args, **kwargs) -> VerificationEvidence:
    return VerificationEvidence(
        work_id="task",
        check_type="pytest",
        command="pytest",
        passed=True,
        output_digest="ok",
    )


def test_cli_main_builds_shell_adapters_when_commands_are_provided(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_repository_builder(*, dsn: str):
        return object()

    def fake_executor_builder(*, command_template: str, workdir: Path, dsn=None):
        captured["executor_command"] = command_template
        captured["executor_workdir"] = workdir
        return _fake_executor

    def fake_verifier_builder(*, command_template: str, workdir: Path, check_type: str):
        captured["verifier_command"] = command_template
        captured["verifier_workdir"] = workdir
        captured["verifier_check_type"] = check_type
        return _fake_verifier

    def fake_committer_builder(*, workdir: Path):
        captured["committer_workdir"] = workdir
        return object()

    def fake_cycle_runner(
        *,
        repository,
        context: ExecutionGuardrailContext,
        worker_name: str,
        executor,
        verifier,
        committer,
        work_item_ids=None,
        workspace_manager=None,
        dsn=None,
    ):
        captured["executor"] = executor
        captured["verifier"] = verifier
        captured["committer"] = committer
        return WorkerCycleResult(claimed_work_id=None)

    exit_code = main(
        [
            "--executor-command",
            "python3 -m pytest -q tests/test_worker.py",
            "--verifier-command",
            "python3 -m pytest -q",
            "--workdir",
            str(tmp_path),
        ],
        repository_builder=fake_repository_builder,
        cycle_runner=fake_cycle_runner,
        executor_builder=fake_executor_builder,
        verifier_builder=fake_verifier_builder,
        committer_builder=fake_committer_builder,
    )

    assert exit_code == 0
    assert captured["executor_command"] == "python3 -m pytest -q tests/test_worker.py"
    assert captured["verifier_command"] == "python3 -m pytest -q"
    assert captured["executor_workdir"] == tmp_path
    assert captured["verifier_workdir"] == tmp_path
    assert captured["committer_workdir"] == tmp_path
    assert captured["verifier_check_type"] == "pytest"


def test_cli_main_uses_task_verifier_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_repository_builder(*, dsn: str):
        return object()

    def fake_verifier_builder(*, command_template: str, workdir: Path, check_type: str):
        captured["verifier_command"] = command_template
        captured["verifier_workdir"] = workdir
        captured["verifier_check_type"] = check_type
        return _fake_verifier

    def fake_committer_builder(*, workdir: Path):
        return object()

    def fake_cycle_runner(
        *,
        repository,
        context: ExecutionGuardrailContext,
        worker_name: str,
        executor,
        verifier,
        committer,
        work_item_ids=None,
        workspace_manager=None,
        dsn=None,
    ):
        captured["verifier"] = verifier
        return WorkerCycleResult(claimed_work_id=None)

    exit_code = main(
        [
            "--workdir",
            str(tmp_path),
        ],
        repository_builder=fake_repository_builder,
        cycle_runner=fake_cycle_runner,
        verifier_builder=fake_verifier_builder,
        committer_builder=fake_committer_builder,
    )

    assert exit_code == 0
    assert (
        captured["verifier_command"]
        == "python3 -m taskplane.task_verifier"
    )
    assert captured["verifier_workdir"] == tmp_path
    assert captured["verifier_check_type"] == "pytest"


def test_story_runner_cli_builds_routed_task_executor_when_command_is_provided(
    monkeypatch, tmp_path
):
    from taskplane.story_runner_cli import main as story_main

    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    def fake_executor_builder(*, command_template: str, workdir: Path, dsn=None):
        captured["executor_command"] = command_template
        captured["executor_workdir"] = workdir
        return _fake_executor

    def fake_story_runner(**kwargs):
        captured["executor"] = kwargs["executor"]
        return type(
            "StoryRunResultStub",
            (),
            {
                "story_complete": False,
                "blocked_work_item_ids": [],
                "remaining_work_item_ids": ["issue-139"],
                "merge_blocked_reason": None,
            },
        )()

    exit_code = story_main(
        [
            "--story-issue-number",
            "130",
            "--executor-command",
            "python3 -m taskplane.opencode_task_executor",
            "--workdir",
            str(tmp_path),
        ],
        repository_builder=lambda *, dsn: object(),
        story_loader=lambda **kwargs: ["issue-139"],
        story_runner=fake_story_runner,
        executor_builder=fake_executor_builder,
        verifier_builder=lambda **kwargs: _fake_verifier,
        committer_builder=lambda **kwargs: object(),
        story_integrator_builder=lambda **kwargs: object(),
    )

    assert exit_code == 0
    assert captured["executor_command"] == (
        "python3 -m taskplane.opencode_task_executor"
    )
    assert captured["executor_workdir"] == tmp_path


def test_hierarchy_api_cli_reads_dsn_from_taskplane_toml(tmp_path, monkeypatch):
    import os
    import sys
    import types

    from taskplane.hierarchy_api_cli import main

    config_path = tmp_path / "taskplane.toml"
    config_path.write_text(
        """
[postgres]
dsn = "postgresql://user:pass@localhost:5432/taskplane"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TASKPLANE_DSN", raising=False)

    captured: dict[str, object] = {}

    fake_uvicorn = types.SimpleNamespace(
        run=lambda app, host, port, reload: captured.update(
            {
                "app": app,
                "host": host,
                "port": port,
                "reload": reload,
                "dsn": os.getenv("TASKPLANE_DSN"),
            }
        )
    )
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    exit_code = main(["--host", "127.0.0.1", "--port", "8123"])

    assert exit_code == 0
    assert captured["app"] == "taskplane.hierarchy_api:app"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8123
    assert captured["reload"] is False
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/taskplane"


def test_cli_main_exports_dsn_from_taskplane_toml_to_subprocess_environment(
    tmp_path, monkeypatch
):
    import os

    from taskplane.cli import main
    from taskplane.models import ExecutionGuardrailContext
    from taskplane.worker import WorkerCycleResult

    (tmp_path / "taskplane.toml").write_text(
        """
[postgres]
dsn = "postgresql://user:pass@localhost:5432/taskplane"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TASKPLANE_DSN", raising=False)

    observed: dict[str, object] = {}

    def fake_repository_builder(*, dsn: str):
        observed["dsn"] = dsn
        return object()

    def fake_verifier_builder(*, command_template: str, workdir, check_type: str):
        observed["env_dsn"] = os.getenv("TASKPLANE_DSN")
        return lambda *args, **kwargs: None

    def fake_cycle_runner(
        *,
        repository,
        context: ExecutionGuardrailContext,
        worker_name: str,
        executor,
        verifier,
        committer,
        work_item_ids=None,
        workspace_manager=None,
        dsn=None,
    ):
        return WorkerCycleResult(claimed_work_id=None)

    exit_code = main(
        ["--workdir", str(tmp_path), "--verifier-command", "true"],
        repository_builder=fake_repository_builder,
        cycle_runner=fake_cycle_runner,
        verifier_builder=fake_verifier_builder,
        committer_builder=lambda **kwargs: object(),
    )

    assert exit_code == 0
    assert observed["dsn"] == "postgresql://user:pass@localhost:5432/taskplane"
    assert observed["env_dsn"] == "postgresql://user:pass@localhost:5432/taskplane"
