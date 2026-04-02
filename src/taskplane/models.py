from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any
from typing import Literal


WorkStatus = Literal[
    "pending",
    "ready",
    "in_progress",
    "verifying",
    "awaiting_approval",
    "blocked",
    "done",
]
Complexity = Literal["low", "medium", "high"]
TargetType = Literal["file", "dir", "doc", "test"]
TaskType = Literal["core_path", "cross_cutting", "documentation", "governance"]
BlockingMode = Literal["hard", "soft"]
ProgramStatus = Literal["proposed", "approved", "completed", "archived"]
ExecutionStatus = Literal[
    "backlog",
    "planned",
    "decomposing",
    "active",
    "gated",
    "done",
    "blocked",
    "needs_story_refinement",
]
EpicRuntimeStatus = Literal["backlog", "active", "awaiting_operator", "done"]
EPIC_RUNTIME_STATUSES: tuple[EpicRuntimeStatus, ...] = (
    "backlog",
    "active",
    "awaiting_operator",
    "done",
)


@dataclass(frozen=True)
class WorkItem:
    id: str
    title: str
    lane: str
    wave: str
    status: WorkStatus
    repo: str | None = None
    complexity: Complexity = "low"
    attempt_count: int = 0
    last_failure_reason: str | None = None
    next_eligible_at: str | None = None
    source_issue_number: int | None = None
    story_issue_numbers: tuple[int, ...] = ()
    canonical_story_issue_number: int | None = None
    related_story_issue_numbers: tuple[int, ...] = ()
    task_type: TaskType = "core_path"
    blocking_mode: BlockingMode = "hard"
    planned_paths: tuple[str, ...] = ()
    blocked_reason: str | None = None
    decision_required: bool = False


@dataclass(frozen=True)
class WorkDependency:
    work_id: str
    depends_on_work_id: str


@dataclass(frozen=True)
class WorkTarget:
    work_id: str
    target_path: str
    target_type: TargetType
    owner_lane: str
    is_frozen: bool
    requires_human_approval: bool


@dataclass(frozen=True)
class WorkClaim:
    work_id: str
    worker_name: str
    workspace_path: str
    branch_name: str
    lease_token: str | None = None
    lease_expires_at: str | None = None
    claimed_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionGuardrailContext:
    allowed_waves: set[str]
    frozen_prefixes: tuple[str, ...]


@dataclass(frozen=True)
class GuardrailViolation:
    code: str
    target_path: str
    message: str


@dataclass(frozen=True)
class QueueEvaluation:
    executable_ids: list[str]
    blocked_by_id: dict[str, list[GuardrailViolation]]


@dataclass(frozen=True)
class ExecutionRun:
    work_id: str
    worker_name: str
    status: WorkStatus
    branch_name: str | None = None
    command_digest: str | None = None
    summary: str | None = None
    exit_code: int | None = None
    elapsed_ms: int | None = None
    stdout_digest: str = ""
    stderr_digest: str = ""
    result_payload_json: dict[str, Any] | None = None
    partial_artifacts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionContext:
    work_id: str
    title: str
    lane: str
    wave: str
    repo: str | None = None
    source_issue_number: int | None = None
    canonical_story_issue_number: int | None = None
    story_issue_numbers: tuple[int, ...] = ()
    planned_paths: tuple[str, ...] = ()
    workspace_path: str | None = None
    project_dir: str | None = None
    session_policy: str = "fresh_session"
    resume_hint: str | None = None
    resume_context: str | None = None


@dataclass(frozen=True)
class VerificationEvidence:
    work_id: str
    check_type: str
    command: str
    passed: bool
    output_digest: str
    run_id: int | None = None
    exit_code: int | None = None
    elapsed_ms: int | None = None
    stdout_digest: str = ""
    stderr_digest: str = ""


@dataclass(frozen=True)
class ApprovalEvent:
    work_id: str
    approver: str
    decision: str
    reason: str | None = None


# =============================================================================
# Parallel Execution Extensions - AI Autonomy Models
# =============================================================================


@dataclass(frozen=True)
class AIConversationTurn:
    """AI 对话轮次"""

    id: str
    work_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    turn_index: int
    metadata: dict = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True)
class AIConversationSummary:
    """AI 对话摘要"""

    work_id: str
    summary: str
    turn_count: int
    last_turn_index: int
    updated_at: datetime | None = None


@dataclass(frozen=True)
class AIDecision:
    """AI 自主决策"""

    id: int
    work_id: str
    decision_type: Literal[
        "auto_resolvable",
        "requires_human",
        "retry_with_context",
        "escalate_to_operator",
    ]
    original_reason_code: str | None
    ai_reasoning: str
    context_summary: str | None
    outcome: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class NotificationRequest:
    """通知请求"""

    id: int | None
    notification_type: Literal[
        "human_decision_required",
        "retry_resolved",
        "story_complete",
        "epic_blocked",
        "milestone_reached",
    ]
    channel: Literal["discord", "slack", "telegram", "email"]
    recipient: str | None
    subject: str
    message: str
    work_id: str | None = None
    story_issue_number: int | None = None
    epic_issue_number: int | None = None
    metadata: dict = field(default_factory=dict)
    status: Literal["pending", "sent", "failed"] = "pending"
    sent_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class StoredAgentConfig:
    """Agent 配置"""

    id: int | None
    agent_name: str
    agent_type: Literal[
        "claude_code",
        "gemini_cli",
        "codex",
        "opencode",
        "qwen_code",
    ]
    command_template: str
    max_parallel: int = 1
    current_parallel: int = 0
    is_active: bool = True
    metadata: dict = field(default_factory=dict)
    updated_at: datetime | None = None


# Backward compatibility alias. New code should use StoredAgentConfig.
AgentConfig = StoredAgentConfig


@dataclass(frozen=True)
class RetryPolicy:
    """重试策略配置"""

    id: int | None
    failure_reason_pattern: str
    max_retries: int = 3
    base_backoff_minutes: int = 5
    max_backoff_minutes: int = 240
    backoff_multiplier: float = 2.0
    is_active: bool = True
    created_at: datetime | None = None


@dataclass(frozen=True)
class GitHubNormalizedIssue:
    repo: str
    issue_number: int
    title: str
    body: str
    url: str
    github_state: str
    import_state: str
    issue_kind: str | None
    lane: str | None
    complexity: str | None
    status_label: str | None
    explicit_parent_issue_numbers: list[int]
    explicit_story_dependency_issue_numbers: list[int] = field(default_factory=list)
    explicit_task_dependency_issue_numbers: list[int] = field(default_factory=list)
    anomaly_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GitHubRelationCandidate:
    source_issue_number: int
    target_issue_number: int
    relation_type: str
    confidence: float
    evidence_text: str


@dataclass(frozen=True)
class CompletionAudit:
    issue_number: int
    derived_complete: bool
    reasons: list[str]


@dataclass(frozen=True)
class GitHubTaskProjection:
    work_items: list[WorkItem]
    story_task_ids: dict[int, list[str]]
    work_dependencies: list[WorkDependency] = field(default_factory=list)
    story_dependencies: list[tuple[int, int]] = field(default_factory=list)
    needs_triage_issue_numbers: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class StoryRunResult:
    story_issue_number: int
    completed_work_item_ids: list[str]
    blocked_work_item_ids: list[str]
    remaining_work_item_ids: list[str]
    story_complete: bool
    merge_blocked_reason: str | None = None
    reason_code: str | None = None


@dataclass(frozen=True)
class EpicExecutionState:
    repo: str
    epic_issue_number: int
    status: EpicRuntimeStatus
    completed_story_issue_numbers: tuple[int, ...] = ()
    blocked_story_issue_numbers: tuple[int, ...] = ()
    remaining_story_issue_numbers: tuple[int, ...] = ()
    blocked_reason_code: str | None = None
    operator_attention_required: bool = False
    last_operator_action_at: datetime | None = None
    last_operator_action_reason: str | None = None
    last_progress_at: datetime | None = None
    stalled_since: datetime | None = None
    verification_status: str | None = None
    verification_reason_code: str | None = None
    last_verification_at: datetime | None = None
    verification_summary: str | None = None


@dataclass(frozen=True)
class OperatorRequest:
    repo: str
    epic_issue_number: int
    reason_code: str
    summary: str
    remaining_story_issue_numbers: tuple[int, ...] = ()
    blocked_story_issue_numbers: tuple[int, ...] = ()
    status: str = "open"
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    closed_reason: str | None = None


@dataclass(frozen=True)
class EpicRunResult:
    epic_issue_number: int
    completed_story_issue_numbers: list[int]
    blocked_story_issue_numbers: list[int]
    remaining_story_issue_numbers: list[int]
    epic_complete: bool
    reason_code: str | None = None


@dataclass(frozen=True)
class StoryIntegrationRun:
    repo: str
    story_issue_number: int
    merged: bool
    promoted: bool = False
    merge_commit_sha: str | None = None
    promotion_commit_sha: str | None = None
    blocked_reason: str | None = None
    summary: str = ""


@dataclass(frozen=True)
class StoryVerificationRun:
    repo: str
    story_issue_number: int
    check_type: str
    command: str
    passed: bool
    summary: str = ""
    output_digest: str = ""
    exit_code: int | None = None
    elapsed_ms: int | None = None
    stdout_digest: str = ""
    stderr_digest: str = ""


@dataclass(frozen=True)
class StoryPullRequestLink:
    repo: str
    story_issue_number: int
    pull_number: int
    pull_url: str


@dataclass(frozen=True)
class TaskSpecDraft:
    repo: str
    story_issue_number: int
    title: str
    complexity: str
    goal: str
    allowed_paths: tuple[str, ...]
    dod: tuple[str, ...]
    verification: tuple[str, ...]
    references: tuple[str, ...]
    status: str = "proposed"
    source_reason_code: str | None = None


@dataclass(frozen=True)
class TriageReport:
    unprojected_task_issue_numbers: list[int]
    storys_without_projected_tasks: list[int]
    anomalies_by_issue: dict[int, list[str]]


@dataclass(frozen=True)
class ProgramEpic:
    issue_number: int
    repo: str
    title: str
    lane: str | None
    program_status: ProgramStatus
    execution_status: ExecutionStatus
    active_wave: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ProgramStory:
    issue_number: int
    repo: str
    epic_issue_number: int | None
    title: str
    lane: str | None
    complexity: str | None
    program_status: ProgramStatus
    execution_status: ExecutionStatus
    active_wave: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ProgramGovernanceProjection:
    epics: list[ProgramEpic]
    stories: list[ProgramStory]
    epic_dependencies: list[tuple[int, int]] = field(default_factory=list)
    story_dependencies: list[tuple[int, int]] = field(default_factory=list)


def with_work_status(work_item: WorkItem, status: WorkStatus) -> WorkItem:
    return replace(work_item, status=status)


# -----------------------------------------------------------------------
# Execution session models (Phase A-2)
# -----------------------------------------------------------------------

SessionStatus = Literal[
    "active",
    "suspended",
    "waiting_internal",
    "waiting_external",
    "policy_review",
    "human_required",
    "completed",
    "failed_terminal",
]

SESSION_TERMINAL_STATUSES: set[SessionStatus] = {
    "completed",
    "failed_terminal",
    "human_required",
}

SESSION_WAITING_STATUSES: set[SessionStatus] = {
    "suspended",
    "waiting_internal",
    "waiting_external",
}


@dataclass(frozen=True)
class ExecutionSession:
    id: str
    work_id: str
    status: SessionStatus = "active"
    attempt_index: int = 1
    parent_session_id: str | None = None
    current_phase: str = "planning"
    strategy_name: str | None = None
    resume_token: str | None = None
    waiting_reason: str | None = None
    wake_after: str | None = None
    wake_condition: dict[str, Any] | None = None
    context_summary: str | None = None
    last_checkpoint_id: str | None = None
    created_at: str | None = None
    last_heartbeat_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class ExecutionCheckpoint:
    id: str
    session_id: str
    phase: str
    summary: str
    phase_index: int = 1
    artifacts: dict[str, Any] | None = None
    tool_state: dict[str, Any] | None = None
    subtasks: list[Any] | None = None
    failure_context: dict[str, Any] | None = None
    next_action_hint: str | None = None
    next_action_params: dict[str, Any] | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class PolicyResolutionRecord:
    id: str | None
    session_id: str
    work_id: str
    risk_level: str
    trigger_reason: str
    evidence_json: dict[str, Any] | None = None
    resolution: str = ""
    resolution_detail_json: dict[str, Any] | None = None
    applied: bool = False
    created_at: str | None = None


@dataclass(frozen=True)
class ExecutionWakeup:
    id: str
    session_id: str
    work_id: str
    wake_type: str
    wake_condition: dict[str, Any]
    status: str = "pending"
    scheduled_at: str | None = None
    fired_at: str | None = None
    created_at: str | None = None
