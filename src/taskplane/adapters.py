from __future__ import annotations

import json
import os
import contextlib
import io
from pathlib import Path
import subprocess
import threading
import time
from typing import Callable

import psycopg

from .browser_executor import BrowserExecutor
from .executor_adapter import parse_executor_output
from .intelligent_executor import (
    build_adaptive_verifier,
    build_intelligent_executor,
    llm_executor_enabled,
    llm_verifier_enabled,
)
from .models import ExecutionContext, VerificationEvidence, WorkItem
from .execution_protocol import (
    EXECUTION_CHECKPOINT_MARKER,
    EXECUTION_RESULT_MARKER,
    EXECUTION_RETRY_INTENT_MARKER,
    EXECUTION_WAIT_MARKER,
)
from .protocols import ExecutorAdapter, VerifierAdapter
from .worker import ExecutionResult


def build_shell_executor(
    *,
    command_template: str,
    workdir: Path,
) -> ExecutorAdapter:
    def _executor(
        work_item: WorkItem,
        workspace_path: Path | None = None,
        execution_context: ExecutionContext | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> ExecutionResult:
        completed, elapsed_ms = _run_command(
            command_template=command_template,
            work_item=work_item,
            workdir=workspace_path or workdir,
            execution_context=execution_context,
            heartbeat=heartbeat,
        )
        metadata = _extract_execution_result_metadata(completed)
        stdout_digest, stderr_digest, output = _build_output_digest(
            completed,
            strip_execution_marker=True,
        )
        return ExecutionResult(
            success=completed.returncode == 0,
            summary=output,
            command_digest=command_template,
            exit_code=completed.returncode,
            elapsed_ms=elapsed_ms,
            stdout_digest=stdout_digest,
            stderr_digest=stderr_digest,
            blocked_reason=metadata.get("blocked_reason")
            or metadata.get("reason_code"),
            decision_required=bool(metadata.get("decision_required") or False),
            result_payload_json=metadata or None,
        )

    return _executor


def build_shell_verifier(
    *,
    command_template: str,
    workdir: Path,
    check_type: str,
) -> VerifierAdapter:
    def _verifier(
        work_item: WorkItem,
        workspace_path: Path | None = None,
        execution_context: ExecutionContext | None = None,
    ) -> VerificationEvidence:
        completed, elapsed_ms = _run_command(
            command_template=command_template,
            work_item=work_item,
            workdir=workspace_path or workdir,
            execution_context=execution_context,
        )
        stdout_digest, stderr_digest, output = _build_output_digest(completed)
        command = f"{check_type}:{command_template}"
        return VerificationEvidence(
            work_id=work_item.id,
            check_type=check_type,
            command=command,
            passed=completed.returncode == 0,
            output_digest=output,
            exit_code=completed.returncode,
            elapsed_ms=elapsed_ms,
            stdout_digest=stdout_digest,
            stderr_digest=stderr_digest,
        )

    return _verifier


def build_task_verifier(
    *,
    command_template: str,
    workdir: Path,
    check_type: str,
) -> VerifierAdapter:
    if llm_verifier_enabled(command_template=command_template):
        return build_adaptive_verifier(
            command_template=command_template,
            workdir=workdir,
            check_type=check_type,
        )
    return build_shell_verifier(
        command_template=command_template,
        workdir=workdir,
        check_type=check_type,
    )


def build_controlled_executor(
    *, workdir: Path, command_template: str | None = None
) -> ExecutorAdapter:
    runner_module = (
        "codex_task_executor"
        if command_template
        and "taskplane.codex_task_executor" in command_template
        else "opencode_task_executor"
    )
    command_digest = f"python -m taskplane.{runner_module}"

    def _executor(
        work_item: WorkItem,
        workspace_path: Path | None = None,
        execution_context: ExecutionContext | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> ExecutionResult:
        effective_workdir = workspace_path or workdir
        previous_project_dir = os.environ.get("TASKPLANE_PROJECT_DIR")
        os.environ["TASKPLANE_PROJECT_DIR"] = str(effective_workdir)
        try:
            if runner_module == "codex_task_executor":
                from .codex_task_executor import run_controlled_codex_task

                runner = lambda: run_controlled_codex_task(
                    work_id=work_item.id,
                    dsn=_load_required_env("TASKPLANE_DSN"),
                    project_dir=effective_workdir,
                    resume_context=_load_resume_context(execution_context),
                )
            else:
                from .opencode_task_executor import run_controlled_opencode_task

                runner = lambda: run_controlled_opencode_task(
                    work_id=work_item.id,
                    dsn=_load_required_env("TASKPLANE_DSN"),
                    project_dir=effective_workdir,
                    bounded_mode=_should_use_bounded_mode(
                        work_item=work_item,
                        execution_context=execution_context,
                    ),
                    resume_context=_load_resume_context(execution_context),
                )

            completed, elapsed_ms = _run_callable_executor(
                runner,
                heartbeat=heartbeat,
            )
        finally:
            if previous_project_dir is None:
                os.environ.pop("TASKPLANE_PROJECT_DIR", None)
            else:
                os.environ["TASKPLANE_PROJECT_DIR"] = previous_project_dir
        metadata = _extract_execution_result_metadata(completed)
        stdout_digest, stderr_digest, output = _build_output_digest(
            completed,
            strip_execution_marker=True,
        )
        return ExecutionResult(
            success=completed.returncode == 0,
            summary=output,
            command_digest=command_digest,
            exit_code=completed.returncode,
            elapsed_ms=elapsed_ms,
            stdout_digest=stdout_digest,
            stderr_digest=stderr_digest,
            blocked_reason=metadata.get("blocked_reason")
            or metadata.get("reason_code"),
            decision_required=bool(metadata.get("decision_required") or False),
            result_payload_json=metadata or None,
        )

    return _executor


def build_browser_executor(
    *,
    command_template: str,
    workdir: Path,
) -> ExecutorAdapter:
    browser = BrowserExecutor(output_dir=workdir / ".run-logs" / "browser")

    def _executor(
        work_item: WorkItem,
        workspace_path: Path | None = None,
        execution_context: ExecutionContext | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> ExecutionResult:
        del work_item, execution_context, heartbeat
        started_at = time.perf_counter()
        work_path = workspace_path or workdir
        try:
            command_spec = _parse_browser_command(command_template)
            action = command_spec["action"]
            if action == "screenshot":
                screenshot = browser.screenshot(
                    command_spec["url"],
                    filename=command_spec.get("filename"),
                )
                payload = {
                    "outcome": "done",
                    "summary": f"browser screenshot captured: {screenshot.path}",
                    "browser_action": "screenshot",
                    "artifact_path": screenshot.path,
                    "content_digest": screenshot.content_digest,
                    "changed_paths": [],
                }
            else:
                dom = browser.get_dom(command_spec["url"])
                artifact_path = str(work_path / ".run-logs" / "browser" / "dom_extract.json")
                payload = {
                    "outcome": "done",
                    "summary": f"browser DOM extracted: {dom.title or dom.url}",
                    "browser_action": "get_dom",
                    "artifact_path": artifact_path,
                    "content_digest": "",
                    "changed_paths": [],
                }
            elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
            return ExecutionResult(
                success=True,
                summary=payload["summary"],
                command_digest=command_template,
                elapsed_ms=elapsed_ms,
                result_payload_json=payload,
            )
        except Exception as exc:
            elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
            payload = {
                "outcome": "blocked",
                "summary": f"browser executor failed: {exc}",
                "reason_code": "browser-executor-error",
                "decision_required": False,
            }
            return ExecutionResult(
                success=False,
                summary=payload["summary"],
                command_digest=command_template,
                elapsed_ms=elapsed_ms,
                blocked_reason="browser-executor-error",
                result_payload_json=payload,
            )

    return _executor


def build_task_executor(
    *,
    command_template: str,
    workdir: Path,
    dsn: str | None = None,
) -> ExecutorAdapter:
    router = None
    if dsn:
        try:
            from .executor_router import ExecutorRouter

            router = ExecutorRouter(
                dsn,
                default_executor_name=os.environ.get(
                    "TASKPLANE_DEFAULT_EXECUTOR"
                ),
            )
        except Exception:
            router = None

    shell_executor = build_shell_executor(
        command_template=command_template,
        workdir=workdir,
    )
    try:
        controlled_executor = build_controlled_executor(
            workdir=workdir,
            command_template=command_template,
        )
    except TypeError:
        controlled_executor = build_controlled_executor(workdir=workdir)
    browser_executor = build_browser_executor(
        command_template=command_template,
        workdir=workdir,
    )
    intelligent_executor: ExecutorAdapter | None = None
    if llm_executor_enabled(command_template=command_template):
        intelligent_executor = build_intelligent_executor(
            command_template=command_template,
            workdir=workdir,
        )

    def _executor(
        work_item: WorkItem,
        workspace_path: Path | None = None,
        execution_context: ExecutionContext | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> ExecutionResult:
        force_shell_executor = os.environ.get(
            "TASKPLANE_FORCE_SHELL_EXECUTOR", ""
        ).strip().lower() in {"1", "true", "yes"}
        if force_shell_executor or _should_prefer_explicit_shell_command(
            command_template
        ):
            return shell_executor(
                work_item,
                workspace_path=workspace_path,
                execution_context=execution_context,
                heartbeat=heartbeat,
            )
        if router is not None:
            try:
                executor_config = router.select_executor(
                    work_item.task_type or "",
                    work_item=work_item,
                    execution_context=execution_context,
                )
            except TypeError:
                executor_config = router.select_executor(work_item.task_type or "")
            if executor_config is not None:
                if dsn:
                    _log_executor_selection(
                        dsn=dsn,
                        work_item=work_item,
                        executor_name=executor_config.executor_name,
                        executor_type=executor_config.executor_type,
                        task_type=work_item.task_type or "",
                    )
                executor_type = str(executor_config.executor_type or "").strip().lower()
                if executor_type in {"llm_native", "agent_cli"}:
                    if intelligent_executor is not None:
                        return intelligent_executor(
                            work_item,
                            workspace_path=workspace_path,
                            execution_context=execution_context,
                            heartbeat=heartbeat,
                        )
                    return controlled_executor(
                        work_item,
                        workspace_path=workspace_path,
                        execution_context=execution_context,
                        heartbeat=heartbeat,
                    )
                if executor_type == "browser":
                    return browser_executor(
                        work_item,
                        workspace_path=workspace_path,
                        execution_context=execution_context,
                        heartbeat=heartbeat,
                    )
                if executor_type in {"shell", "test_runner"}:
                    return shell_executor(
                        work_item,
                        workspace_path=workspace_path,
                        execution_context=execution_context,
                        heartbeat=heartbeat,
                    )
        if intelligent_executor is not None and _should_use_controlled_executor(
            work_item=work_item,
            execution_context=execution_context,
        ):
            return intelligent_executor(
                work_item,
                workspace_path=workspace_path,
                execution_context=execution_context,
                heartbeat=heartbeat,
            )
        if _should_use_controlled_executor(
            work_item=work_item,
            execution_context=execution_context,
        ):
            return controlled_executor(
                work_item,
                workspace_path=workspace_path,
                execution_context=execution_context,
                heartbeat=heartbeat,
            )
        return shell_executor(
            work_item,
            workspace_path=workspace_path,
            execution_context=execution_context,
            heartbeat=heartbeat,
        )

    return _executor


def _log_executor_selection(
    *,
    dsn: str,
    work_item: WorkItem,
    executor_name: str,
    executor_type: str,
    task_type: str,
) -> None:
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO event_log (event_type, work_id, actor, detail)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        "executor_selected",
                        work_item.id,
                        executor_name,
                        json.dumps(
                            {
                                "executor_name": executor_name,
                                "executor_type": executor_type,
                                "task_type": task_type,
                                "lane": work_item.lane,
                                "wave": work_item.wave,
                            }
                        ),
                    ),
                )
        return None
    except Exception:
        return None


def _run_command(
    *,
    command_template: str,
    work_item: WorkItem,
    workdir: Path,
    execution_context: ExecutionContext | None = None,
    heartbeat: Callable[[], None] | None = None,
) -> tuple[subprocess.CompletedProcess[str], int]:
    env = os.environ.copy()
    env.update(
        {
            "TASKPLANE_WORK_ID": work_item.id,
            "TASKPLANE_WORK_TITLE": work_item.title,
            "TASKPLANE_WORK_LANE": work_item.lane,
            "TASKPLANE_WORK_WAVE": work_item.wave,
            "TASKPLANE_PROJECT_DIR": str(workdir),
        }
    )
    if execution_context is not None:
        env["TASKPLANE_EXECUTION_CONTEXT_JSON"] = json.dumps(
            {
                "work_id": execution_context.work_id,
                "title": execution_context.title,
                "lane": execution_context.lane,
                "wave": execution_context.wave,
                "repo": execution_context.repo,
                "source_issue_number": execution_context.source_issue_number,
                "canonical_story_issue_number": execution_context.canonical_story_issue_number,
                "story_issue_numbers": list(execution_context.story_issue_numbers),
                "planned_paths": list(execution_context.planned_paths),
                "workspace_path": execution_context.workspace_path,
                "project_dir": execution_context.project_dir,
                "resume_context": execution_context.resume_context,
            }
        )
    started_at = time.perf_counter()
    process = subprocess.Popen(
        command_template,
        shell=True,
        cwd=str(workdir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    while True:
        try:
            stdout, stderr = process.communicate(timeout=0.1)
            break
        except subprocess.TimeoutExpired:
            if heartbeat is not None:
                heartbeat()
    elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    completed = subprocess.CompletedProcess(
        args=command_template,
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
    )
    return completed, elapsed_ms


def _run_callable_executor(
    runner: Callable[[], int],
    *,
    heartbeat: Callable[[], None] | None = None,
) -> tuple[subprocess.CompletedProcess[str], int]:
    started_at = time.perf_counter()
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    returncode: int | None = None
    raised: BaseException | None = None

    def _run() -> None:
        nonlocal returncode, raised
        try:
            with (
                contextlib.redirect_stdout(stdout_buffer),
                contextlib.redirect_stderr(stderr_buffer),
            ):
                returncode = runner()
        except BaseException as exc:
            raised = exc

    thread = threading.Thread(target=_run)
    thread.start()
    while thread.is_alive():
        thread.join(timeout=0.1)
        if thread.is_alive() and heartbeat is not None:
            heartbeat()
    if raised is not None:
        raise raised
    if returncode is None:
        returncode = 1
    elapsed_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    completed = subprocess.CompletedProcess(
        args="controlled-task-executor",
        returncode=returncode,
        stdout=stdout_buffer.getvalue(),
        stderr=stderr_buffer.getvalue(),
    )
    return completed, elapsed_ms


def _load_required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _load_resume_context(execution_context: ExecutionContext | None) -> str:
    if execution_context is None:
        return ""
    return str(execution_context.resume_context or "").strip()


def _should_use_controlled_executor(
    *, work_item: WorkItem, execution_context: ExecutionContext | None
) -> bool:
    if work_item.task_type:
        return work_item.task_type == "core_path"
    return _is_implementation_title(work_item.title)


def _should_prefer_explicit_shell_command(command_template: str) -> bool:
    normalized = command_template.strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    if lowered.startswith("llm://"):
        return False
    controlled_modules = {
        "python3 -m taskplane.opencode_task_executor",
        "python -m taskplane.opencode_task_executor",
        "python3 -m taskplane.codex_task_executor",
        "python -m taskplane.codex_task_executor",
    }
    if lowered in controlled_modules:
        return False
    return " -m taskplane." in lowered


def _should_use_bounded_mode(
    *, work_item: WorkItem, execution_context: ExecutionContext | None
) -> bool:
    if os.environ.get("TASKPLANE_BOUNDED_EXECUTOR", "").strip():
        return os.environ.get("TASKPLANE_BOUNDED_EXECUTOR", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
    if execution_context is not None and execution_context.planned_paths:
        return True
    return _should_use_controlled_executor(
        work_item=work_item,
        execution_context=execution_context,
    )


def _is_implementation_title(title: str) -> bool:
    return "-IMPL]" in title.upper()


def _build_output_digest(
    completed: subprocess.CompletedProcess[str],
    *,
    strip_execution_marker: bool = False,
) -> tuple[str, str, str]:
    stdout_digest = (completed.stdout or "").strip()
    stderr_digest = (completed.stderr or "").strip()
    if strip_execution_marker:
        stdout_digest = _strip_execution_result_markers(stdout_digest)
        stderr_digest = _strip_execution_result_markers(stderr_digest)
    output_parts = []
    if stdout_digest:
        output_parts.append(stdout_digest)
    if stderr_digest:
        output_parts.append(stderr_digest)
    if not output_parts:
        output_parts.append(f"exit={completed.returncode}")
    return (
        stdout_digest,
        stderr_digest,
        "\n".join(part for part in output_parts if part),
    )


def _extract_execution_result_metadata(
    completed: subprocess.CompletedProcess[str],
) -> dict:
    parsed = parse_executor_output(
        completed.stdout or "",
        completed.stderr or "",
        completed.returncode,
    )
    return parsed.payload if isinstance(parsed.payload, dict) else {}


def _strip_execution_result_markers(output: str) -> str:
    lines = [
        line
        for line in output.splitlines()
        if not any(
            line.startswith(marker)
            for marker in (
                EXECUTION_RESULT_MARKER,
                EXECUTION_CHECKPOINT_MARKER,
                EXECUTION_WAIT_MARKER,
                EXECUTION_RETRY_INTENT_MARKER,
            )
        )
    ]
    return "\n".join(lines).strip()


def _parse_browser_command(command_template: str) -> dict[str, str]:
    raw = command_template.strip()
    if not raw:
        raise ValueError("browser executor command is empty")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"action": "screenshot", "url": raw}
    if not isinstance(parsed, dict):
        raise ValueError("browser executor command must decode to an object")
    action = str(parsed.get("action") or "screenshot").strip().lower()
    if action not in {"screenshot", "get_dom"}:
        raise ValueError(f"unsupported browser action: {action}")
    url = str(parsed.get("url") or "").strip()
    if not url:
        raise ValueError("browser executor requires a url")
    result = {"action": action, "url": url}
    filename = str(parsed.get("filename") or "").strip()
    if filename:
        result["filename"] = filename
    return result
