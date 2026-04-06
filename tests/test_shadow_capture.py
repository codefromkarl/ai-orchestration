from taskplane.artifact_store import ArtifactRecord
from taskplane.event_log import InMemoryEventLogRecorder
from taskplane.models import ExecutionRun, WorkItem
from taskplane.repository import InMemoryControlPlaneRepository
from taskplane.shadow_capture import ShadowCommandResult, capture_shadow_command


class FakeArtifactStore:
    def __init__(self) -> None:
        self.records: list[ArtifactRecord] = []

    def store_and_record(
        self,
        *,
        work_id: str,
        artifact_type: str,
        content,
        run_id=None,
        session_id=None,
        metadata=None,
        mime_type=None,
        sequence: int = 1,
    ) -> ArtifactRecord:
        ext_by_type = {
            "task_summary": "json",
            "stdout": "txt",
            "stderr": "txt",
            "diff_snapshot": "diff",
            "custom": "txt",
        }
        ext = ext_by_type.get(artifact_type, "bin")
        record = ArtifactRecord(
            id=len(self.records) + 1,
            work_id=work_id,
            run_id=run_id,
            session_id=session_id,
            artifact_type=artifact_type,
            artifact_key=f"{work_id}/{artifact_type}/{sequence:02d}.{ext}",
            storage_path=f"/tmp/{work_id}/{artifact_type}/{sequence:02d}.{ext}",
            content_digest=f"digest-{len(self.records) + 1}",
            content_size_bytes=len(content if isinstance(content, bytes) else str(content).encode("utf-8")),
            mime_type=mime_type or "text/plain",
            metadata=metadata or {},
            created_at="2026-04-04T00:00:00+00:00",
        )
        self.records.append(record)
        return record


class FakeContextStore:
    def __init__(self) -> None:
        self.turns: list[tuple[str, str, str, dict | None]] = []

    def save_turn(self, work_id: str, role: str, content: str, metadata=None) -> str:
        self.turns.append((work_id, role, content, metadata))
        return f"turn-{len(self.turns)}"


def test_capture_shadow_command_creates_and_finalizes_done_task():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )
    artifact_store = FakeArtifactStore()
    event_recorder = InMemoryEventLogRecorder()

    result = capture_shadow_command(
        repository=repository,
        repo="codefromkarl/stardrifter",
        title="shadow captured task",
        workdir="/tmp/project",
        command=["codex", "exec", "fix bug"],
        prompt="fix bug and add tests",
        assistant_summary="implemented fix and tests passed",
        transcript_text="assistant transcript",
        transcript_path="/tmp/project/transcript.md",
        worker_name="shadow-wrap:codex",
        artifact_store=artifact_store,
        context_store=FakeContextStore(),
        event_recorder=event_recorder,
        command_runner=lambda **kwargs: ShadowCommandResult(
            returncode=0,
            stdout="done",
            stderr="",
            elapsed_ms=1200,
        ),
        diff_collector=lambda **kwargs: "src/app.py\n\n 1 file changed, 3 insertions(+)",
        work_id_factory=lambda: "adhoc-1",
    )

    assert result.work_id == "adhoc-1"
    assert result.status == "done"
    assert repository.get_work_item("adhoc-1") == WorkItem(
        id="adhoc-1",
        repo="codefromkarl/stardrifter",
        title="shadow captured task",
        lane="general",
        wave="Direct",
        status="done",
        task_type="core_path",
        blocking_mode="soft",
    )
    assert repository.execution_runs == [
        ExecutionRun(
            work_id="adhoc-1",
            worker_name="shadow-wrap:codex",
            status="done",
            branch_name="shadow/adhoc-1",
            command_digest=result.command_digest,
            summary="shadow command completed successfully",
            exit_code=0,
            elapsed_ms=1200,
            stdout_digest=result.stdout_digest,
            stderr_digest=result.stderr_digest,
            result_payload_json={
                "entry_mode": "shadow_wrap",
                "executor": "codex",
                "workdir": "/tmp/project",
                "prompt_present": True,
                "artifacts": [
                    "adhoc-1/task_summary/01.json",
                    "adhoc-1/custom/01.txt",
                    "adhoc-1/custom/02.txt",
                    "adhoc-1/stdout/01.txt",
                    "adhoc-1/diff_snapshot/01.diff",
                ],
                "conversation_captured": True,
            },
        )
    ]
    assert [record.artifact_type for record in artifact_store.records] == [
        "task_summary",
        "custom",
        "custom",
        "stdout",
        "diff_snapshot",
    ]
    assert [event.action for event in event_recorder.events] == [
        "started",
        "artifact_created",
        "artifact_created",
        "artifact_created",
        "artifact_created",
        "artifact_created",
        "completed",
    ]
    assert repository.list_active_work_claims() == []


def test_capture_shadow_command_persists_prompt_and_assistant_turns():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )
    artifact_store = FakeArtifactStore()
    context_store = FakeContextStore()

    capture_shadow_command(
        repository=repository,
        repo="codefromkarl/stardrifter",
        title="shadow captured task",
        workdir="/tmp/project",
        command=["codex", "exec", "fix bug"],
        prompt="fix bug and add tests",
        assistant_summary="implemented fix and tests passed",
        transcript_text="assistant transcript",
        transcript_path="/tmp/project/transcript.md",
        worker_name="shadow-wrap:codex",
        artifact_store=artifact_store,
        context_store=context_store,
        event_recorder=InMemoryEventLogRecorder(),
        command_runner=lambda **kwargs: ShadowCommandResult(
            returncode=0,
            stdout="done",
            stderr="",
            elapsed_ms=1200,
        ),
        diff_collector=lambda **kwargs: "",
        work_id_factory=lambda: "adhoc-ctx",
    )

    assert context_store.turns == [
        (
            "adhoc-ctx",
            "user",
            "fix bug and add tests",
            {"source": "shadow_wrap_prompt"},
        ),
        (
            "adhoc-ctx",
            "assistant",
            "implemented fix and tests passed",
            {
                "source": "shadow_wrap_summary",
                "transcript_path": "/tmp/project/transcript.md",
            },
        ),
    ]


def test_capture_shadow_command_derives_assistant_summary_from_transcript():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )
    context_store = FakeContextStore()

    capture_shadow_command(
        repository=repository,
        repo="codefromkarl/stardrifter",
        title="shadow captured task",
        workdir="/tmp/project",
        command=["codex", "exec", "fix bug"],
        prompt="fix bug and add tests",
        assistant_summary=None,
        transcript_text=(
            "User: fix bug and add tests\n"
            "Assistant: inspected login flow and identified stale state handling.\n"
            "\n"
            "Assistant: implemented the fix and added regression tests.\n"
            "Assistant: all relevant tests passed.\n"
        ),
        transcript_path="/tmp/project/transcript.md",
        worker_name="shadow-wrap:codex",
        artifact_store=FakeArtifactStore(),
        context_store=context_store,
        event_recorder=InMemoryEventLogRecorder(),
        command_runner=lambda **kwargs: ShadowCommandResult(
            returncode=0,
            stdout="done",
            stderr="",
            elapsed_ms=1200,
        ),
        diff_collector=lambda **kwargs: "",
        work_id_factory=lambda: "adhoc-auto-summary",
    )

    assert context_store.turns == [
        (
            "adhoc-auto-summary",
            "user",
            "fix bug and add tests",
            {"source": "shadow_wrap_prompt"},
        ),
        (
            "adhoc-auto-summary",
            "assistant",
            "implemented the fix and added regression tests. all relevant tests passed.",
            {
                "source": "shadow_wrap_summary",
                "transcript_path": "/tmp/project/transcript.md",
            },
        ),
    ]


def test_capture_shadow_command_marks_task_blocked_on_failure():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )
    artifact_store = FakeArtifactStore()
    event_recorder = InMemoryEventLogRecorder()

    result = capture_shadow_command(
        repository=repository,
        repo="codefromkarl/stardrifter",
        title="shadow captured task",
        workdir="/tmp/project",
        command=["codex", "exec", "fix bug"],
        prompt=None,
        worker_name="shadow-wrap:codex",
        artifact_store=artifact_store,
        context_store=FakeContextStore(),
        event_recorder=event_recorder,
        command_runner=lambda **kwargs: ShadowCommandResult(
            returncode=17,
            stdout="",
            stderr="failed",
            elapsed_ms=800,
        ),
        diff_collector=lambda **kwargs: "",
        work_id_factory=lambda: "adhoc-2",
    )

    assert result.status == "blocked"
    assert repository.get_work_item("adhoc-2").status == "blocked"
    assert repository.get_work_item("adhoc-2").blocked_reason == "shadow command exited with code 17"
    assert [record.artifact_type for record in artifact_store.records] == [
        "task_summary",
        "stderr",
    ]
    assert event_recorder.events[-1].action == "failed"
