from pathlib import Path
import threading
import json

from typing import Any, cast

from stardrifter_orchestration_mvp.adapters import (
    build_controlled_executor,
    build_shell_executor,
    build_shell_verifier,
    build_task_executor,
)
from stardrifter_orchestration_mvp.execution_protocol import EXECUTION_RESULT_MARKER
from stardrifter_orchestration_mvp.models import ExecutionContext, WorkItem


def test_shell_executor_runs_command_and_returns_success(tmp_path):
    work_item = WorkItem(
        id="task-2",
        title="safe cleanup",
        lane="Lane 06",
        wave="wave-5",
        status="in_progress",
    )
    output_path = tmp_path / "executor.txt"
    executor = build_shell_executor(
        command_template=(
            'python3 -c "from pathlib import Path; '
            "Path(r'{output}').write_text('executed')\""
        ).format(output=output_path),
        workdir=tmp_path,
    )

    result = executor(work_item)

    assert result.success is True
    assert output_path.read_text() == "executed"
    assert "python3 -c" in (result.command_digest or "")
    assert result.exit_code == 0
    assert result.elapsed_ms is not None and result.elapsed_ms >= 0
    assert result.stdout_digest == ""
    assert result.stderr_digest == ""
    assert result.result_payload_json is None


def test_shell_verifier_returns_false_for_nonzero_exit(tmp_path):
    work_item = WorkItem(
        id="task-3",
        title="failing verify",
        lane="Lane 06",
        wave="wave-5",
        status="verifying",
    )
    verifier = build_shell_verifier(
        command_template="python3 -c \"import sys; print('fail'); sys.exit(2)\"",
        workdir=tmp_path,
        check_type="pytest",
    )

    evidence = verifier(work_item)

    assert evidence.passed is False
    assert evidence.exit_code == 2
    assert evidence.elapsed_ms is not None and evidence.elapsed_ms >= 0
    assert "python3 -c" in evidence.command
    assert "fail" in evidence.stdout_digest


def test_shell_executor_extracts_structured_execution_result(tmp_path):
    work_item = WorkItem(
        id="task-9",
        title="needs decision",
        lane="Lane 01",
        wave="wave-1",
        status="in_progress",
    )
    executor = build_shell_executor(
        command_template=(
            "python3 - <<'PY'\nprint('{marker}{payload}')\nPY\nexit 5"
        ).format(
            marker=EXECUTION_RESULT_MARKER,
            payload='{"outcome":"needs_decision","summary":"缺少边界批准","reason_code":"missing-approval","question":"是否允许改 authority?","decision_required":true}',
        ),
        workdir=tmp_path,
    )

    result = executor(work_item)

    assert result.success is False
    assert result.decision_required is True
    assert result.blocked_reason == "missing-approval"
    assert result.result_payload_json is not None
    assert result.result_payload_json["outcome"] == "needs_decision"
    assert EXECUTION_RESULT_MARKER not in result.summary


def test_shell_executor_calls_heartbeat_while_command_is_running(tmp_path):
    work_item = WorkItem(
        id="task-15",
        title="heartbeat shell executor",
        lane="Lane 06",
        wave="wave-5",
        status="in_progress",
    )
    heartbeat_calls: list[int] = []
    executor = build_shell_executor(
        command_template="python3 -c \"import time; time.sleep(0.25); print('done')\"",
        workdir=tmp_path,
    )

    heartbeat_executor = cast(Any, executor)
    result = heartbeat_executor(work_item, heartbeat=lambda: heartbeat_calls.append(1))

    assert result.success is True
    assert len(heartbeat_calls) >= 1


def test_shell_executor_does_not_deadlock_on_large_stdout(tmp_path):
    work_item = WorkItem(
        id="task-16",
        title="large output shell executor",
        lane="Lane 06",
        wave="wave-5",
        status="in_progress",
    )
    executor = build_shell_executor(
        command_template=(
            'python3 -c "import sys; '
            "sys.stdout.write('x'*200000); "
            "sys.stderr.write('y'*200000)\""
        ),
        workdir=tmp_path,
    )

    result_holder: dict[str, object] = {}

    def run_executor() -> None:
        result_holder["result"] = executor(work_item)

    thread = threading.Thread(target=run_executor)
    thread.start()
    thread.join(timeout=3)

    assert not thread.is_alive()
    result = cast(Any, result_holder["result"])
    assert result.success is True


def test_shell_executor_exports_execution_context_json(tmp_path):
    work_item = WorkItem(
        id="task-32",
        title="context env",
        lane="Lane 06",
        wave="wave-5",
        status="in_progress",
        repo="codefromkarl/stardrifter",
        source_issue_number=32,
        canonical_story_issue_number=14,
        story_issue_numbers=(14,),
        planned_paths=("src/stardrifter_engine/runtime.py",),
    )
    output_path = tmp_path / "context.json"
    executor = build_shell_executor(
        command_template=(
            'python3 -c "import os, pathlib; '
            "pathlib.Path(r'{output}').write_text(os.environ['STARDRIFTER_EXECUTION_CONTEXT_JSON'])\""
        ).format(output=output_path),
        workdir=tmp_path,
    )

    heartbeat_executor = cast(Any, executor)
    result = heartbeat_executor(
        work_item,
        execution_context=ExecutionContext(
            work_id="task-32",
            title="context env",
            lane="Lane 06",
            wave="wave-5",
            repo="codefromkarl/stardrifter",
            source_issue_number=32,
            canonical_story_issue_number=14,
            story_issue_numbers=(14,),
            planned_paths=("src/stardrifter_engine/runtime.py",),
            workspace_path=str(tmp_path),
            project_dir=str(tmp_path),
        ),
    )

    assert result.success is True
    payload = json.loads(output_path.read_text())
    assert payload["work_id"] == "task-32"
    assert payload["repo"] == "codefromkarl/stardrifter"
    assert payload["source_issue_number"] == 32


def test_controlled_executor_preserves_payload_semantics(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    work_item = WorkItem(
        id="issue-139",
        title="[09-IMPL] Adapter registry",
        lane="Lane 09",
        wave="Wave0",
        status="in_progress",
    )

    def fake_run_controlled_opencode_task(**kwargs):
        print(
            f"{EXECUTION_RESULT_MARKER}"
            '{"outcome":"needs_decision","summary":"Need approval","reason_code":"awaiting_user_input","decision_required":true}'
        )
        return 5

    monkeypatch.setattr(
        "stardrifter_orchestration_mvp.opencode_task_executor.run_controlled_opencode_task",
        fake_run_controlled_opencode_task,
    )

    executor = build_controlled_executor(workdir=tmp_path)
    result = executor(work_item)

    assert result.success is False
    assert result.exit_code == 5
    assert result.decision_required is True
    assert result.blocked_reason == "awaiting_user_input"
    assert result.result_payload_json == {
        "outcome": "needs_decision",
        "summary": "Need approval",
        "reason_code": "awaiting_user_input",
        "decision_required": True,
    }
    assert EXECUTION_RESULT_MARKER not in result.summary


def test_controlled_executor_calls_heartbeat_while_opencode_runs(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "STARDRIFTER_ORCHESTRATION_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    work_item = WorkItem(
        id="issue-139",
        title="[09-IMPL] Adapter registry",
        lane="Lane 09",
        wave="Wave0",
        status="in_progress",
    )
    heartbeat_calls: list[int] = []

    def fake_run_controlled_opencode_task(**kwargs):
        del kwargs
        import time

        time.sleep(0.25)
        print(
            f"{EXECUTION_RESULT_MARKER}"
            '{"outcome":"done","summary":"done","decision_required":false}'
        )
        return 0

    monkeypatch.setattr(
        "stardrifter_orchestration_mvp.opencode_task_executor.run_controlled_opencode_task",
        fake_run_controlled_opencode_task,
    )

    executor = build_controlled_executor(workdir=tmp_path)
    heartbeat_executor = cast(Any, executor)

    result = heartbeat_executor(
        work_item,
        heartbeat=lambda: heartbeat_calls.append(1),
    )

    assert result.success is True
    assert len(heartbeat_calls) >= 1
    assert result.result_payload_json == {
        "outcome": "done",
        "summary": "done",
        "decision_required": False,
    }


def test_task_executor_routes_implementation_tasks_to_controlled_path(
    monkeypatch, tmp_path
):
    work_item = WorkItem(
        id="issue-139",
        title="[09-IMPL] Adapter registry",
        lane="Lane 09",
        wave="Wave0",
        status="in_progress",
        task_type="core_path",
    )
    calls: list[str] = []

    def fake_controlled_builder(*, workdir: Path):
        assert workdir == tmp_path

        def _executor(*args, **kwargs):
            calls.append("controlled")
            return cast(Any, object())

        return _executor

    def fake_shell_builder(*, command_template: str, workdir: Path):
        assert (
            command_template
            == "python3 -m stardrifter_orchestration_mvp.opencode_task_executor"
        )
        assert workdir == tmp_path

        def _executor(*args, **kwargs):
            calls.append("shell")
            return cast(Any, object())

        return _executor

    monkeypatch.setattr(
        "stardrifter_orchestration_mvp.adapters.build_controlled_executor",
        fake_controlled_builder,
    )
    monkeypatch.setattr(
        "stardrifter_orchestration_mvp.adapters.build_shell_executor",
        fake_shell_builder,
    )

    executor = build_task_executor(
        command_template="python3 -m stardrifter_orchestration_mvp.opencode_task_executor",
        workdir=tmp_path,
    )

    executor(work_item)

    assert calls == ["controlled"]


def test_task_executor_routes_non_implementation_tasks_to_shell_path(
    monkeypatch, tmp_path
):
    work_item = WorkItem(
        id="issue-140",
        title="[09-DOC] Update notes",
        lane="Lane 09",
        wave="Wave0",
        status="in_progress",
        task_type="documentation",
    )
    calls: list[str] = []

    def fake_controlled_builder(*, workdir: Path):
        def _executor(*args, **kwargs):
            calls.append("controlled")
            return cast(Any, object())

        return _executor

    def fake_shell_builder(*, command_template: str, workdir: Path):
        def _executor(*args, **kwargs):
            calls.append("shell")
            return cast(Any, object())

        return _executor

    monkeypatch.setattr(
        "stardrifter_orchestration_mvp.adapters.build_controlled_executor",
        fake_controlled_builder,
    )
    monkeypatch.setattr(
        "stardrifter_orchestration_mvp.adapters.build_shell_executor",
        fake_shell_builder,
    )

    executor = build_task_executor(command_template="echo shell", workdir=tmp_path)

    executor(
        work_item,
        execution_context=ExecutionContext(
            work_id="issue-140",
            title=work_item.title,
            lane=work_item.lane,
            wave=work_item.wave,
        ),
    )

    assert calls == ["shell"]


def test_task_executor_uses_title_signal_only_when_task_type_metadata_missing(
    monkeypatch, tmp_path
):
    work_item = WorkItem(
        id="issue-141",
        title="[09-IMPL] Fallback classification",
        lane="Lane 09",
        wave="Wave0",
        status="in_progress",
        task_type=cast(Any, ""),
    )
    calls: list[str] = []

    def fake_controlled_builder(*, workdir: Path):
        def _executor(*args, **kwargs):
            calls.append("controlled")
            return cast(Any, object())

        return _executor

    def fake_shell_builder(*, command_template: str, workdir: Path):
        def _executor(*args, **kwargs):
            calls.append("shell")
            return cast(Any, object())

        return _executor

    monkeypatch.setattr(
        "stardrifter_orchestration_mvp.adapters.build_controlled_executor",
        fake_controlled_builder,
    )
    monkeypatch.setattr(
        "stardrifter_orchestration_mvp.adapters.build_shell_executor",
        fake_shell_builder,
    )

    executor = build_task_executor(command_template="echo shell", workdir=tmp_path)

    executor(work_item)

    assert calls == ["controlled"]
