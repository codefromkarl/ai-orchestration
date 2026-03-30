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

from .models import ExecutionContext, VerificationEvidence, WorkItem
from .execution_protocol import EXECUTION_RESULT_MARKER
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


def build_controlled_executor(*, workdir: Path) -> ExecutorAdapter:
    def _executor(
        work_item: WorkItem,
        workspace_path: Path | None = None,
        execution_context: ExecutionContext | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> ExecutionResult:
        effective_workdir = workspace_path or workdir
        previous_project_dir = os.environ.get("STARDRIFTER_PROJECT_DIR")
        os.environ["STARDRIFTER_PROJECT_DIR"] = str(effective_workdir)
        try:
            from .opencode_task_executor import run_controlled_opencode_task

            completed, elapsed_ms = _run_callable_executor(
                lambda: run_controlled_opencode_task(
                    work_id=work_item.id,
                    dsn=_load_required_env("STARDRIFTER_ORCHESTRATION_DSN"),
                    project_dir=effective_workdir,
                    bounded_mode=_should_use_bounded_mode(
                        work_item=work_item,
                        execution_context=execution_context,
                    ),
                ),
                heartbeat=heartbeat,
            )
        finally:
            if previous_project_dir is None:
                os.environ.pop("STARDRIFTER_PROJECT_DIR", None)
            else:
                os.environ["STARDRIFTER_PROJECT_DIR"] = previous_project_dir
        metadata = _extract_execution_result_metadata(completed)
        stdout_digest, stderr_digest, output = _build_output_digest(
            completed,
            strip_execution_marker=True,
        )
        return ExecutionResult(
            success=completed.returncode == 0,
            summary=output,
            command_digest="python -m stardrifter_orchestration_mvp.opencode_task_executor",
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


def build_task_executor(
    *,
    command_template: str,
    workdir: Path,
) -> ExecutorAdapter:
    shell_executor = build_shell_executor(
        command_template=command_template,
        workdir=workdir,
    )
    controlled_executor = build_controlled_executor(workdir=workdir)

    def _executor(
        work_item: WorkItem,
        workspace_path: Path | None = None,
        execution_context: ExecutionContext | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> ExecutionResult:
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
            "STARDRIFTER_WORK_ID": work_item.id,
            "STARDRIFTER_WORK_TITLE": work_item.title,
            "STARDRIFTER_WORK_LANE": work_item.lane,
            "STARDRIFTER_WORK_WAVE": work_item.wave,
            "STARDRIFTER_PROJECT_DIR": str(workdir),
        }
    )
    if execution_context is not None:
        env["STARDRIFTER_EXECUTION_CONTEXT_JSON"] = json.dumps(
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
        args="controlled-opencode-task-executor",
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


def _should_use_controlled_executor(
    *, work_item: WorkItem, execution_context: ExecutionContext | None
) -> bool:
    if work_item.task_type:
        return work_item.task_type == "core_path"
    return _is_implementation_title(work_item.title)


def _should_use_bounded_mode(
    *, work_item: WorkItem, execution_context: ExecutionContext | None
) -> bool:
    if os.environ.get("STARDRIFTER_BOUNDED_EXECUTOR", "").strip():
        return os.environ.get("STARDRIFTER_BOUNDED_EXECUTOR", "").strip().lower() in {
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
    candidates: list[str] = []
    for stream in ((completed.stdout or ""), (completed.stderr or "")):
        for line in stream.splitlines():
            if line.startswith(EXECUTION_RESULT_MARKER):
                candidates.append(line[len(EXECUTION_RESULT_MARKER) :].strip())
    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _strip_execution_result_markers(output: str) -> str:
    lines = [
        line
        for line in output.splitlines()
        if not line.startswith(EXECUTION_RESULT_MARKER)
    ]
    return "\n".join(lines).strip()
