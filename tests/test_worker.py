from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from stardrifter_orchestration_mvp.git_committer import CommitResult
from stardrifter_orchestration_mvp.guardrails import evaluate_execution_guardrails
from stardrifter_orchestration_mvp.models import (
    ApprovalEvent,
    ExecutionRun,
    ExecutionGuardrailContext,
    VerificationEvidence,
    WorkClaim,
    WorkDependency,
    WorkItem,
    WorkTarget,
)
from stardrifter_orchestration_mvp._worker_failure_policy import (
    BACKOFF_BASE_MINUTES,
    BACKOFF_MAX_MINUTES,
    _classify_execution_failure,
    calculate_backoff,
    is_auto_resolvable_failure,
    is_human_required_failure,
)
from stardrifter_orchestration_mvp._worker_execution_runtime import (
    _renew_claim_after_prepare,
    _run_executor_with_heartbeat,
)
from stardrifter_orchestration_mvp._worker_queue_preparation import (
    PreflightEarlyExit,
    _prepare_worker_queue,
    _run_preflight_checks,
)
from stardrifter_orchestration_mvp.repository import InMemoryControlPlaneRepository
from stardrifter_orchestration_mvp.worker import (
    ExecutionResult,
    _build_execution_context,
    _exclude_previously_completed_in_memory_candidates as _exclude_previously_completed_in_memory_candidates_from_worker,
    _materialize_blocked_items as _materialize_blocked_items_from_worker,
    _renew_claim_after_prepare as _renew_claim_after_prepare_from_worker,
    _run_preflight_checks as _run_preflight_checks_from_worker,
    _run_executor_with_heartbeat as _run_executor_with_heartbeat_from_worker,
    run_worker_cycle,
)


def test_failure_policy_calculate_backoff_uses_expected_exponential_schedule():
    assert calculate_backoff(1).total_seconds() == BACKOFF_BASE_MINUTES * 60
    assert calculate_backoff(2).total_seconds() == BACKOFF_BASE_MINUTES * 2 * 60
    assert calculate_backoff(3).total_seconds() == BACKOFF_BASE_MINUTES * 4 * 60
    assert calculate_backoff(10).total_seconds() == BACKOFF_MAX_MINUTES * 60


def test_failure_policy_classifies_auto_resolvable_and_human_required_reasons():
    assert is_auto_resolvable_failure("timeout") is True
    assert is_auto_resolvable_failure("paused_for_input: waiting on next step") is True
    assert is_auto_resolvable_failure("missing-terminal-payload") is True
    assert is_auto_resolvable_failure("multiple-terminal-payloads") is True
    assert is_auto_resolvable_failure("tooling_error") is False

    assert is_human_required_failure("credential_required") is True
    assert is_human_required_failure("upstream_api_error") is True
    assert is_human_required_failure("SECURITY_CONCERN: manual approval") is True
    assert is_human_required_failure("timeout") is False


def test_failure_policy_classifies_interrupted_retryable_as_immediate_resume_candidate():
    result = _classify_execution_failure(
        ExecutionResult(
            success=False,
            summary="executor interrupted",
            blocked_reason="interrupted_retryable",
        ),
        attempt_count=3,
    )

    assert result == (
        "pending",
        None,
        False,
        1,
        "interrupted_retryable",
        None,
        "resume_candidate",
    )


def test_failure_policy_classifies_timeout_with_retry_metadata_and_backoff_window():
    now = datetime.now(UTC)

    result = _classify_execution_failure(
        ExecutionResult(
            success=False,
            summary="executor timed out",
            blocked_reason="timeout",
        ),
        attempt_count=2,
    )

    assert result[0:5] == ("pending", None, False, 1, "timeout")
    assert result[6] is None
    assert result[5] is not None

    next_eligible_at = datetime.fromisoformat(result[5])
    min_expected = now + calculate_backoff(2) - timedelta(seconds=1)
    max_expected = now + calculate_backoff(2) + timedelta(seconds=1)
    assert min_expected <= next_eligible_at <= max_expected


def test_failure_policy_classifies_human_required_failure_without_retry_metadata():
    result = _classify_execution_failure(
        ExecutionResult(
            success=False,
            summary="needs credential",
            blocked_reason="credential_required",
        ),
        attempt_count=2,
    )

    assert result == (
        "blocked",
        "credential_required",
        True,
        None,
        "credential_required",
        None,
        None,
    )


def test_failure_policy_keeps_non_recoverable_failure_blocked_without_retry_tracking():
    result = _classify_execution_failure(
        ExecutionResult(
            success=False,
            summary="tooling exploded",
            blocked_reason="tooling_error",
        ),
        attempt_count=4,
    )

    assert result == (
        "blocked",
        "tooling_error",
        False,
        None,
        None,
        None,
        None,
    )


def test_worker_runtime_reexports_helpers_from_worker_module():
    assert _renew_claim_after_prepare_from_worker is _renew_claim_after_prepare
    assert _run_executor_with_heartbeat_from_worker is _run_executor_with_heartbeat


def test_worker_reexports_queue_preparation_helpers_from_worker_module():
    from stardrifter_orchestration_mvp._worker_queue_preparation import (
        _exclude_previously_completed_in_memory_candidates,
        _materialize_blocked_items,
        _run_preflight_checks,
    )

    assert _run_preflight_checks_from_worker is _run_preflight_checks
    assert (
        _exclude_previously_completed_in_memory_candidates_from_worker
        is _exclude_previously_completed_in_memory_candidates
    )
    assert _materialize_blocked_items_from_worker is _materialize_blocked_items


def test_prepare_worker_queue_preserves_preflight_and_queue_behavior_before_claim():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-queue-1",
                title="already done in memory",
                lane="Lane 01",
                wave="wave-1",
                status="ready",
                planned_paths=("src/already_done.py",),
            ),
            WorkItem(
                id="task-queue-2",
                title="ready active candidate",
                lane="Lane 01",
                wave="wave-1",
                status="ready",
                planned_paths=("src/active_candidate.py",),
            ),
            WorkItem(
                id="task-queue-3",
                title="guardrail blocked candidate",
                lane="Lane 01",
                wave="wave-2",
                status="ready",
                planned_paths=("src/blocked_candidate.py",),
            ),
            WorkItem(
                id="task-queue-4",
                title="filtered out candidate",
                lane="Lane 01",
                wave="wave-1",
                status="ready",
                planned_paths=("src/filtered_out.py",),
            ),
        ],
        dependencies=[],
        targets_by_work_id={},
        execution_runs=[
            ExecutionRun(
                work_id="task-queue-1",
                worker_name="worker-a",
                status="done",
                summary="completed already",
            )
        ],
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-1"},
        frozen_prefixes=("docs/authority/",),
    )

    class ActiveOnlyRepository(InMemoryControlPlaneRepository):
        def list_active_work_items(self):
            return [
                self.work_items_by_id["task-queue-1"],
                self.work_items_by_id["task-queue-2"],
                self.work_items_by_id["task-queue-3"],
                self.work_items_by_id["task-queue-4"],
            ]

    repository = ActiveOnlyRepository(
        work_items=repository.work_items,
        dependencies=repository.dependencies,
        targets_by_work_id=repository.targets_by_work_id,
        execution_runs=repository.execution_runs,
    )

    prepared = _prepare_worker_queue(
        repository=repository,
        context=context,
        work_item_ids=["task-queue-1", "task-queue-2", "task-queue-3"],
        worker_name="worker-a",
    )

    assert prepared.early_exit_result is None
    assert [item.id for item in prepared.work_items] == ["task-queue-2", "task-queue-3"]
    assert prepared.evaluation.executable_ids == ["task-queue-2"]
    assert "task-queue-3" in prepared.evaluation.blocked_by_id
    assert repository.work_items_by_id["task-queue-3"].status == "blocked"
    assert repository.work_items_by_id["task-queue-3"].blocked_reason is not None


def test_run_preflight_checks_returns_internal_early_exit_shape_for_missing_issue_identity():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-preflight-1",
                title="missing issue identity",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
                repo="codefromkarl/stardrifter",
                source_issue_number=None,
            ),
        ],
        dependencies=[],
        targets_by_work_id={},
    )

    result = _run_preflight_checks(repository=repository, work_item_ids=None)

    assert result == PreflightEarlyExit(claimed_work_id=None)
    assert repository.work_items_by_id["task-preflight-1"].status == "blocked"
    assert (
        repository.work_items_by_id["task-preflight-1"].blocked_reason
        == "missing_source_issue_number"
    )


def test_renew_claim_after_prepare_uses_current_matching_active_claim_token_only():
    renewed: list[tuple[str, str]] = []

    class RenewingRepository(InMemoryControlPlaneRepository):
        def renew_work_claim(self, work_id: str, *, lease_token: str):
            renewed.append((work_id, lease_token))
            return super().renew_work_claim(work_id, lease_token=lease_token)

    repository = RenewingRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )
    repository.upsert_work_claim(
        WorkClaim(
            work_id="task-100",
            worker_name="worker-a",
            workspace_path="/tmp/task-100",
            branch_name="task/100",
            lease_token="token-100",
            lease_expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        )
    )
    repository.upsert_work_claim(
        WorkClaim(
            work_id="task-101",
            worker_name="worker-b",
            workspace_path="/tmp/task-101",
            branch_name="task/101",
            lease_token="token-101",
            lease_expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        )
    )

    _renew_claim_after_prepare(repository, "task-101")

    assert renewed == [("task-101", "token-101")]


def test_renew_claim_after_prepare_skips_when_active_claim_has_no_lease_token():
    renewed: list[tuple[str, str]] = []

    class RenewingRepository(InMemoryControlPlaneRepository):
        def renew_work_claim(self, work_id: str, *, lease_token: str):
            renewed.append((work_id, lease_token))
            return super().renew_work_claim(work_id, lease_token=lease_token)

    repository = RenewingRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )
    repository.upsert_work_claim(
        WorkClaim(
            work_id="task-102",
            worker_name="worker-a",
            workspace_path="/tmp/task-102",
            branch_name="task/102",
            lease_token=None,
            lease_expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        )
    )

    _renew_claim_after_prepare(repository, "task-102")

    assert renewed == []


def test_renew_claim_after_prepare_skips_when_repository_does_not_support_claim_renewal():
    class LegacyRepository:
        pass

    _renew_claim_after_prepare(LegacyRepository(), "task-103")


def test_run_executor_with_heartbeat_passes_heartbeat_and_execution_context_when_supported():
    heartbeat_calls: list[str] = []
    captured: dict[str, object] = {}

    class RenewingRepository:
        def list_active_work_claims(self):
            return [
                WorkClaim(
                    work_id="task-104",
                    worker_name="worker-a",
                    workspace_path="/tmp/task-104",
                    branch_name="task/104",
                    lease_token="token-104",
                    lease_expires_at=(
                        datetime.now(UTC) + timedelta(minutes=5)
                    ).isoformat(),
                )
            ]

        def renew_work_claim(self, work_id: str, *, lease_token: str):
            heartbeat_calls.append(f"{work_id}:{lease_token}")

    execution_context = _build_execution_context(
        repository=InMemoryControlPlaneRepository(
            work_items=[
                WorkItem(
                    id="task-104",
                    title="runtime helper",
                    lane="Lane 01",
                    wave="wave-1",
                    status="in_progress",
                )
            ],
            dependencies=[],
            targets_by_work_id={},
        ),
        work_id="task-104",
        workspace_path=Path("/tmp/task-104"),
    )

    def executor(
        work_item, workspace_path=None, heartbeat=None, execution_context=None
    ):
        captured["work_id"] = work_item.id
        captured["workspace_path"] = workspace_path
        captured["execution_context"] = execution_context
        assert heartbeat is not None
        heartbeat()
        return ExecutionResult(success=True, summary="ok")

    result = _run_executor_with_heartbeat(
        executor=executor,
        repository=RenewingRepository(),
        work_id="task-104",
        work_item=WorkItem(
            id="task-104",
            title="runtime helper",
            lane="Lane 01",
            wave="wave-1",
            status="in_progress",
        ),
        workspace_path=Path("/tmp/task-104"),
        execution_context=execution_context,
    )

    assert result == ExecutionResult(success=True, summary="ok")
    assert heartbeat_calls == ["task-104:token-104"]
    assert captured["work_id"] == "task-104"
    assert captured["workspace_path"] == Path("/tmp/task-104")
    assert captured["execution_context"] == execution_context


def test_run_executor_with_heartbeat_passes_only_execution_context_for_non_heartbeat_executor():
    captured: dict[str, object] = {}
    work_item = WorkItem(
        id="task-105",
        title="context-only executor",
        lane="Lane 01",
        wave="wave-1",
        status="in_progress",
    )
    execution_context = _build_execution_context(
        repository=InMemoryControlPlaneRepository(
            work_items=[work_item],
            dependencies=[],
            targets_by_work_id={},
        ),
        work_id="task-105",
        workspace_path=None,
    )

    def executor(work_item, workspace_path=None, execution_context=None):
        captured["work_id"] = work_item.id
        captured["workspace_path"] = workspace_path
        captured["execution_context"] = execution_context
        return ExecutionResult(success=True, summary="ok")

    result = _run_executor_with_heartbeat(
        executor=executor,
        repository=InMemoryControlPlaneRepository(
            work_items=[],
            dependencies=[],
            targets_by_work_id={},
        ),
        work_id="task-105",
        work_item=work_item,
        workspace_path=None,
        execution_context=execution_context,
    )

    assert result == ExecutionResult(success=True, summary="ok")
    assert captured == {
        "work_id": "task-105",
        "workspace_path": None,
        "execution_context": execution_context,
    }


def test_run_executor_with_heartbeat_supports_legacy_executor_without_optional_parameters():
    captured: list[tuple[str, Path | None]] = []
    work_item = WorkItem(
        id="task-106",
        title="legacy executor",
        lane="Lane 01",
        wave="wave-1",
        status="in_progress",
    )

    def executor(work_item, workspace_path=None):
        captured.append((work_item.id, workspace_path))
        return ExecutionResult(success=True, summary="ok")

    result = _run_executor_with_heartbeat(
        executor=executor,
        repository=InMemoryControlPlaneRepository(
            work_items=[],
            dependencies=[],
            targets_by_work_id={},
        ),
        work_id="task-106",
        work_item=work_item,
        workspace_path=Path("/tmp/task-106"),
        execution_context=_build_execution_context(
            repository=InMemoryControlPlaneRepository(
                work_items=[work_item],
                dependencies=[],
                targets_by_work_id={},
            ),
            work_id="task-106",
            workspace_path=Path("/tmp/task-106"),
        ),
    )

    assert result == ExecutionResult(success=True, summary="ok")
    assert captured == [("task-106", Path("/tmp/task-106"))]


def test_run_worker_cycle_claims_executes_verifies_and_marks_done():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-1",
                title="upstream",
                lane="Lane 06",
                wave="wave-5",
                status="done",
            ),
            WorkItem(
                id="task-2",
                title="safe cleanup",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
            ),
        ],
        dependencies=[WorkDependency(work_id="task-2", depends_on_work_id="task-1")],
        targets_by_work_id={
            "task-2": [
                WorkTarget(
                    work_id="task-2",
                    target_path="src/stardrifter_engine/projections/godot_map_projection.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    def executor(work_item: WorkItem, workspace_path=None) -> ExecutionResult:
        assert work_item.id == "task-2"
        return ExecutionResult(
            success=True,
            summary="patched files",
            command_digest="codex run",
            exit_code=0,
            elapsed_ms=12,
            stdout_digest="stdout ok",
            stderr_digest="",
        )

    def verifier(work_item: WorkItem, workspace_path=None):
        assert work_item.id == "task-2"
        from stardrifter_orchestration_mvp.models import VerificationEvidence

        return VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="3 passed",
            exit_code=0,
            elapsed_ms=34,
            stdout_digest="3 passed",
            stderr_digest="",
        )

    commit_calls = []

    def committer(
        work_item: WorkItem, execution_result: ExecutionResult, workspace_path=None
    ):
        commit_calls.append((work_item.id, execution_result.summary))
        return CommitResult(
            committed=True,
            commit_sha="abc123",
            blocked_reason=None,
            summary="committed",
            commit_message="chore(task-2): complete task #2",
        )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=executor,
        verifier=verifier,
        committer=committer,
    )

    assert result.claimed_work_id == "task-2"
    assert repository.work_items_by_id["task-2"].status == "done"
    assert len(repository.execution_runs) == 1
    assert repository.execution_runs[0].status == "done"
    assert repository.execution_runs[0].exit_code == 0
    assert repository.execution_runs[0].elapsed_ms == 12
    assert len(repository.verification_evidence) == 1
    assert repository.verification_evidence[0].passed is True
    assert repository.verification_evidence[0].exit_code == 0
    assert repository.verification_evidence[0].elapsed_ms == 34
    assert commit_calls == [("task-2", "patched files")]


def test_run_worker_cycle_passes_execution_context_to_executor_and_verifier(tmp_path):
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-31",
                title="context assembly",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
                repo="codefromkarl/stardrifter",
                source_issue_number=31,
                canonical_story_issue_number=12,
                story_issue_numbers=(12,),
                planned_paths=("src/stardrifter_engine/runtime.py",),
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-31": [
                WorkTarget(
                    work_id="task-31",
                    target_path="src/stardrifter_engine/runtime.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )
    captured = {}

    class FakeWorkspaceManager:
        repo_root = Path("/repo/root")
        worktree_root = tmp_path

        def prepare(self, *, work_item, worker_name, repository):
            return tmp_path / "task-31"

        def release(self, *, work_item, repository):
            repository.delete_work_claim(work_item.id)

    def executor(work_item, workspace_path=None, execution_context=None):
        captured["executor_context"] = execution_context
        return ExecutionResult(success=True, summary="done")

    def verifier(work_item, workspace_path=None, execution_context=None):
        captured["verifier_context"] = execution_context
        from stardrifter_orchestration_mvp.models import VerificationEvidence

        return VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=executor,
        verifier=verifier,
        workspace_manager=FakeWorkspaceManager(),
    )

    assert result.claimed_work_id == "task-31"
    for key in ("executor_context", "verifier_context"):
        ctx = captured[key]
        assert ctx.work_id == "task-31"
        assert ctx.title == "context assembly"
        assert ctx.repo == "codefromkarl/stardrifter"
        assert ctx.source_issue_number == 31
        assert ctx.canonical_story_issue_number == 12
        assert ctx.story_issue_numbers == (12,)
        assert ctx.planned_paths == ("src/stardrifter_engine/runtime.py",)
        assert ctx.workspace_path == str(tmp_path / "task-31")
        assert ctx.project_dir == str(tmp_path / "task-31")


def test_run_worker_cycle_blocks_guardrail_violations_before_execution():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-1",
                title="needs approval",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-1": [
                WorkTarget(
                    work_id="task-1",
                    target_path="docs/authority/active-baselines.md",
                    target_type="doc",
                    owner_lane="Lane 06",
                    is_frozen=True,
                    requires_human_approval=True,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True,
            summary="should not run",
            exit_code=0,
            elapsed_ms=1,
            stdout_digest="",
            stderr_digest="",
        ),
        verifier=lambda work_item, workspace_path=None: (_ for _ in ()).throw(
            AssertionError("verifier should not run")
        ),
    )

    assert result.claimed_work_id is None
    assert repository.work_items_by_id["task-1"].status == "blocked"
    assert repository.blocked_reasons["task-1"]
    assert not repository.execution_runs


def test_run_worker_cycle_does_not_reblock_task_after_prior_successful_done_run():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-82",
                title="stable location references",
                lane="Lane 01",
                wave="unassigned",
                status="ready",
            ),
        ],
        dependencies=[],
        targets_by_work_id={},
        execution_runs=[
            ExecutionRun(
                work_id="issue-82",
                worker_name="worker-a",
                status="done",
                summary="already completed",
            )
        ],
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"unassigned"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-b",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=False,
            summary="opencode did not emit a valid structured result payload",
            blocked_reason="invalid-result-payload",
        ),
        verifier=lambda work_item, workspace_path=None: (_ for _ in ()).throw(
            AssertionError("verifier should not run")
        ),
    )

    assert result.claimed_work_id is None
    assert repository.work_items_by_id["issue-82"].status == "ready"


def test_run_worker_cycle_blocks_preflight_when_required_issue_identity_is_missing():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-30",
                title="missing issue identity",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
                repo="codefromkarl/stardrifter",
                source_issue_number=None,
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-30": [
                WorkTarget(
                    work_id="task-30",
                    target_path="src/stardrifter_engine/runtime.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True,
            summary="should not run",
        ),
        verifier=lambda work_item, workspace_path=None: (_ for _ in ()).throw(
            AssertionError("verifier should not run")
        ),
    )

    assert result.claimed_work_id is None
    assert repository.work_items_by_id["task-30"].status == "blocked"
    assert (
        repository.work_items_by_id["task-30"].blocked_reason
        == "missing_source_issue_number"
    )
    assert not repository.execution_runs


def test_run_worker_cycle_allows_file_task_without_planned_paths_under_current_preflight():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-35",
                title="missing planned paths",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
                repo="codefromkarl/stardrifter",
                source_issue_number=35,
                planned_paths=(),
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-35": [
                WorkTarget(
                    work_id="task-35",
                    target_path="src/stardrifter_engine/runtime.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    from stardrifter_orchestration_mvp.models import VerificationEvidence

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True,
            summary="ran without planned paths",
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
    )

    assert result.claimed_work_id == "task-35"
    assert repository.work_items_by_id["task-35"].status == "done"


def test_run_worker_cycle_marks_needs_decision_metadata_on_blocked_task():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-4",
                title="needs decision",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-4": [
                WorkTarget(
                    work_id="task-4",
                    target_path="docs/domains/06-projection-save-replay/execution-plan.md",
                    target_type="doc",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=False,
            summary="需要人类决策",
            blocked_reason="missing-approval",
            decision_required=True,
            result_payload_json={
                "outcome": "needs_decision",
                "reason_code": "missing-approval",
            },
        ),
        verifier=lambda work_item, workspace_path=None: (_ for _ in ()).throw(
            AssertionError("verifier should not run")
        ),
    )

    assert result.claimed_work_id == "task-4"
    assert repository.work_items_by_id["task-4"].status == "blocked"
    assert repository.work_items_by_id["task-4"].blocked_reason == "missing-approval"
    assert repository.work_items_by_id["task-4"].decision_required is True
    assert repository.execution_runs[0].result_payload_json == {
        "outcome": "needs_decision",
        "reason_code": "missing-approval",
    }


def test_run_worker_cycle_keeps_tooling_error_blocked_without_retry_metadata():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-36",
                title="tooling error",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-36": [
                WorkTarget(
                    work_id="task-36",
                    target_path="src/stardrifter_engine/runtime.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=False,
            summary="executor tooling failure",
            blocked_reason="tooling_error",
            result_payload_json={"reason_code": "tooling_error"},
        ),
        verifier=lambda work_item, workspace_path=None: (_ for _ in ()).throw(
            AssertionError("verifier should not run")
        ),
    )

    assert result.claimed_work_id == "task-36"
    assert repository.work_items_by_id["task-36"].status == "blocked"
    assert repository.work_items_by_id["task-36"].blocked_reason == "tooling_error"
    assert repository.work_items_by_id["task-36"].attempt_count == 0
    assert repository.work_items_by_id["task-36"].last_failure_reason is None
    assert repository.work_items_by_id["task-36"].next_eligible_at is None


def test_run_worker_cycle_keeps_protocol_error_blocked_without_retry_metadata():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-37",
                title="protocol error",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-37": [
                WorkTarget(
                    work_id="task-37",
                    target_path="src/stardrifter_engine/runtime.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=False,
            summary="invalid executor payload",
            blocked_reason="protocol_error",
            result_payload_json={"reason_code": "protocol_error"},
        ),
        verifier=lambda work_item, workspace_path=None: (_ for _ in ()).throw(
            AssertionError("verifier should not run")
        ),
    )

    assert result.claimed_work_id == "task-37"
    assert repository.work_items_by_id["task-37"].status == "blocked"
    assert repository.work_items_by_id["task-37"].blocked_reason == "protocol_error"
    assert repository.work_items_by_id["task-37"].attempt_count == 0
    assert repository.work_items_by_id["task-37"].last_failure_reason is None
    assert repository.work_items_by_id["task-37"].next_eligible_at is None


def test_run_worker_cycle_requeues_timeout_failure_as_ready():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-16",
                title="timeout task",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-16": [
                WorkTarget(
                    work_id="task-16",
                    target_path="src/stardrifter_engine/runtime.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=False,
            summary="executor timed out",
            blocked_reason="timeout",
        ),
        verifier=lambda work_item, workspace_path=None: (_ for _ in ()).throw(
            AssertionError("verifier should not run")
        ),
    )

    assert result.claimed_work_id == "task-16"
    assert repository.work_items_by_id["task-16"].status == "pending"
    assert repository.work_items_by_id["task-16"].blocked_reason is None
    assert repository.work_items_by_id["task-16"].attempt_count == 1
    assert repository.work_items_by_id["task-16"].last_failure_reason == "timeout"
    assert repository.work_items_by_id["task-16"].next_eligible_at is not None
    assert repository.execution_runs[0].status == "blocked"
    assert repository.execution_runs[0].summary == "executor timed out"


def test_run_worker_cycle_requeues_invalid_result_payload_failure_as_ready():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-38",
                title="payload glitch",
                lane="Lane 01",
                wave="unassigned",
                status="pending",
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-38": [
                WorkTarget(
                    work_id="task-38",
                    target_path="tests/unit/test_campaign_topology_schema_closure.py",
                    target_type="file",
                    owner_lane="Lane 01",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"unassigned"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=False,
            summary="opencode did not emit a valid structured result payload",
            blocked_reason="invalid-result-payload",
        ),
        verifier=lambda work_item, workspace_path=None: (_ for _ in ()).throw(
            AssertionError("verifier should not run")
        ),
    )

    assert result.claimed_work_id == "task-38"
    assert repository.work_items_by_id["task-38"].status == "pending"
    assert repository.work_items_by_id["task-38"].blocked_reason is None
    assert repository.work_items_by_id["task-38"].attempt_count == 1
    assert (
        repository.work_items_by_id["task-38"].last_failure_reason
        == "invalid-result-payload"
    )


def test_run_worker_cycle_keeps_timeout_retry_as_fresh_session_policy():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-33",
                title="timeout session policy",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-33": [
                WorkTarget(
                    work_id="task-33",
                    target_path="src/stardrifter_engine/runtime.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=False,
            summary="executor timed out",
            blocked_reason="timeout",
        ),
        verifier=lambda work_item, workspace_path=None: (_ for _ in ()).throw(
            AssertionError("verifier should not run")
        ),
    )

    assert repository.work_items_by_id["task-33"].last_failure_reason == "timeout"
    assert repository.work_items_by_id["task-33"].next_eligible_at is not None


def test_run_worker_cycle_marks_interrupted_retry_as_resume_candidate_context():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-34",
                title="interrupted retry context",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
                repo="codefromkarl/stardrifter",
                source_issue_number=34,
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-34": [
                WorkTarget(
                    work_id="task-34",
                    target_path="src/stardrifter_engine/runtime.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )
    captured: list[object] = []

    run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=False,
            summary="executor interrupted",
            blocked_reason="interrupted_retryable",
        ),
        verifier=lambda work_item, workspace_path=None: (_ for _ in ()).throw(
            AssertionError("verifier should not run")
        ),
    )

    ctx = _build_execution_context(
        repository=repository,
        work_id="task-34",
        workspace_path=None,
    )
    assert getattr(ctx, "session_policy") == "resume_candidate"


def test_run_worker_cycle_uses_repository_finalization_for_timeout_failure():
    finalized: list[dict[str, object]] = []

    class FinalizingRepository(InMemoryControlPlaneRepository):
        def finalize_work_attempt(self, **kwargs):
            finalized.append(kwargs)
            return super().finalize_work_attempt(**kwargs)

    repository = FinalizingRepository(
        work_items=[
            WorkItem(
                id="task-22",
                title="timeout finalized",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-22": [
                WorkTarget(
                    work_id="task-22",
                    target_path="src/stardrifter_engine/runtime.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=False,
            summary="executor timed out",
            blocked_reason="timeout",
        ),
        verifier=lambda work_item, workspace_path=None: (_ for _ in ()).throw(
            AssertionError("verifier should not run")
        ),
    )

    assert result.claimed_work_id == "task-22"
    assert len(finalized) == 1
    assert finalized[0]["status"] == "pending"
    assert finalized[0]["blocked_reason"] is None


def test_run_worker_cycle_uses_repository_finalization_for_needs_decision_failure():
    finalized: list[dict[str, object]] = []
    approval_events: list[ApprovalEvent] = []

    class FinalizingRepository(InMemoryControlPlaneRepository):
        def finalize_work_attempt(self, **kwargs):
            finalized.append(kwargs)
            return super().finalize_work_attempt(**kwargs)

        def record_approval_event(self, event: ApprovalEvent):
            approval_events.append(event)
            return super().record_approval_event(event)

    repository = FinalizingRepository(
        work_items=[
            WorkItem(
                id="task-23",
                title="needs decision finalized",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-23": [
                WorkTarget(
                    work_id="task-23",
                    target_path="docs/domains/06-projection-save-replay/execution-plan.md",
                    target_type="doc",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True,
            summary="需要人类决策",
            result_payload_json={
                "outcome": "needs_decision",
                "reason_code": "missing-approval",
                "decision_required": True,
            },
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
    )

    assert result.claimed_work_id == "task-23"
    assert len(finalized) == 1
    assert finalized[0]["status"] == "awaiting_approval"
    assert finalized[0]["blocked_reason"] is None
    assert finalized[0]["decision_required"] is True
    assert len(approval_events) == 1
    assert approval_events[0].work_id == "task-23"
    assert approval_events[0].decision == "requested"


def test_run_worker_cycle_requeues_prepare_failure_without_blocking_metadata(tmp_path):
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-17",
                title="prepare failure classification",
                lane="Lane 04",
                wave="unassigned",
                status="pending",
                planned_paths=("docs/domains/04-encounter-mediation/",),
            ),
        ],
        dependencies=[],
        targets_by_work_id={},
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"unassigned"},
        frozen_prefixes=("docs/authority/",),
    )

    class FailingWorkspaceManager:
        repo_root = Path("/repo/root")
        worktree_root = tmp_path

        def prepare(self, *, work_item, worker_name, repository):
            raise RuntimeError("prepare failed")

        def release(self, *, work_item, repository):
            raise AssertionError("release should not run after prepare failure")

    with pytest.raises(RuntimeError, match="prepare failed"):
        run_worker_cycle(
            repository=repository,
            context=context,
            worker_name="worker-a",
            executor=lambda work_item, workspace_path=None: ExecutionResult(
                success=True, summary="done"
            ),
            verifier=lambda work_item, workspace_path=None: (_ for _ in ()).throw(
                AssertionError("verifier should not run")
            ),
            workspace_manager=FailingWorkspaceManager(),
        )

    assert repository.work_items_by_id["task-17"].status == "ready"
    assert repository.work_items_by_id["task-17"].blocked_reason is None


def test_run_worker_cycle_keeps_verification_failure_blocked():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-18",
                title="verification failure",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-18": [
                WorkTarget(
                    work_id="task-18",
                    target_path="src/stardrifter_engine/runtime.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    from stardrifter_orchestration_mvp.models import VerificationEvidence

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True,
            summary="patched files",
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=False,
            output_digest="2 tests failed",
        ),
    )

    assert result.claimed_work_id == "task-18"
    assert repository.work_items_by_id["task-18"].status == "blocked"
    assert repository.work_items_by_id["task-18"].blocked_reason == "2 tests failed"


def test_run_worker_cycle_blocks_when_auto_commit_is_unsafe():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-5",
                title="needs safe commit",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-5": [
                WorkTarget(
                    work_id="task-5",
                    target_path="docs/domains/06-projection-save-replay/execution-plan.md",
                    target_type="doc",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    from stardrifter_orchestration_mvp.models import VerificationEvidence

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True,
            summary="patched files",
            result_payload_json={
                "changed_paths": [
                    "docs/domains/06-projection-save-replay/execution-plan.md"
                ]
            },
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
        committer=lambda work_item, execution_result, workspace_path=None: CommitResult(
            committed=False,
            commit_sha=None,
            blocked_reason="unsafe_auto_commit_dirty_paths",
            summary="cannot safely commit",
            commit_message=None,
        ),
    )

    assert result.claimed_work_id == "task-5"
    assert repository.work_items_by_id["task-5"].status == "blocked"
    assert (
        repository.work_items_by_id["task-5"].blocked_reason
        == "unsafe_auto_commit_dirty_paths"
    )
    assert repository.execution_runs[0].status == "blocked"
    assert repository.execution_runs[0].result_payload_json is not None
    assert (
        repository.execution_runs[0].result_payload_json["commit"]["blocked_reason"]
        == "unsafe_auto_commit_dirty_paths"
    )


def test_run_worker_cycle_blocks_duplicate_canonical_commit():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-21",
                title="duplicate commit",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
                repo="codefromkarl/stardrifter",
                source_issue_number=21,
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-21": [
                WorkTarget(
                    work_id="task-21",
                    target_path="src/stardrifter_engine/runtime.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    repository.record_commit_link(
        work_id="task-21",
        repo="codefromkarl/stardrifter",
        issue_number=21,
        commit_sha="abc123",
        commit_message="chore(task-21): complete task #21",
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    from stardrifter_orchestration_mvp.models import VerificationEvidence

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True,
            summary="patched files",
            result_payload_json={
                "changed_paths": ["src/stardrifter_engine/runtime.py"]
            },
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
        committer=lambda work_item, execution_result, workspace_path=None: CommitResult(
            committed=True,
            commit_sha="def456",
            blocked_reason=None,
            summary="committed",
            commit_message="chore(task-21): complete task #21",
        ),
    )

    assert result.claimed_work_id == "task-21"
    assert repository.work_items_by_id["task-21"].status == "blocked"
    assert (
        repository.work_items_by_id["task-21"].blocked_reason
        == "duplicate_canonical_commit"
    )


def test_run_worker_cycle_syncs_done_status_to_github_after_finalization():
    writes: list[dict[str, object]] = []
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-24",
                title="github done sync",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
                repo="codefromkarl/stardrifter",
                source_issue_number=24,
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-24": [
                WorkTarget(
                    work_id="task-24",
                    target_path="src/stardrifter_engine/runtime.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    from stardrifter_orchestration_mvp.models import VerificationEvidence

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True,
            summary="patched files",
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
        github_writeback=lambda **kwargs: writes.append(kwargs),
    )

    assert result.claimed_work_id == "task-24"
    assert writes == [
        {
            "repo": "codefromkarl/stardrifter",
            "issue_number": 24,
            "status": "done",
            "decision_required": False,
        }
    ]


def test_run_worker_cycle_records_pull_request_link_when_commit_payload_provides_one():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-26",
                title="pr link persistence",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
                repo="codefromkarl/stardrifter",
                source_issue_number=26,
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-26": [
                WorkTarget(
                    work_id="task-26",
                    target_path="src/stardrifter_engine/runtime.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    from stardrifter_orchestration_mvp.models import VerificationEvidence

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True,
            summary="patched files",
            result_payload_json={
                "pull_request": {
                    "pull_number": 81,
                    "pull_url": "https://github.com/codefromkarl/stardrifter/pull/81",
                }
            },
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
    )

    assert result.claimed_work_id == "task-26"
    link = repository.get_pull_request_link("task-26")
    assert link is not None
    assert link["pull_number"] == 81
    assert link["pull_url"] == "https://github.com/codefromkarl/stardrifter/pull/81"


def test_run_worker_cycle_syncs_blocked_needs_decision_to_github():
    writes: list[dict[str, object]] = []
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-25",
                title="github blocked sync",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
                repo="codefromkarl/stardrifter",
                source_issue_number=25,
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-25": [
                WorkTarget(
                    work_id="task-25",
                    target_path="docs/domains/06-projection-save-replay/execution-plan.md",
                    target_type="doc",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=False,
            summary="需要人类决策",
            blocked_reason="missing-approval",
            decision_required=True,
            result_payload_json={
                "outcome": "needs_decision",
                "reason_code": "missing-approval",
            },
        ),
        verifier=lambda work_item, workspace_path=None: (_ for _ in ()).throw(
            AssertionError("verifier should not run")
        ),
        github_writeback=lambda **kwargs: writes.append(kwargs),
    )

    assert result.claimed_work_id == "task-25"
    assert writes == [
        {
            "repo": "codefromkarl/stardrifter",
            "issue_number": 25,
            "status": "blocked",
            "decision_required": True,
        }
    ]


def test_run_worker_cycle_blocks_already_satisfied_without_commit_evidence():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-6",
                title="already satisfied",
                lane="Lane 02",
                wave="wave-2",
                status="pending",
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-6": [
                WorkTarget(
                    work_id="task-6",
                    target_path="src/stardrifter_engine/campaign/runtime.py",
                    target_type="file",
                    owner_lane="Lane 02",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-2"},
        frozen_prefixes=("docs/authority/",),
    )
    verifier_calls: list[str] = []
    commit_calls: list[str] = []

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True,
            summary="already there",
            result_payload_json={
                "outcome": "already_satisfied",
                "reason_code": "already_has_backend_skeleton",
                "changed_paths": [],
            },
        ),
        verifier=lambda work_item, workspace_path=None: verifier_calls.append(
            work_item.id
        ),  # type: ignore[return-value]
        committer=lambda work_item, execution_result, workspace_path=None: (
            commit_calls.append(work_item.id)
        ),  # type: ignore[return-value]
    )

    assert result.claimed_work_id == "task-6"
    assert repository.work_items_by_id["task-6"].status == "blocked"
    assert (
        repository.work_items_by_id["task-6"].blocked_reason
        == "already_satisfied_without_commit_evidence"
    )
    assert repository.work_items_by_id["task-6"].decision_required is True
    assert verifier_calls == []
    assert commit_calls == []
    assert repository.execution_runs[0].status == "blocked"
    assert repository.execution_runs[0].result_payload_json == {
        "outcome": "already_satisfied",
        "reason_code": "already_has_backend_skeleton",
        "changed_paths": [],
    }
    assert repository.verification_evidence == []


def test_run_worker_cycle_allows_already_satisfied_with_existing_commit_evidence():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-6b",
                title="already satisfied with proof",
                lane="Lane 02",
                wave="wave-2",
                status="pending",
                repo="codefromkarl/stardrifter",
                source_issue_number=6,
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-6b": [
                WorkTarget(
                    work_id="task-6b",
                    target_path="src/stardrifter_engine/campaign/runtime.py",
                    target_type="file",
                    owner_lane="Lane 02",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    repository.record_commit_link(
        work_id="task-6b",
        repo="codefromkarl/stardrifter",
        issue_number=6,
        commit_sha="abc123",
        commit_message="chore(task-6): complete task #6",
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-2"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True,
            summary="already there",
            result_payload_json={
                "outcome": "already_satisfied",
                "reason_code": "already_has_backend_skeleton",
                "changed_paths": [],
            },
        ),
        verifier=lambda work_item, workspace_path=None: (_ for _ in ()).throw(
            AssertionError("verifier should not run for already_satisfied")
        ),
    )

    assert result.claimed_work_id == "task-6b"
    assert repository.work_items_by_id["task-6b"].status == "done"
    assert repository.work_items_by_id["task-6b"].blocked_reason is None
    assert repository.execution_runs[0].status == "done"


def test_run_worker_cycle_blocks_when_committer_returns_uncommitted_without_reason():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-6c",
                title="missing commit evidence",
                lane="Lane 02",
                wave="wave-2",
                status="pending",
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "task-6c": [
                WorkTarget(
                    work_id="task-6c",
                    target_path="src/stardrifter_engine/campaign/runtime.py",
                    target_type="file",
                    owner_lane="Lane 02",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-2"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True,
            summary="claimed done but no commit",
            result_payload_json={
                "outcome": "done",
                "changed_paths": ["src/stardrifter_engine/campaign/runtime.py"],
            },
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
        committer=lambda work_item, execution_result, workspace_path=None: CommitResult(
            committed=False,
            commit_sha=None,
            blocked_reason=None,
            summary="no commit produced",
            commit_message=None,
        ),
    )

    assert result.claimed_work_id == "task-6c"
    assert repository.work_items_by_id["task-6c"].status == "blocked"
    assert (
        repository.work_items_by_id["task-6c"].blocked_reason
        == "missing_commit_evidence"
    )


def test_run_worker_cycle_creates_and_releases_work_claim_with_workspace_path(tmp_path):
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-7",
                title="[04-DOC] isolated docs task",
                lane="Lane 04",
                wave="unassigned",
                status="pending",
                planned_paths=("docs/domains/04-encounter-mediation/",),
            ),
        ],
        dependencies=[],
        targets_by_work_id={},
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"unassigned"},
        frozen_prefixes=("docs/authority/",),
    )
    calls: dict[str, object] = {}

    class FakeWorkspaceManager:
        repo_root = Path("/repo/root")
        worktree_root = tmp_path

        def prepare(self, *, work_item, worker_name, repository):
            calls["prepare"] = (work_item.id, worker_name)
            return tmp_path / "task-7"

        def release(self, *, work_item, repository):
            calls["release"] = work_item.id
            repository.delete_work_claim(work_item.id)

    def executor(work_item, workspace_path=None):
        calls["executor_path"] = workspace_path
        return ExecutionResult(success=True, summary="done")

    def verifier(work_item, workspace_path=None):
        calls["verifier_path"] = workspace_path
        from stardrifter_orchestration_mvp.models import VerificationEvidence

        return VerificationEvidence(
            work_id=work_item.id,
            check_type="noop",
            command="noop",
            passed=True,
            output_digest="ok",
        )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=executor,
        verifier=verifier,
        workspace_manager=FakeWorkspaceManager(),
    )

    assert result.claimed_work_id == "task-7"
    assert calls["prepare"] == ("task-7", "worker-a")
    assert calls["release"] == "task-7"
    assert calls["executor_path"] == tmp_path / "task-7"
    assert calls["verifier_path"] == tmp_path / "task-7"
    assert repository.list_work_claims() == []


def test_run_worker_cycle_renews_claim_after_workspace_prepare(tmp_path):
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-13",
                title="renew lease",
                lane="Lane 04",
                wave="unassigned",
                status="pending",
                planned_paths=("docs/domains/04-encounter-mediation/",),
            ),
        ],
        dependencies=[],
        targets_by_work_id={},
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"unassigned"},
        frozen_prefixes=("docs/authority/",),
    )
    renewed_tokens: list[str] = []

    class RenewingRepository(InMemoryControlPlaneRepository):
        def renew_work_claim(self, work_id: str, *, lease_token: str):
            renewed_tokens.append(lease_token)
            return super().renew_work_claim(work_id, lease_token=lease_token)

    repository = RenewingRepository(
        work_items=repository.work_items,
        dependencies=repository.dependencies,
        targets_by_work_id=repository.targets_by_work_id,
    )

    class FakeWorkspaceManager:
        repo_root = Path("/repo/root")
        worktree_root = tmp_path

        def prepare(self, *, work_item, worker_name, repository):
            return tmp_path / "task-13"

        def release(self, *, work_item, repository):
            repository.delete_work_claim(work_item.id)

    def verifier(work_item, workspace_path=None):
        from stardrifter_orchestration_mvp.models import VerificationEvidence

        return VerificationEvidence(
            work_id=work_item.id,
            check_type="noop",
            command="noop",
            passed=True,
            output_digest="ok",
        )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True, summary="done"
        ),
        verifier=verifier,
        workspace_manager=FakeWorkspaceManager(),
    )

    assert result.claimed_work_id == "task-13"
    assert len(renewed_tokens) == 1


def test_run_worker_cycle_renews_claim_multiple_times_during_long_executor(tmp_path):
    base_repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-15",
                title="long executor renewal",
                lane="Lane 04",
                wave="unassigned",
                status="pending",
                planned_paths=("docs/domains/04-encounter-mediation/",),
            ),
        ],
        dependencies=[],
        targets_by_work_id={},
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"unassigned"},
        frozen_prefixes=("docs/authority/",),
    )
    renewed_tokens: list[str] = []

    class RenewingRepository(InMemoryControlPlaneRepository):
        def renew_work_claim(self, work_id: str, *, lease_token: str):
            renewed_tokens.append(lease_token)
            return super().renew_work_claim(work_id, lease_token=lease_token)

    repository = RenewingRepository(
        work_items=base_repository.work_items,
        dependencies=base_repository.dependencies,
        targets_by_work_id=base_repository.targets_by_work_id,
    )

    class FakeWorkspaceManager:
        repo_root = Path("/repo/root")
        worktree_root = tmp_path

        def prepare(self, *, work_item, worker_name, repository):
            return tmp_path / "task-15"

        def release(self, *, work_item, repository):
            repository.delete_work_claim(work_item.id)

    def executor(work_item, workspace_path=None, heartbeat=None):
        assert heartbeat is not None
        heartbeat()
        heartbeat()
        return ExecutionResult(success=True, summary="done")

    def verifier(work_item, workspace_path=None):
        from stardrifter_orchestration_mvp.models import VerificationEvidence

        return VerificationEvidence(
            work_id=work_item.id,
            check_type="noop",
            command="noop",
            passed=True,
            output_digest="ok",
        )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=executor,
        verifier=verifier,
        workspace_manager=FakeWorkspaceManager(),
    )

    assert result.claimed_work_id == "task-15"
    assert len(renewed_tokens) == 3


def test_run_worker_cycle_claims_second_candidate_when_repository_rejects_first():
    class LateConflictRepository(InMemoryControlPlaneRepository):
        def claim_ready_work_item(
            self,
            work_id: str,
            *,
            worker_name: str,
            workspace_path: str,
            branch_name: str,
            claimed_paths: tuple[str, ...],
        ):
            if work_id == "task-8":
                return None
            return super().claim_ready_work_item(
                work_id,
                worker_name=worker_name,
                workspace_path=workspace_path,
                branch_name=branch_name,
                claimed_paths=claimed_paths,
            )

    repository = LateConflictRepository(
        work_items=[
            WorkItem(
                id="task-8",
                title="late conflict",
                lane="Lane 04",
                wave="wave-5",
                status="pending",
                planned_paths=("src/stardrifter_engine/projections/",),
            ),
            WorkItem(
                id="task-9",
                title="fallback candidate",
                lane="Lane 04",
                wave="wave-5",
                status="pending",
                planned_paths=("src/stardrifter_engine/runtime.py",),
            ),
        ],
        dependencies=[],
        targets_by_work_id={},
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )
    executor_calls: list[str] = []
    verifier_calls: list[str] = []

    def verifier(work_item, workspace_path=None):
        verifier_calls.append(work_item.id)
        from stardrifter_orchestration_mvp.models import VerificationEvidence

        return VerificationEvidence(
            work_id=work_item.id,
            check_type="noop",
            command="noop",
            passed=True,
            output_digest="ok",
        )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: (
            executor_calls.append(work_item.id)
            or ExecutionResult(success=True, summary="done")
        ),
        verifier=verifier,
    )

    assert result.claimed_work_id == "task-9"
    assert executor_calls == ["task-9"]
    assert verifier_calls == ["task-9"]
    assert repository.work_items_by_id["task-8"].status == "ready"
    assert repository.work_items_by_id["task-9"].status == "done"


def test_run_worker_cycle_records_claim_before_workspace_prepare(tmp_path):
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-9",
                title="[04-DOC] claim before prepare",
                lane="Lane 04",
                wave="unassigned",
                status="pending",
                planned_paths=("docs/domains/04-encounter-mediation/",),
            ),
        ],
        dependencies=[],
        targets_by_work_id={},
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"unassigned"},
        frozen_prefixes=("docs/authority/",),
    )
    observed_claims: list[list[WorkClaim]] = []

    class FakeWorkspaceManager:
        repo_root = Path("/repo/root")
        worktree_root = tmp_path

        def prepare(self, *, work_item, worker_name, repository):
            observed_claims.append(repository.list_work_claims())
            return tmp_path / "task-9"

        def release(self, *, work_item, repository):
            repository.delete_work_claim(work_item.id)

    def verifier(work_item, workspace_path=None):
        from stardrifter_orchestration_mvp.models import VerificationEvidence

        return VerificationEvidence(
            work_id=work_item.id,
            check_type="noop",
            command="noop",
            passed=True,
            output_digest="ok",
        )

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True, summary="done"
        ),
        verifier=verifier,
        workspace_manager=FakeWorkspaceManager(),
    )

    assert result.claimed_work_id == "task-9"
    assert len(observed_claims) == 1
    assert len(observed_claims[0]) == 1
    claim = observed_claims[0][0]
    assert claim.work_id == "task-9"
    assert claim.worker_name == "worker-a"
    assert claim.workspace_path == str(tmp_path / "task-9-04-doc")
    assert claim.branch_name == "task/9-04-doc"
    assert claim.lease_token is not None
    assert claim.lease_expires_at is not None
    assert claim.claimed_paths == ("docs/domains/04-encounter-mediation/",)


def test_run_worker_cycle_rolls_back_claim_and_status_when_workspace_prepare_fails(
    tmp_path,
):
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-14",
                title="prepare failure rollback",
                lane="Lane 04",
                wave="unassigned",
                status="pending",
                planned_paths=("docs/domains/04-encounter-mediation/",),
            ),
        ],
        dependencies=[],
        targets_by_work_id={},
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"unassigned"},
        frozen_prefixes=("docs/authority/",),
    )
    observed_claims: list[list[WorkClaim]] = []

    class FailingWorkspaceManager:
        repo_root = Path("/repo/root")
        worktree_root = tmp_path

        def prepare(self, *, work_item, worker_name, repository):
            observed_claims.append(repository.list_work_claims())
            raise RuntimeError("prepare failed")

        def release(self, *, work_item, repository):
            raise AssertionError("release should not run after prepare failure")

    with pytest.raises(RuntimeError, match="prepare failed"):
        run_worker_cycle(
            repository=repository,
            context=context,
            worker_name="worker-a",
            executor=lambda work_item, workspace_path=None: ExecutionResult(
                success=True, summary="done"
            ),
            verifier=lambda work_item, workspace_path=None: (_ for _ in ()).throw(
                AssertionError("verifier should not run")
            ),
            workspace_manager=FailingWorkspaceManager(),
        )

    assert len(observed_claims) == 1
    assert len(observed_claims[0]) == 1
    assert observed_claims[0][0].work_id == "task-14"
    assert repository.work_items_by_id["task-14"].status == "ready"
    assert repository.list_work_claims() == []
    assert repository.execution_runs == []
    assert repository.verification_evidence == []


def test_run_worker_cycle_prefers_active_work_items_view_when_repository_supports_it():
    class ActiveOnlyRepository(InMemoryControlPlaneRepository):
        def list_active_work_items(self):
            return [self.work_items_by_id["task-11"]]

    repository = ActiveOnlyRepository(
        work_items=[
            WorkItem(
                id="task-10",
                title="not active",
                lane="Lane 04",
                wave="wave-5",
                status="ready",
                planned_paths=("src/not_active.py",),
            ),
            WorkItem(
                id="task-11",
                title="active candidate",
                lane="Lane 04",
                wave="wave-5",
                status="ready",
                planned_paths=("src/active.py",),
            ),
        ],
        dependencies=[],
        targets_by_work_id={},
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-5"},
        frozen_prefixes=("docs/authority/",),
    )
    executed: list[str] = []

    result = run_worker_cycle(
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: (
            executed.append(work_item.id)
            or ExecutionResult(success=True, summary="done")
        ),
        verifier=lambda work_item, workspace_path=None: __import__(
            "stardrifter_orchestration_mvp.models", fromlist=["VerificationEvidence"]
        ).VerificationEvidence(
            work_id=work_item.id,
            check_type="noop",
            command="noop",
            passed=True,
            output_digest="ok",
        ),
    )

    assert result.claimed_work_id == "task-11"
    assert executed == ["task-11"]
