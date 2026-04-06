from __future__ import annotations

import hashlib
import json
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .artifact_store import ArtifactStore
from .context_store import ContextStore
from .models import ExecutionRun


@dataclass(frozen=True)
class ShadowCommandResult:
    returncode: int
    stdout: str
    stderr: str
    elapsed_ms: int


@dataclass(frozen=True)
class ShadowCaptureEvent:
    event_type: str
    action: str
    work_id: str
    actor: str
    detail: dict[str, Any]


@dataclass(frozen=True)
class ShadowCaptureResult:
    work_id: str
    status: str
    command_digest: str
    stdout_digest: str
    stderr_digest: str


class ShadowCommandRunner(Protocol):
    def __call__(self, *, command: list[str], workdir: str) -> ShadowCommandResult: ...


class DiffCollector(Protocol):
    def __call__(self, *, workdir: str, max_chars: int) -> str: ...


def capture_shadow_command(
    *,
    repository: Any,
    repo: str,
    title: str,
    workdir: str,
    command: list[str],
    prompt: str | None,
    assistant_summary: str | None = None,
    transcript_text: str | None = None,
    transcript_path: str | None = None,
    worker_name: str,
    dsn: str | None = None,
    artifact_store: ArtifactStore | Any | None = None,
    context_store: ContextStore | Any | None = None,
    event_recorder: Any | None = None,
    command_runner: ShadowCommandRunner | None = None,
    diff_collector: DiffCollector | None = None,
    work_id_factory=None,
) -> ShadowCaptureResult:
    workdir_path = str(Path(workdir).resolve())
    work_id_factory = work_id_factory or _default_work_id_factory
    command_runner = command_runner or _default_command_runner
    diff_collector = diff_collector or _default_diff_collector
    artifact_store = artifact_store or (ArtifactStore(dsn=dsn) if dsn else None)
    context_store = context_store or (ContextStore(dsn=dsn) if dsn else None)

    work_id = work_id_factory()
    branch_name = f"shadow/{work_id}"
    created = repository.create_ad_hoc_work_item(
        work_id=work_id,
        repo=repo,
        title=title,
        lane="general",
        wave="Direct",
        task_type="core_path",
        blocking_mode="soft",
        planned_paths=(),
        metadata={
            "entry_mode": "shadow_wrap",
            "executor": _infer_executor_name(worker_name),
            "workdir": workdir_path,
        },
    )
    claimed = repository.claim_ready_work_item(
        work_id,
        worker_name=worker_name,
        workspace_path=workdir_path,
        branch_name=branch_name,
        claimed_paths=(),
    )
    if claimed is None:
        raise RuntimeError(f"failed to claim shadow work item: {work_id}")

    _record_event(
        dsn=dsn,
        event_recorder=event_recorder,
        event_type="task_started",
        action="started",
        work_id=work_id,
        actor=worker_name,
        detail={"repo": repo, "workdir": workdir_path},
    )

    command_result = command_runner(command=command, workdir=workdir_path)
    command_digest = _sha256_text(" ".join(command))
    stdout_digest = _sha256_text(command_result.stdout)
    stderr_digest = _sha256_text(command_result.stderr)

    artifact_keys: list[str] = []
    task_summary_payload = {
        "entry_mode": "shadow_wrap",
        "repo": repo,
        "title": title,
        "workdir": workdir_path,
        "executor": _infer_executor_name(worker_name),
        "command": command,
        "prompt_present": bool(prompt),
        "returncode": command_result.returncode,
        "elapsed_ms": command_result.elapsed_ms,
    }
    summary_record = _store_artifact(
        artifact_store=artifact_store,
        dsn=dsn,
        event_recorder=event_recorder,
        work_id=work_id,
        actor=worker_name,
        artifact_type="task_summary",
        content=json.dumps(task_summary_payload, ensure_ascii=False, indent=2),
        metadata={"summary": title},
        mime_type="application/json",
    )
    if summary_record is not None:
        artifact_keys.append(summary_record.artifact_key)

    if prompt:
        prompt_record = _store_artifact(
            artifact_store=artifact_store,
            dsn=dsn,
            event_recorder=event_recorder,
            work_id=work_id,
            actor=worker_name,
            artifact_type="custom",
            content=prompt,
            metadata={"summary": "shadow wrap prompt", "kind": "prompt"},
            mime_type="text/plain",
            sequence=1,
        )
        if prompt_record is not None:
            artifact_keys.append(prompt_record.artifact_key)

    if transcript_text:
        transcript_record = _store_artifact(
            artifact_store=artifact_store,
            dsn=dsn,
            event_recorder=event_recorder,
            work_id=work_id,
            actor=worker_name,
            artifact_type="custom",
            content=transcript_text,
            metadata={
                "summary": "shadow wrap transcript",
                "kind": "transcript",
                "source_path": transcript_path,
            },
            mime_type="text/plain",
            sequence=2,
        )
        if transcript_record is not None:
            artifact_keys.append(transcript_record.artifact_key)

    if command_result.stdout:
        stdout_record = _store_artifact(
            artifact_store=artifact_store,
            dsn=dsn,
            event_recorder=event_recorder,
            work_id=work_id,
            actor=worker_name,
            artifact_type="stdout",
            content=command_result.stdout,
            metadata={"summary": "shadow command stdout"},
            mime_type="text/plain",
        )
        if stdout_record is not None:
            artifact_keys.append(stdout_record.artifact_key)
    if command_result.stderr:
        stderr_record = _store_artifact(
            artifact_store=artifact_store,
            dsn=dsn,
            event_recorder=event_recorder,
            work_id=work_id,
            actor=worker_name,
            artifact_type="stderr",
            content=command_result.stderr,
            metadata={"summary": "shadow command stderr"},
            mime_type="text/plain",
        )
        if stderr_record is not None:
            artifact_keys.append(stderr_record.artifact_key)

    diff_snapshot = diff_collector(workdir=workdir_path, max_chars=4000).strip()
    if diff_snapshot:
        diff_record = _store_artifact(
            artifact_store=artifact_store,
            dsn=dsn,
            event_recorder=event_recorder,
            work_id=work_id,
            actor=worker_name,
            artifact_type="diff_snapshot",
            content=diff_snapshot,
            metadata={"summary": "git diff snapshot"},
            mime_type="text/x-diff",
            sequence=1,
        )
        if diff_record is not None:
            artifact_keys.append(diff_record.artifact_key)

    effective_assistant_summary = assistant_summary or _derive_assistant_summary(
        transcript_text
    )
    conversation_captured = False
    if context_store is not None:
        if prompt:
            context_store.save_turn(
                work_id,
                "user",
                prompt,
                metadata={"source": "shadow_wrap_prompt"},
            )
            conversation_captured = True
        if effective_assistant_summary:
            context_store.save_turn(
                work_id,
                "assistant",
                effective_assistant_summary,
                metadata={
                    "source": "shadow_wrap_summary",
                    "transcript_path": transcript_path,
                },
            )
            conversation_captured = True

    status = "done" if command_result.returncode == 0 else "blocked"
    blocked_reason = None
    summary = "shadow command completed successfully"
    if status != "done":
        blocked_reason = f"shadow command exited with code {command_result.returncode}"
        summary = blocked_reason

    repository.finalize_work_attempt(
        work_id=work_id,
        status=status,
        blocked_reason=blocked_reason,
        last_failure_reason=None if status == "done" else "shadow_wrap_failed",
        execution_run=ExecutionRun(
            work_id=work_id,
            worker_name=worker_name,
            status=status,
            branch_name=branch_name,
            command_digest=command_digest,
            summary=summary,
            exit_code=command_result.returncode,
            elapsed_ms=command_result.elapsed_ms,
            stdout_digest=stdout_digest,
            stderr_digest=stderr_digest,
            result_payload_json={
                "entry_mode": "shadow_wrap",
                "executor": _infer_executor_name(worker_name),
                "workdir": workdir_path,
                "prompt_present": bool(prompt),
                "artifacts": artifact_keys,
                "conversation_captured": conversation_captured,
            },
        ),
    )
    repository.delete_work_claim(work_id)

    _record_event(
        dsn=dsn,
        event_recorder=event_recorder,
        event_type="task_completed" if status == "done" else "task_failed",
        action="completed" if status == "done" else "failed",
        work_id=work_id,
        actor=worker_name,
        detail={"status": status, "returncode": command_result.returncode},
    )

    return ShadowCaptureResult(
        work_id=work_id,
        status=status,
        command_digest=command_digest,
        stdout_digest=stdout_digest,
        stderr_digest=stderr_digest,
    )


def _store_artifact(
    *,
    artifact_store: ArtifactStore | Any | None,
    dsn: str | None,
    event_recorder: Any | None,
    work_id: str,
    actor: str,
    artifact_type: str,
    content: str,
    metadata: dict[str, Any],
    mime_type: str,
    sequence: int = 1,
):
    if artifact_store is None:
        return None
    record = artifact_store.store_and_record(
        work_id=work_id,
        artifact_type=artifact_type,
        content=content,
        metadata=metadata,
        mime_type=mime_type,
        sequence=sequence,
    )
    _record_event(
        dsn=dsn,
        event_recorder=event_recorder,
        event_type="artifact_created",
        action="artifact_created",
        work_id=work_id,
        actor=actor,
        detail={
            "artifact_type": artifact_type,
            "artifact_key": record.artifact_key,
        },
    )
    return record


def _record_event(
    *,
    dsn: str | None,
    event_recorder: Any | None,
    event_type: str,
    action: str,
    work_id: str,
    actor: str,
    detail: dict[str, Any],
) -> None:
    if event_recorder is not None:
        event_recorder.record(
            ShadowCaptureEvent(
                event_type=event_type,
                action=action,
                work_id=work_id,
                actor=actor,
                detail=detail,
            )
        )
    if dsn:
        try:
            import psycopg
            from psycopg.rows import dict_row

            with psycopg.connect(dsn, row_factory=dict_row) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO event_log (event_type, work_id, actor, detail)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (event_type, work_id, actor, detail),
                    )
        except Exception:
            pass


def _infer_executor_name(worker_name: str) -> str:
    if ":" in worker_name:
        return worker_name.split(":", 1)[1]
    return worker_name


def _default_work_id_factory() -> str:
    return f"adhoc-{int(time.time())}-{uuid.uuid4().hex[:8]}"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _default_command_runner(
    *, command: list[str], workdir: str
) -> ShadowCommandResult:
    started_at = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    return ShadowCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        elapsed_ms=elapsed_ms,
    )


def _default_diff_collector(*, workdir: str, max_chars: int) -> str:
    commands = [
        ["git", "-C", workdir, "diff", "--name-only"],
        ["git", "-C", workdir, "diff", "--stat"],
    ]
    parts: list[str] = []
    for command in commands:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        output = (completed.stdout or "").strip()
        if output:
            parts.append(output)
    combined = "\n\n".join(parts)
    if len(combined) <= max_chars:
        return combined
    if max_chars <= 3:
        return "." * max_chars
    return combined[: max_chars - 3].rstrip() + "..."


def _derive_assistant_summary(
    transcript_text: str | None,
    *,
    max_chars: int = 280,
) -> str | None:
    if not transcript_text:
        return None

    assistant_lines: list[str] = []
    for raw_line in transcript_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("assistant:"):
            assistant_lines.append(line.split(":", 1)[1].strip())

    if not assistant_lines:
        return None

    summary_parts = assistant_lines[-2:] if len(assistant_lines) >= 2 else assistant_lines
    summary = " ".join(part for part in summary_parts if part).strip()
    if not summary:
        return None
    if len(summary) <= max_chars:
        return summary
    if max_chars <= 3:
        return "." * max_chars
    return summary[: max_chars - 3].rstrip() + "..."
