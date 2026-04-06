from pathlib import Path
import threading
import json

from typing import Any, cast

from taskplane.adapters import (
    build_controlled_executor,
    build_browser_executor,
    build_shell_executor,
    build_shell_verifier,
    build_task_executor,
    build_task_verifier,
)
from taskplane.execution_protocol import (
    EXECUTION_CHECKPOINT_MARKER,
    EXECUTION_RESULT_MARKER,
)
from taskplane.models import ExecutionContext, WorkItem


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


def test_shell_executor_extracts_checkpoint_payload_and_strips_marker(tmp_path):
    work_item = WorkItem(
        id="task-10",
        title="checkpointed execution",
        lane="Lane 01",
        wave="wave-1",
        status="in_progress",
    )
    executor = build_shell_executor(
        command_template=(
            "python3 - <<'PY'\n"
            "print('working...')\n"
            "print('{marker}{payload}')\n"
            "PY"
        ).format(
            marker=EXECUTION_CHECKPOINT_MARKER,
            payload='{"execution_kind":"checkpoint","phase":"implementing","summary":"step 1"}',
        ),
        workdir=tmp_path,
    )

    result = executor(work_item)

    assert result.success is True
    assert result.result_payload_json == {
        "execution_kind": "checkpoint",
        "phase": "implementing",
        "summary": "step 1",
    }
    assert EXECUTION_CHECKPOINT_MARKER not in result.summary
    assert "working..." in result.summary


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
            "pathlib.Path(r'{output}').write_text(os.environ['TASKPLANE_EXECUTION_CONTEXT_JSON'])\""
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
        "TASKPLANE_DSN",
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
        "taskplane.opencode_task_executor.run_controlled_opencode_task",
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


def test_controlled_executor_extracts_checkpoint_payload(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    work_item = WorkItem(
        id="issue-140",
        title="[09-IMPL] Checkpointed adapter registry",
        lane="Lane 09",
        wave="Wave0",
        status="in_progress",
    )

    def fake_run_controlled_opencode_task(**kwargs):
        print("scanning workspace")
        print(
            f"{EXECUTION_CHECKPOINT_MARKER}"
            '{"execution_kind":"checkpoint","phase":"researching","summary":"found modules"}'
        )
        return 0

    monkeypatch.setattr(
        "taskplane.opencode_task_executor.run_controlled_opencode_task",
        fake_run_controlled_opencode_task,
    )

    executor = build_controlled_executor(workdir=tmp_path)
    result = executor(work_item)

    assert result.success is True
    assert result.result_payload_json == {
        "execution_kind": "checkpoint",
        "phase": "researching",
        "summary": "found modules",
    }
    assert EXECUTION_CHECKPOINT_MARKER not in result.summary
    assert "scanning workspace" in result.summary


def test_browser_executor_uses_real_browser_backend(monkeypatch, tmp_path):
    calls: list[dict[str, str]] = []

    class FakeBrowserExecutor:
        def __init__(self, output_dir):
            self.output_dir = output_dir

        def screenshot(self, url: str, filename: str | None = None):
            calls.append({"url": url, "filename": filename or ""})
            return type(
                "ScreenshotResult",
                (),
                {
                    "path": str(tmp_path / "shot.png"),
                    "content_digest": "digest",
                    "width": 1280,
                    "height": 720,
                },
            )()

    monkeypatch.setattr(
        "taskplane.adapters.BrowserExecutor",
        FakeBrowserExecutor,
    )
    work_item = WorkItem(
        id="task-browser-1",
        title="browser task",
        lane="Lane 04",
        wave="wave-1",
        status="in_progress",
    )
    executor = build_browser_executor(
        command_template='{"action":"screenshot","url":"https://example.com","filename":"page.png"}',
        workdir=tmp_path,
    )

    result = executor(work_item)

    assert result.success is True
    assert calls == [{"url": "https://example.com", "filename": "page.png"}]
    assert result.result_payload_json is not None
    assert result.result_payload_json["browser_action"] == "screenshot"
    assert result.result_payload_json["artifact_path"].endswith("shot.png")


def test_controlled_executor_calls_heartbeat_while_opencode_runs(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
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
        "taskplane.opencode_task_executor.run_controlled_opencode_task",
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


def test_controlled_executor_uses_codex_runner_for_codex_command(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    work_item = WorkItem(
        id="issue-201",
        title="[09-IMPL] Codex executor",
        lane="Lane 09",
        wave="Wave0",
        status="in_progress",
    )

    def fake_run_controlled_codex_task(**kwargs):
        print(
            f"{EXECUTION_RESULT_MARKER}"
            '{"outcome":"done","summary":"done by codex","decision_required":false}'
        )
        return 0

    monkeypatch.setattr(
        "taskplane.codex_task_executor.run_controlled_codex_task",
        fake_run_controlled_codex_task,
    )

    executor = build_controlled_executor(
        workdir=tmp_path,
        command_template="python3 -m taskplane.codex_task_executor",
    )
    result = executor(work_item)

    assert result.success is True
    assert result.command_digest == (
        "python -m taskplane.codex_task_executor"
    )
    assert result.result_payload_json == {
        "outcome": "done",
        "summary": "done by codex",
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
            == "python3 -m taskplane.opencode_task_executor"
        )
        assert workdir == tmp_path

        def _executor(*args, **kwargs):
            calls.append("shell")
            return cast(Any, object())

        return _executor

    monkeypatch.setattr(
        "taskplane.adapters.build_controlled_executor",
        fake_controlled_builder,
    )
    monkeypatch.setattr(
        "taskplane.adapters.build_shell_executor",
        fake_shell_builder,
    )

    executor = build_task_executor(
        command_template="python3 -m taskplane.opencode_task_executor",
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
        "taskplane.adapters.build_controlled_executor",
        fake_controlled_builder,
    )
    monkeypatch.setattr(
        "taskplane.adapters.build_shell_executor",
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
        "taskplane.adapters.build_controlled_executor",
        fake_controlled_builder,
    )
    monkeypatch.setattr(
        "taskplane.adapters.build_shell_executor",
        fake_shell_builder,
    )

    executor = build_task_executor(command_template="echo shell", workdir=tmp_path)

    executor(work_item)

    assert calls == ["controlled"]


def test_task_executor_routes_core_path_to_intelligent_when_enabled(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("TASKPLANE_ENABLE_LLM_EXECUTOR", "1")
    work_item = WorkItem(
        id="issue-501",
        title="[09-IMPL] LLM route",
        lane="Lane 09",
        wave="Wave0",
        status="in_progress",
        task_type="core_path",
    )
    calls: list[str] = []

    def fake_intelligent_builder(*, command_template: str, workdir: Path):
        assert command_template == "echo shell"
        assert workdir == tmp_path

        def _executor(*args, **kwargs):
            del args, kwargs
            calls.append("intelligent")
            return cast(Any, object())

        return _executor

    def fake_controlled_builder(*, workdir: Path):
        assert workdir == tmp_path

        def _executor(*args, **kwargs):
            del args, kwargs
            calls.append("controlled")
            return cast(Any, object())

        return _executor

    monkeypatch.setattr(
        "taskplane.adapters.build_intelligent_executor",
        fake_intelligent_builder,
    )
    monkeypatch.setattr(
        "taskplane.adapters.build_controlled_executor",
        fake_controlled_builder,
    )

    executor = build_task_executor(command_template="echo shell", workdir=tmp_path)
    executor(work_item)

    assert calls == ["intelligent"]


def test_task_executor_uses_executor_type_not_product_name_for_agent_cli_route(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("TASKPLANE_ENABLE_LLM_EXECUTOR", "1")
    work_item = WorkItem(
        id="issue-777",
        title="[09-IMPL] generic agent cli",
        lane="Lane 09",
        wave="Wave0",
        status="in_progress",
        task_type="core_path",
    )
    calls: list[str] = []

    class FakeRouter:
        def select_executor(self, task_type: str):
            del task_type
            return cast(
                Any,
                type(
                    "Cfg",
                    (),
                    {"executor_name": "internal-agent-x", "executor_type": "agent_cli"},
                )(),
            )

    def fake_router_ctor(dsn: str, default_executor_name=None):
        del dsn, default_executor_name
        return FakeRouter()

    def fake_intelligent_builder(*, command_template: str, workdir: Path):
        def _executor(*args, **kwargs):
            del args, kwargs
            calls.append("intelligent")
            return cast(Any, object())

        return _executor

    monkeypatch.setattr(
        "taskplane.adapters.build_intelligent_executor",
        fake_intelligent_builder,
    )
    monkeypatch.setattr(
        "taskplane.executor_router.ExecutorRouter",
        fake_router_ctor,
    )

    executor = build_task_executor(
        command_template="echo shell",
        workdir=tmp_path,
        dsn="postgresql://fake/fake",
    )
    executor(work_item)

    assert calls == ["intelligent"]


def test_task_executor_passes_work_item_and_execution_context_to_router_when_supported(
    monkeypatch, tmp_path
):
    work_item = WorkItem(
        id="issue-779",
        title="[09-IMPL] context aware route",
        lane="Lane 09",
        wave="Wave0",
        status="in_progress",
        task_type="core_path",
        attempt_count=2,
        last_failure_reason="timeout",
    )
    captured: dict[str, object] = {}
    calls: list[str] = []

    class FakeRouter:
        def select_executor(self, task_type: str, **kwargs):
            captured["task_type"] = task_type
            captured["work_item"] = kwargs.get("work_item")
            captured["execution_context"] = kwargs.get("execution_context")
            return cast(
                Any,
                type(
                    "Cfg",
                    (),
                    {"executor_name": "smart-router", "executor_type": "shell"},
                )(),
            )

    def fake_router_ctor(dsn: str, default_executor_name=None):
        del dsn, default_executor_name
        return FakeRouter()

    def fake_shell_builder(*, command_template: str, workdir: Path):
        def _executor(*args, **kwargs):
            del args, kwargs
            calls.append("shell")
            return cast(Any, object())

        return _executor

    monkeypatch.setattr(
        "taskplane.adapters.build_shell_executor",
        fake_shell_builder,
    )
    monkeypatch.setattr(
        "taskplane.executor_router.ExecutorRouter",
        fake_router_ctor,
    )

    executor = build_task_executor(
        command_template="echo shell",
        workdir=tmp_path,
        dsn="postgresql://fake/fake",
    )
    execution_context = ExecutionContext(
        work_id="issue-779",
        title=work_item.title,
        lane=work_item.lane,
        wave=work_item.wave,
        resume_hint="resume_candidate",
    )
    executor(work_item, execution_context=execution_context)

    assert calls == ["shell"]
    assert captured["task_type"] == "core_path"
    assert captured["work_item"] == work_item
    assert captured["execution_context"] == execution_context


def test_task_executor_logs_executor_selection_event_when_router_matches(
    monkeypatch, tmp_path
):
    work_item = WorkItem(
        id="issue-780",
        title="[09-IMPL] log selected executor",
        lane="Lane 09",
        wave="Wave0",
        status="in_progress",
        task_type="core_path",
    )
    logged: list[dict[str, object]] = []

    class FakeRouter:
        def select_executor(self, task_type: str, **kwargs):
            del task_type, kwargs
            return cast(
                Any,
                type(
                    "Cfg",
                    (),
                    {
                        "executor_name": "smart-router",
                        "executor_type": "shell",
                        "capabilities": ["bash"],
                    },
                )(),
            )

    def fake_router_ctor(dsn: str, default_executor_name=None):
        del dsn, default_executor_name
        return FakeRouter()

    def fake_shell_builder(*, command_template: str, workdir: Path):
        def _executor(*args, **kwargs):
            del args, kwargs
            return cast(Any, object())

        return _executor

    def fake_log_executor_selection(**kwargs):
        logged.append(kwargs)

    monkeypatch.setattr(
        "taskplane.adapters.build_shell_executor",
        fake_shell_builder,
    )
    monkeypatch.setattr(
        "taskplane.adapters._log_executor_selection",
        fake_log_executor_selection,
    )
    monkeypatch.setattr(
        "taskplane.executor_router.ExecutorRouter",
        fake_router_ctor,
    )

    executor = build_task_executor(
        command_template="echo shell",
        workdir=tmp_path,
        dsn="postgresql://fake/fake",
    )
    executor(work_item)

    assert logged == [
        {
            "dsn": "postgresql://fake/fake",
            "work_item": work_item,
            "executor_name": "smart-router",
            "executor_type": "shell",
            "task_type": "core_path",
        }
    ]


def test_task_executor_force_shell_executor_bypasses_router(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("TASKPLANE_FORCE_SHELL_EXECUTOR", "1")
    work_item = WorkItem(
        id="issue-781",
        title="[09-IMPL] force shell route",
        lane="Lane 09",
        wave="Wave0",
        status="in_progress",
        task_type="core_path",
    )
    calls: list[str] = []

    class FakeRouter:
        def select_executor(self, task_type: str, **kwargs):
            del task_type, kwargs
            calls.append("router")
            return cast(
                Any,
                type(
                    "Cfg",
                    (),
                    {"executor_name": "claude-code", "executor_type": "agent_cli"},
                )(),
            )

    def fake_router_ctor(dsn: str, default_executor_name=None):
        del dsn, default_executor_name
        return FakeRouter()

    def fake_shell_builder(*, command_template: str, workdir: Path):
        def _executor(*args, **kwargs):
            del args, kwargs
            calls.append("shell")
            return cast(Any, object())

        return _executor

    monkeypatch.setattr(
        "taskplane.adapters.build_shell_executor",
        fake_shell_builder,
    )
    monkeypatch.setattr(
        "taskplane.executor_router.ExecutorRouter",
        fake_router_ctor,
    )

    executor = build_task_executor(
        command_template="echo shell",
        workdir=tmp_path,
        dsn="postgresql://fake/fake",
    )
    executor(work_item)

    assert calls == ["shell"]


def test_task_executor_prefers_explicit_custom_command_over_router_agent_cli(
    monkeypatch, tmp_path
):
    work_item = WorkItem(
        id="issue-782",
        title="[09-IMPL] explicit custom executor command",
        lane="Lane 09",
        wave="Wave0",
        status="in_progress",
        task_type="core_path",
    )
    calls: list[str] = []

    class FakeRouter:
        def select_executor(self, task_type: str, **kwargs):
            del task_type, kwargs
            calls.append("router")
            return cast(
                Any,
                type(
                    "Cfg",
                    (),
                    {"executor_name": "claude-code", "executor_type": "agent_cli"},
                )(),
            )

    def fake_router_ctor(dsn: str, default_executor_name=None):
        del dsn, default_executor_name
        return FakeRouter()

    def fake_shell_builder(*, command_template: str, workdir: Path):
        assert command_template == "python3 -m taskplane.demo_task_executor"

        def _executor(*args, **kwargs):
            del args, kwargs
            calls.append("shell")
            return cast(Any, object())

        return _executor

    def fake_controlled_builder(*, workdir: Path, command_template: str | None = None):
        def _executor(*args, **kwargs):
            del args, kwargs
            calls.append("controlled")
            return cast(Any, object())

        return _executor

    monkeypatch.setattr(
        "taskplane.adapters.build_shell_executor",
        fake_shell_builder,
    )
    monkeypatch.setattr(
        "taskplane.adapters.build_controlled_executor",
        fake_controlled_builder,
    )
    monkeypatch.setattr(
        "taskplane.executor_router.ExecutorRouter",
        fake_router_ctor,
    )

    executor = build_task_executor(
        command_template="python3 -m taskplane.demo_task_executor",
        workdir=tmp_path,
        dsn="postgresql://fake/fake",
    )
    executor(work_item)

    assert calls == ["shell"]


def test_task_executor_routes_browser_by_executor_type(
    monkeypatch, tmp_path
):
    work_item = WorkItem(
        id="issue-778",
        title="[09-UI] generic browser route",
        lane="Lane 09",
        wave="Wave0",
        status="in_progress",
        task_type="ui_visual",
    )
    calls: list[str] = []

    class FakeRouter:
        def select_executor(self, task_type: str):
            del task_type
            return cast(
                Any,
                type(
                    "Cfg",
                    (),
                    {"executor_name": "visual-runner", "executor_type": "browser"},
                )(),
            )

    def fake_router_ctor(dsn: str, default_executor_name=None):
        del dsn, default_executor_name
        return FakeRouter()

    def fake_browser_builder(*, command_template: str, workdir: Path):
        def _executor(*args, **kwargs):
            del args, kwargs
            calls.append("browser")
            return cast(Any, object())

        return _executor

    monkeypatch.setattr(
        "taskplane.adapters.build_browser_executor",
        fake_browser_builder,
    )
    monkeypatch.setattr(
        "taskplane.executor_router.ExecutorRouter",
        fake_router_ctor,
    )

    executor = build_task_executor(
        command_template="echo shell",
        workdir=tmp_path,
        dsn="postgresql://fake/fake",
    )
    executor(work_item)

    assert calls == ["browser"]


def test_task_verifier_routes_to_llm_verifier_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("TASKPLANE_ENABLE_LLM_VERIFIER", "true")
    calls: list[str] = []

    def fake_adaptive_builder(*, command_template: str, workdir: Path, check_type: str):
        assert command_template == "pytest -q"
        assert workdir == tmp_path
        assert check_type == "pytest"

        def _verifier(*args, **kwargs):
            del args, kwargs
            calls.append("llm")
            return cast(Any, object())

        return _verifier

    monkeypatch.setattr(
        "taskplane.adapters.build_adaptive_verifier",
        fake_adaptive_builder,
    )

    verifier = build_task_verifier(
        command_template="pytest -q",
        workdir=tmp_path,
        check_type="pytest",
    )
    verifier(
        WorkItem(
            id="task-v",
            title="verify",
            lane="Lane 06",
            wave="wave-5",
            status="verifying",
        )
    )

    assert calls == ["llm"]
