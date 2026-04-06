from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .taxonomy import DEFAULT_SCHEMA_VERSION


@dataclass(frozen=True)
class EvalExportEndpoint:
    path: str
    method: str = "GET"
    description: str = ""
    cursor_param: str | None = None


@dataclass(frozen=True)
class EvalExportEnvelope:
    data: list[dict[str, Any]]
    schema_version: str = DEFAULT_SCHEMA_VERSION
    emitted_at: str | None = None
    next_cursor: str | None = None
    has_more: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "emitted_at": self.emitted_at,
            "data": self.data,
            "page": {
                "next_cursor": self.next_cursor,
                "has_more": self.has_more,
            },
        }


@dataclass(frozen=True)
class WorkSnapshotExport:
    work_id: str
    repo: str
    title: str
    status: str
    lane: str
    wave: str
    schema_version: str = DEFAULT_SCHEMA_VERSION
    kind: str = "work_snapshot"
    emitted_at: str | None = None
    task_type: str | None = None
    blocking_mode: str | None = None
    attempt_count: int = 0
    last_failure_reason: str | None = None
    next_eligible_at: str | None = None
    decision_required: bool = False
    blocked_reason: str | None = None
    source_issue_number: int | None = None
    canonical_story_issue_number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionAttemptExport:
    run_id: int
    work_id: str
    attempt_number: int
    worker_name: str
    status: str
    schema_version: str = DEFAULT_SCHEMA_VERSION
    kind: str = "execution_attempt"
    emitted_at: str | None = None
    executor_name: str | None = None
    executor_profile: str | None = None
    session_id: str | None = None
    branch_name: str | None = None
    workspace_path: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_ms: int | None = None
    exit_code: int | None = None
    command_digest: str | None = None
    stdout_digest: str = ""
    stderr_digest: str = ""
    result_payload: dict[str, Any] | None = None
    partial_artifacts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationResultExport:
    verification_id: str
    run_id: int
    work_id: str
    attempt_number: int
    verifier_name: str
    check_type: str
    command: str
    passed: bool
    schema_version: str = DEFAULT_SCHEMA_VERSION
    kind: str = "verification_result"
    emitted_at: str | None = None
    exit_code: int | None = None
    elapsed_ms: int | None = None
    stdout_digest: str = ""
    stderr_digest: str = ""
    output_digest: str = ""
    classification: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
