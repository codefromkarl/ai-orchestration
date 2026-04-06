import threading
import time
from typing import Any, cast
from uuid import uuid4

import pytest
import taskplane.repository as repository_module
from datetime import datetime, timezone

from taskplane.models import (
    ApprovalEvent,
    EpicExecutionState,
    ExecutionRun,
    OperatorRequest,
    ProgramStory,
    QueueEvaluation,
    StoryVerificationRun,
    StoryIntegrationRun,
    StoryPullRequestLink,
    TaskSpecDraft,
    VerificationEvidence,
    WorkClaim,
    WorkDependency,
    WorkItem,
)
from taskplane.repository import (
    InMemoryControlPlaneRepository,
    PostgresControlPlaneRepository,
)
from taskplane.repository._postgres_row_mapping import (
    row_to_operator_request,
    row_to_program_story,
    row_to_work_claim,
    row_to_work_item,
    value,
    value_optional,
)

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]


def test_in_memory_repository_sync_ready_states_promotes_pending_items():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-1",
                title="done upstream",
                lane="Lane 06",
                wave="wave-5",
                status="done",
            ),
            WorkItem(
                id="task-2",
                title="should become ready",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
            ),
            WorkItem(
                id="task-3",
                title="still blocked",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
            ),
        ],
        dependencies=[
            WorkDependency(work_id="task-2", depends_on_work_id="task-1"),
            WorkDependency(work_id="task-3", depends_on_work_id="task-2"),
        ],
        targets_by_work_id={},
    )

    repository.sync_ready_states()

    assert repository.work_items_by_id["task-2"].status == "ready"
    assert repository.work_items_by_id["task-3"].status == "pending"


def test_in_memory_repository_sync_ready_states_stages_recovery_derivation_and_apply(
    monkeypatch,
):
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )
    calls: list[object] = []

    monkeypatch.setattr(
        repository,
        "_repair_or_recover_ready_state_inputs",
        lambda: calls.append("repair_or_recover"),
        raising=False,
    )
    monkeypatch.setattr(
        repository,
        "_derive_ready_candidate_ids",
        lambda: (calls.append("derive_ready_ids") or {"task-2"}),
        raising=False,
    )
    monkeypatch.setattr(
        repository,
        "_apply_ready_state_transitions",
        lambda ready_ids: calls.append(("apply_transitions", ready_ids)),
        raising=False,
    )

    repository.sync_ready_states()

    assert calls == [
        "repair_or_recover",
        "derive_ready_ids",
        ("apply_transitions", {"task-2"}),
    ]


def test_repository_module_exports_narrower_protocols_for_runtime_boundaries():
    expected_exports = {
        "ReadyStateSyncRepository",
        "SupervisorSchedulingRepository",
        "WorkStateRepository",
        "ClaimRepository",
        "ExecutionRepository",
        "WorkerRepository",
        "StoryRepository",
        "EpicRepository",
        "StoryDecompositionRepository",
        "EpicDecompositionRepository",
    }

    for name in expected_exports:
        assert hasattr(repository_module, name), name


def test_in_memory_repository_sync_ready_states_respects_story_dependencies():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-44",
                title="story 21 task",
                lane="Lane 01",
                wave="wave-1",
                status="pending",
                source_issue_number=44,
                story_issue_numbers=(21,),
            ),
            WorkItem(
                id="issue-46",
                title="story 24 task",
                lane="Lane 02",
                wave="wave-2",
                status="pending",
                source_issue_number=46,
                story_issue_numbers=(24,),
            ),
        ],
        dependencies=[],
        story_dependencies=[(24, 21)],
        targets_by_work_id={},
    )

    repository.sync_ready_states()

    assert repository.work_items_by_id["issue-44"].status == "ready"
    assert repository.work_items_by_id["issue-46"].status == "pending"


def test_in_memory_repository_sync_ready_states_demotes_stale_ready_items():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-46",
                title="story 24 task",
                lane="Lane 02",
                wave="wave-2",
                status="ready",
                source_issue_number=46,
                story_issue_numbers=(24,),
            ),
        ],
        dependencies=[],
        story_dependencies=[(24, 23)],
        targets_by_work_id={},
    )

    repository.sync_ready_states()

    assert repository.work_items_by_id["issue-46"].status == "pending"


def test_in_memory_repository_sync_ready_states_respects_future_next_eligible_at():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-19",
                title="future retry",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
                next_eligible_at="2999-01-01T00:00:00+00:00",
            )
        ],
        dependencies=[],
        targets_by_work_id={},
    )

    repository.sync_ready_states()

    assert repository.work_items_by_id["task-19"].status == "pending"


def test_in_memory_repository_sync_ready_states_promotes_pending_item_after_retry_window():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-20",
                title="retry eligible",
                lane="Lane 06",
                wave="wave-5",
                status="pending",
                next_eligible_at="2000-01-01T00:00:00+00:00",
            )
        ],
        dependencies=[],
        targets_by_work_id={},
    )

    repository.sync_ready_states()

    assert repository.work_items_by_id["task-20"].status == "ready"


def test_postgres_repository_sync_ready_states_filters_by_next_eligible_at_in_sql():
    connection = FakeConnection()
    repository = PostgresControlPlaneRepository(connection)

    repository.sync_ready_states()

    executed_sql = "\n".join(connection.executed_sql)
    assert "wi.next_eligible_at IS NULL OR wi.next_eligible_at <= NOW()" in executed_sql


def test_in_memory_repository_sync_ready_states_recovers_abandoned_in_progress_item_after_expired_lease():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-12",
                title="abandoned work",
                lane="Lane 06",
                wave="wave-5",
                status="in_progress",
            )
        ],
        dependencies=[],
        targets_by_work_id={},
        work_claims=[
            WorkClaim(
                work_id="task-12",
                worker_name="worker-a",
                workspace_path="/tmp/task-12",
                branch_name="task/12-abandoned-work",
                lease_token="expired-lease",
                lease_expires_at="2000-01-01T00:00:00+00:00",
            )
        ],
    )

    repository.sync_ready_states()

    assert repository.work_items_by_id["task-12"].status == "ready"


def test_in_memory_repository_sync_ready_states_keeps_active_in_progress_item_in_progress():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-13",
                title="active work",
                lane="Lane 06",
                wave="wave-5",
                status="in_progress",
            )
        ],
        dependencies=[],
        targets_by_work_id={},
        work_claims=[
            WorkClaim(
                work_id="task-13",
                worker_name="worker-a",
                workspace_path="/tmp/task-13",
                branch_name="task/13-active-work",
                lease_token="active-lease",
                lease_expires_at="2999-01-01T00:00:00+00:00",
            )
        ],
    )

    repository.sync_ready_states()

    assert repository.work_items_by_id["task-13"].status == "in_progress"


def test_postgres_repository_claim_ready_work_item_uses_skip_locked():
    connection = FakeConnection(
        fetchone_results=[
            {
                "id": "task-2",
                "title": "safe cleanup",
                "lane": "Lane 06",
                "wave": "wave-5",
                "status": "in_progress",
                "complexity": "medium",
            }
        ]
    )
    repository = PostgresControlPlaneRepository(connection)

    claimed = repository.claim_ready_work_item(
        "task-2",
        worker_name="worker-a",
        workspace_path="/tmp/task-2",
        branch_name="task/2-safe-cleanup",
        claimed_paths=("src/stardrifter_engine/projections/",),
    )

    assert claimed is not None
    assert claimed.id == "task-2"
    executed_sql = "\n".join(connection.executed_sql)
    assert "FOR UPDATE SKIP LOCKED" in executed_sql
    assert "UPDATE work_item" in executed_sql
    assert "INSERT INTO work_claim" in executed_sql
    assert "jsonb_array_elements_text" in executed_sql
    assert "lease_token" in executed_sql
    assert "lease_expires_at" in executed_sql


def test_postgres_repository_sync_ready_states_recovers_abandoned_in_progress_items_in_sql():
    connection = FakeConnection()
    repository = PostgresControlPlaneRepository(connection)

    repository.sync_ready_states()

    executed_sql = "\n".join(connection.executed_sql)
    assert "wi.status = 'in_progress'" in executed_sql
    assert "NOT EXISTS (" in executed_sql
    assert "FROM work_claim wc" in executed_sql
    assert "wc.lease_expires_at IS NULL OR wc.lease_expires_at > NOW()" in executed_sql


def test_postgres_repository_sync_ready_states_excludes_waiting_sessions_in_sql():
    connection = FakeConnection()
    repository = PostgresControlPlaneRepository(connection)

    repository.sync_ready_states()

    executed_sql = "\n".join(connection.executed_sql)
    assert "FROM execution_session es" in executed_sql
    assert "es.work_id = wi.id" in executed_sql
    assert "es.status IN ('suspended', 'waiting_internal', 'waiting_external')" in executed_sql


def test_postgres_repository_sync_ready_states_stages_repair_derivation_and_apply(
    monkeypatch,
):
    connection = FakeConnection()
    repository = PostgresControlPlaneRepository(connection)
    calls: list[object] = []

    monkeypatch.setattr(
        repository,
        "_repair_or_recover_ready_state_inputs",
        lambda cursor: calls.append(("repair_or_recover", cursor)),
        raising=False,
    )
    monkeypatch.setattr(
        repository,
        "_derive_ready_candidate_ids",
        lambda cursor: (calls.append(("derive_ready_ids", cursor)) or {"task-2"}),
        raising=False,
    )
    monkeypatch.setattr(
        repository,
        "_apply_ready_state_transitions",
        lambda cursor, ready_ids: calls.append(("apply_transitions", cursor, ready_ids)),
        raising=False,
    )

    repository.sync_ready_states()

    assert [call[0] for call in calls] == [
        "repair_or_recover",
        "derive_ready_ids",
        "apply_transitions",
    ]
    assert calls[-1][2] == {"task-2"}


def test_in_memory_repository_claim_ready_work_item_rejects_overlapping_claimed_paths():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-2",
                title="safe cleanup",
                lane="Lane 06",
                wave="wave-5",
                status="ready",
                planned_paths=("src/stardrifter_engine/projections/",),
            )
        ],
        dependencies=[],
        targets_by_work_id={},
        work_claims=[
            WorkClaim(
                work_id="task-1",
                worker_name="worker-b",
                workspace_path="/tmp/task-1",
                branch_name="task/1-upstream",
                claimed_paths=("src/stardrifter_engine/",),
            )
        ],
    )

    claimed = repository.claim_ready_work_item(
        "task-2",
        worker_name="worker-a",
        workspace_path="/tmp/task-2",
        branch_name="task/2-safe-cleanup",
        claimed_paths=("src/stardrifter_engine/projections/",),
    )

    assert claimed is None
    assert repository.work_items_by_id["task-2"].status == "ready"
    assert repository.list_work_claims() == [
        WorkClaim(
            work_id="task-1",
            worker_name="worker-b",
            workspace_path="/tmp/task-1",
            branch_name="task/1-upstream",
            claimed_paths=("src/stardrifter_engine/",),
        )
    ]


def test_in_memory_repository_claim_ready_work_item_ignores_expired_conflicting_claims():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-2",
                title="safe cleanup",
                lane="Lane 06",
                wave="wave-5",
                status="ready",
                planned_paths=("src/stardrifter_engine/projections/",),
            )
        ],
        dependencies=[],
        targets_by_work_id={},
        work_claims=[
            WorkClaim(
                work_id="task-1",
                worker_name="worker-b",
                workspace_path="/tmp/task-1",
                branch_name="task/1-upstream",
                lease_token="expired-lease",
                lease_expires_at="2000-01-01T00:00:00+00:00",
                claimed_paths=("src/stardrifter_engine/",),
            )
        ],
    )

    claimed = repository.claim_ready_work_item(
        "task-2",
        worker_name="worker-a",
        workspace_path="/tmp/task-2",
        branch_name="task/2-safe-cleanup",
        claimed_paths=("src/stardrifter_engine/projections/",),
    )

    assert claimed is not None
    assert claimed.id == "task-2"


def test_in_memory_repository_claim_ready_work_item_skips_task_with_successful_done_run():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-82",
                title="task 82",
                lane="Lane 01",
                wave="unassigned",
                status="ready",
            )
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

    claimed = repository.claim_ready_work_item(
        "issue-82",
        worker_name="worker-b",
        workspace_path="/tmp/issue-82",
        branch_name="story/23",
        claimed_paths=(),
    )

    assert claimed is None
    assert repository.work_items_by_id["issue-82"].status == "ready"


def test_in_memory_repository_finalize_work_attempt_allows_later_blocked_result():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-82",
                title="task 82",
                lane="Lane 01",
                wave="unassigned",
                status="done",
            )
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

    repository.finalize_work_attempt(
        work_id="issue-82",
        status="blocked",
        blocked_reason="invalid-result-payload",
        execution_run=ExecutionRun(
            work_id="issue-82",
            worker_name="worker-b",
            status="blocked",
            summary="bad payload",
        ),
    )

    assert repository.work_items_by_id["issue-82"].status == "blocked"
    assert repository.work_items_by_id["issue-82"].blocked_reason == "invalid-result-payload"


def test_in_memory_repository_lists_only_active_work_claims():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        work_claims=[
            WorkClaim(
                work_id="task-active",
                worker_name="worker-a",
                workspace_path="/tmp/task-active",
                branch_name="task/active",
                lease_token="active-lease",
                lease_expires_at="2999-01-01T00:00:00+00:00",
            ),
            WorkClaim(
                work_id="task-expired",
                worker_name="worker-b",
                workspace_path="/tmp/task-expired",
                branch_name="task/expired",
                lease_token="expired-lease",
                lease_expires_at="2000-01-01T00:00:00+00:00",
            ),
        ],
    )

    claims = repository.list_active_work_claims()

    assert [claim.work_id for claim in claims] == ["task-active"]


def test_in_memory_repository_renew_work_claim_updates_expiry_for_matching_token():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        work_claims=[
            WorkClaim(
                work_id="task-2",
                worker_name="worker-a",
                workspace_path="/tmp/task-2",
                branch_name="task/2-safe-cleanup",
                lease_token="lease-123",
                lease_expires_at="2999-01-01T00:00:00+00:00",
            )
        ],
    )

    renewed = repository.renew_work_claim("task-2", lease_token="lease-123")

    assert renewed is not None
    assert renewed.lease_token == "lease-123"
    assert renewed.lease_expires_at != "2999-01-01T00:00:00+00:00"


def test_in_memory_repository_renew_work_claim_rejects_wrong_token():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        work_claims=[
            WorkClaim(
                work_id="task-2",
                worker_name="worker-a",
                workspace_path="/tmp/task-2",
                branch_name="task/2-safe-cleanup",
                lease_token="lease-123",
                lease_expires_at="2999-01-01T00:00:00+00:00",
            )
        ],
    )

    renewed = repository.renew_work_claim("task-2", lease_token="wrong-token")

    assert renewed is None


def test_postgres_repository_claim_ready_work_item_filters_expired_claims_in_sql():
    connection = FakeConnection(
        fetchone_results=[
            {
                "id": "task-2",
                "title": "safe cleanup",
                "lane": "Lane 06",
                "wave": "wave-5",
                "status": "in_progress",
                "complexity": "medium",
            }
        ]
    )
    repository = PostgresControlPlaneRepository(connection)

    repository.claim_ready_work_item(
        "task-2",
        worker_name="worker-a",
        workspace_path="/tmp/task-2",
        branch_name="task/2-safe-cleanup",
        claimed_paths=("src/stardrifter_engine/projections/",),
    )

    executed_sql = "\n".join(connection.executed_sql)
    assert "lease_expires_at" in executed_sql
    assert "lease_expires_at > NOW()" in executed_sql


def test_postgres_repository_renew_work_claim_uses_token_match():
    connection = FakeConnection(
        fetchone_results=[
            {
                "work_id": "task-2",
                "worker_name": "worker-a",
                "workspace_path": "/tmp/task-2",
                "branch_name": "task/2-safe-cleanup",
                "lease_token": "lease-123",
                "lease_expires_at": "2999-01-01T00:00:00+00:00",
                "claimed_paths": [],
            }
        ]
    )
    repository = PostgresControlPlaneRepository(connection)

    renewed = repository.renew_work_claim("task-2", lease_token="lease-123")

    assert renewed is not None
    executed_sql = "\n".join(connection.executed_sql)
    assert "UPDATE work_claim" in executed_sql
    assert "lease_token = %s" in executed_sql


def test_in_memory_repository_records_and_queries_commit_link():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-60",
                title="task 60",
                lane="Lane 01",
                wave="unassigned",
                status="done",
                repo="codefromkarl/stardrifter",
                source_issue_number=60,
            )
        ],
        dependencies=[],
        targets_by_work_id={},
    )

    repository.record_commit_link(
        work_id="issue-60",
        repo="codefromkarl/stardrifter",
        issue_number=60,
        commit_sha="abc123",
        commit_message="chore(task-60): complete task #60",
    )

    link = repository.get_commit_link("issue-60")

    assert link is not None
    assert link["commit_sha"] == "abc123"
    assert link["issue_number"] == 60


def test_in_memory_repository_rejects_duplicate_commit_link_for_same_work_item():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-61",
                title="task 61",
                lane="Lane 01",
                wave="unassigned",
                status="done",
                repo="codefromkarl/stardrifter",
                source_issue_number=61,
            )
        ],
        dependencies=[],
        targets_by_work_id={},
    )

    repository.record_commit_link(
        work_id="issue-61",
        repo="codefromkarl/stardrifter",
        issue_number=61,
        commit_sha="abc123",
        commit_message="chore(task-61): complete task #61",
    )

    with pytest.raises(ValueError, match="commit link already exists"):
        repository.record_commit_link(
            work_id="issue-61",
            repo="codefromkarl/stardrifter",
            issue_number=61,
            commit_sha="def456",
            commit_message="chore(task-61): complete task #61 again",
        )


def test_in_memory_repository_records_and_queries_pull_request_link():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-62",
                title="task 62",
                lane="Lane 01",
                wave="unassigned",
                status="done",
                repo="codefromkarl/stardrifter",
                source_issue_number=62,
            )
        ],
        dependencies=[],
        targets_by_work_id={},
    )

    repository.record_pull_request_link(
        work_id="issue-62",
        repo="codefromkarl/stardrifter",
        issue_number=62,
        pull_number=77,
        pull_url="https://github.com/codefromkarl/stardrifter/pull/77",
    )

    link = repository.get_pull_request_link("issue-62")

    assert link is not None
    assert link["pull_number"] == 77
    assert link["pull_url"] == "https://github.com/codefromkarl/stardrifter/pull/77"


def test_in_memory_repository_rejects_duplicate_pull_request_link_for_same_work_item():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-63",
                title="task 63",
                lane="Lane 01",
                wave="unassigned",
                status="done",
                repo="codefromkarl/stardrifter",
                source_issue_number=63,
            )
        ],
        dependencies=[],
        targets_by_work_id={},
    )

    repository.record_pull_request_link(
        work_id="issue-63",
        repo="codefromkarl/stardrifter",
        issue_number=63,
        pull_number=78,
        pull_url="https://github.com/codefromkarl/stardrifter/pull/78",
    )

    with pytest.raises(ValueError, match="pull request link already exists"):
        repository.record_pull_request_link(
            work_id="issue-63",
            repo="codefromkarl/stardrifter",
            issue_number=63,
            pull_number=79,
            pull_url="https://github.com/codefromkarl/stardrifter/pull/79",
        )


def test_in_memory_repository_records_story_integration_run():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )

    record_id = repository.record_story_integration_run(
        StoryIntegrationRun(
            repo="codefromkarl/stardrifter",
            story_issue_number=41,
            merged=True,
            promoted=False,
            merge_commit_sha="abc123",
            summary="merged story/41 into main",
        )
    )

    assert record_id == 1
    assert len(repository.story_integration_runs) == 1
    assert repository.story_integration_runs[0].story_issue_number == 41


def test_postgres_repository_records_story_integration_run_sql():
    connection = FakeConnection(
        fetchone_results=[{"id": 7}],
    )
    repository = PostgresControlPlaneRepository(connection)

    record_id = repository.record_story_integration_run(
        StoryIntegrationRun(
            repo="codefromkarl/stardrifter",
            story_issue_number=41,
            merged=True,
            promoted=False,
            merge_commit_sha="abc123",
            summary="merged story/41 into main",
        )
    )

    assert record_id == 7
    executed_sql = "\n".join(connection.executed_sql)
    assert "INSERT INTO story_integration_run" in executed_sql


def test_in_memory_repository_records_story_verification_run():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )

    record_id = repository.record_story_verification_run(
        StoryVerificationRun(
            repo="codefromkarl/stardrifter",
            story_issue_number=41,
            check_type="pytest",
            command="python3 -m pytest -q tests/integration/test_story_41.py",
            passed=True,
            summary="story verification passed",
            output_digest="ok",
        )
    )

    assert record_id == 1
    assert len(repository.story_verification_runs) == 1
    assert repository.story_verification_runs[0].story_issue_number == 41


def test_postgres_repository_records_story_verification_run_sql():
    connection = FakeConnection(
        fetchone_results=[{"id": 11}],
    )
    repository = PostgresControlPlaneRepository(connection)

    record_id = repository.record_story_verification_run(
        StoryVerificationRun(
            repo="codefromkarl/stardrifter",
            story_issue_number=41,
            check_type="pytest",
            command="python3 -m pytest -q tests/integration/test_story_41.py",
            passed=True,
            summary="story verification passed",
            output_digest="ok",
        )
    )

    assert record_id == 11
    executed_sql = "\n".join(connection.executed_sql)
    assert "INSERT INTO story_verification_run" in executed_sql


def test_in_memory_repository_upserts_and_reads_epic_execution_state():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )

    repository.upsert_epic_execution_state(
        EpicExecutionState(
            repo="codefromkarl/stardrifter",
            epic_issue_number=13,
            status="active",
            completed_story_issue_numbers=(41,),
            blocked_story_issue_numbers=(),
            remaining_story_issue_numbers=(42,),
            blocked_reason_code="epic_incomplete",
            operator_attention_required=False,
            last_progress_at=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
            stalled_since=datetime(2026, 3, 1, 13, 0, tzinfo=timezone.utc),
        )
    )

    assert repository.get_epic_execution_state(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    ) == EpicExecutionState(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        status="active",
        completed_story_issue_numbers=(41,),
        blocked_story_issue_numbers=(),
        remaining_story_issue_numbers=(42,),
        blocked_reason_code="epic_incomplete",
        operator_attention_required=False,
        last_progress_at=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        stalled_since=datetime(2026, 3, 1, 13, 0, tzinfo=timezone.utc),
    )


def test_in_memory_repository_lists_program_stories_for_epic():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        program_stories=[
            ProgramStory(
                issue_number=42,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 42",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="active",
            ),
            ProgramStory(
                issue_number=41,
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                title="Story 41",
                lane="Lane 01",
                complexity="medium",
                program_status="approved",
                execution_status="done",
            ),
            ProgramStory(
                issue_number=99,
                repo="codefromkarl/stardrifter",
                epic_issue_number=77,
                title="Other epic story",
                lane="Lane 04",
                complexity="low",
                program_status="approved",
                execution_status="planned",
            ),
        ],
    )

    assert repository.list_program_stories_for_epic(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    ) == [
        ProgramStory(
            issue_number=41,
            repo="codefromkarl/stardrifter",
            epic_issue_number=13,
            title="Story 41",
            lane="Lane 01",
            complexity="medium",
            program_status="approved",
            execution_status="done",
        ),
        ProgramStory(
            issue_number=42,
            repo="codefromkarl/stardrifter",
            epic_issue_number=13,
            title="Story 42",
            lane="Lane 01",
            complexity="medium",
            program_status="approved",
            execution_status="active",
        ),
    ]


def test_in_memory_repository_records_task_spec_draft():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )

    record_id = repository.record_task_spec_draft(
        TaskSpecDraft(
            repo="codefromkarl/stardrifter",
            story_issue_number=41,
            title="[06-TEST] establish verification closure for Story #41",
            complexity="medium",
            goal="verification fallback",
            allowed_paths=("tests/unit/",),
            dod=("has draft",),
            verification=("run tests",),
            references=("Story #41",),
        )
    )

    assert record_id == 1
    assert len(repository.task_spec_drafts) == 1
    assert repository.task_spec_drafts[0].story_issue_number == 41


def test_postgres_repository_records_task_spec_draft_sql():
    connection = FakeConnection(
        fetchone_results=[{"id": 9}],
    )
    repository = PostgresControlPlaneRepository(connection)

    record_id = repository.record_task_spec_draft(
        TaskSpecDraft(
            repo="codefromkarl/stardrifter",
            story_issue_number=41,
            title="[06-TEST] establish verification closure for Story #41",
            complexity="medium",
            goal="verification fallback",
            allowed_paths=("tests/unit/",),
            dod=("has draft",),
            verification=("run tests",),
            references=("Story #41",),
        )
    )

    assert record_id == 9
    executed_sql = "\n".join(connection.executed_sql)
    assert "INSERT INTO story_task_draft" in executed_sql


def test_in_memory_repository_records_and_updates_natural_language_intent():
    from taskplane.models import NaturalLanguageIntent

    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )

    intent = NaturalLanguageIntent(
        id="intent-1",
        repo="codefromkarl/stardrifter",
        prompt="实现认证系统",
        status="awaiting_review",
        conversation=(
            {"role": "user", "content": "实现认证系统"},
        ),
        summary="ready",
        clarification_questions=(),
        proposal_json={"epic": {"title": "Auth"}, "stories": []},
    )

    repository.record_natural_language_intent(intent)
    listed = repository.list_natural_language_intents(repo="codefromkarl/stardrifter")

    assert listed == [intent]

    updated = NaturalLanguageIntent(
        id="intent-1",
        repo="codefromkarl/stardrifter",
        prompt="实现认证系统",
        status="promoted",
        conversation=(
            {"role": "user", "content": "实现认证系统"},
        ),
        summary="promoted",
        clarification_questions=(),
        proposal_json={"epic": {"title": "Auth"}, "stories": []},
        promoted_epic_issue_number=900000001,
    )
    repository.update_natural_language_intent(updated)

    assert repository.get_natural_language_intent("intent-1") == updated


def test_postgres_repository_records_and_lists_natural_language_intents():
    from taskplane.models import NaturalLanguageIntent

    connection = FakeConnection(
        fetchone_results=[{"id": "intent-1"}],
        fetchall_results=[[
            {
                "id": "intent-1",
                "repo": "codefromkarl/stardrifter",
                "prompt": "实现认证系统",
                "status": "awaiting_review",
                "conversation_json": [{"role": "user", "content": "实现认证系统"}],
                "summary": "ready",
                "clarification_questions_json": [],
                "proposal_json": {"epic": {"title": "Auth"}, "stories": []},
                "analysis_model": "gpt-4.1-mini",
                "promoted_epic_issue_number": None,
                "created_at": None,
                "updated_at": None,
                "approved_at": None,
                "approved_by": None,
            }
        ]],
    )
    repository = PostgresControlPlaneRepository(connection)

    record_id = repository.record_natural_language_intent(
        NaturalLanguageIntent(
            id="intent-1",
            repo="codefromkarl/stardrifter",
            prompt="实现认证系统",
            status="awaiting_review",
            conversation=(({"role": "user", "content": "实现认证系统"}),),
            summary="ready",
            clarification_questions=(),
            proposal_json={"epic": {"title": "Auth"}, "stories": []},
            analysis_model="gpt-4.1-mini",
        )
    )
    listed = repository.list_natural_language_intents(repo="codefromkarl/stardrifter")

    assert record_id == "intent-1"
    assert listed[0].id == "intent-1"
    executed_sql = "\n".join(connection.executed_sql)
    assert "INSERT INTO natural_language_intent" in executed_sql
    assert "FROM natural_language_intent" in executed_sql


def test_postgres_natural_language_intent_helpers_preserve_review_fields():
    from taskplane.models import NaturalLanguageIntent
    from taskplane.repository._postgres_intake import (
        NATURAL_LANGUAGE_INTENT_SELECT_SQL,
        build_record_natural_language_intent_params,
    )

    intent = NaturalLanguageIntent(
        id="intent-1",
        repo="codefromkarl/stardrifter",
        prompt="实现认证系统",
        status="awaiting_review",
        conversation=(({"role": "user", "content": "实现认证系统"}),),
        summary="ready",
        clarification_questions=("请补充 JWT 范围",),
        proposal_json={"epic": {"title": "Auth"}, "stories": []},
        analysis_model="gpt-4.1-mini",
        approved_by="alice",
        reviewed_by="bob",
        review_action="approve",
        review_feedback="looks good",
    )

    params = build_record_natural_language_intent_params(intent)

    assert "reviewed_at" in NATURAL_LANGUAGE_INTENT_SELECT_SQL
    assert "reviewed_by" in NATURAL_LANGUAGE_INTENT_SELECT_SQL
    assert "review_action" in NATURAL_LANGUAGE_INTENT_SELECT_SQL
    assert "review_feedback" in NATURAL_LANGUAGE_INTENT_SELECT_SQL
    assert params[0] == "intent-1"
    assert params[4] == '[{"role": "user", "content": "实现认证系统"}]'
    assert params[6] == '["请补充 JWT 范围"]'
    assert params[13] == "bob"
    assert params[14] == "approve"
    assert params[15] == "looks good"


def test_in_memory_repository_records_and_queries_story_pull_request_link():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )

    record_id = repository.record_story_pull_request_link(
        StoryPullRequestLink(
            repo="codefromkarl/stardrifter",
            story_issue_number=41,
            pull_number=203,
            pull_url="https://github.com/codefromkarl/stardrifter/pull/203",
        )
    )

    assert record_id == 1
    assert repository.get_story_pull_request_link(
        repo="codefromkarl/stardrifter", story_issue_number=41
    ) == {
        "repo": "codefromkarl/stardrifter",
        "story_issue_number": 41,
        "pull_number": 203,
        "pull_url": "https://github.com/codefromkarl/stardrifter/pull/203",
    }


def test_postgres_repository_records_story_pull_request_link_sql():
    connection = FakeConnection(
        fetchone_results=[{"id": 11}],
    )
    repository = PostgresControlPlaneRepository(connection)

    record_id = repository.record_story_pull_request_link(
        StoryPullRequestLink(
            repo="codefromkarl/stardrifter",
            story_issue_number=41,
            pull_number=203,
            pull_url="https://github.com/codefromkarl/stardrifter/pull/203",
        )
    )

    assert record_id == 11
    executed_sql = "\n".join(connection.executed_sql)
    assert "INSERT INTO story_pull_request_link" in executed_sql


def test_in_memory_repository_records_approval_event():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )

    record_id = repository.record_approval_event(
        ApprovalEvent(
            work_id="issue-41",
            approver="system",
            decision="requested",
            reason="missing-approval",
        )
    )

    assert record_id == 1
    assert len(repository.approval_events) == 1
    assert repository.approval_events[0].work_id == "issue-41"


def test_postgres_repository_records_approval_event_sql():
    connection = FakeConnection(
        fetchone_results=[{"id": 13}],
    )
    repository = PostgresControlPlaneRepository(connection)

    record_id = repository.record_approval_event(
        ApprovalEvent(
            work_id="issue-41",
            approver="system",
            decision="requested",
            reason="missing-approval",
        )
    )

    assert record_id == 13
    executed_sql = "\n".join(connection.executed_sql)
    assert "INSERT INTO approval_event" in executed_sql


def test_in_memory_repository_records_and_lists_operator_requests():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )

    record_id = repository.record_operator_request(
        OperatorRequest(
            repo="codefromkarl/stardrifter",
            epic_issue_number=13,
            reason_code="progress_timeout",
            summary="Epic #13 needs operator attention: progress timed out with 1 remaining story.",
            remaining_story_issue_numbers=(43,),
            blocked_story_issue_numbers=(),
            status="open",
            opened_at=datetime(2026, 3, 1, 14, 30, tzinfo=timezone.utc),
        )
    )

    assert record_id == 1
    assert repository.list_operator_requests(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    ) == [
        OperatorRequest(
            repo="codefromkarl/stardrifter",
            epic_issue_number=13,
            reason_code="progress_timeout",
            summary="Epic #13 needs operator attention: progress timed out with 1 remaining story.",
            remaining_story_issue_numbers=(43,),
            blocked_story_issue_numbers=(),
            status="open",
            opened_at=datetime(2026, 3, 1, 14, 30, tzinfo=timezone.utc),
        )
    ]


def test_postgres_repository_records_and_lists_operator_requests():
    opened_at = datetime(2026, 3, 1, 14, 30, tzinfo=timezone.utc)
    connection = FakeConnection(
        fetchone_results=[{"id": 17}],
        fetchall_results=[
            [
                {
                    "repo": "codefromkarl/stardrifter",
                    "epic_issue_number": 13,
                    "reason_code": "all_remaining_stories_blocked",
                    "summary": "Epic #13 needs operator attention: 2 blocked stories are preventing the remaining 1 story from safely running.",
                    "remaining_story_issue_numbers_json": [44],
                    "blocked_story_issue_numbers_json": [41, 42],
                    "status": "open",
                    "opened_at": opened_at,
                }
            ]
        ],
    )
    repository = PostgresControlPlaneRepository(connection)

    record_id = repository.record_operator_request(
        OperatorRequest(
            repo="codefromkarl/stardrifter",
            epic_issue_number=13,
            reason_code="all_remaining_stories_blocked",
            summary="Epic #13 needs operator attention: 2 blocked stories are preventing the remaining 1 story from safely running.",
            remaining_story_issue_numbers=(44,),
            blocked_story_issue_numbers=(41, 42),
            status="open",
            opened_at=opened_at,
        )
    )

    listed = repository.list_operator_requests(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    )

    assert record_id == 17
    assert listed == [
        OperatorRequest(
            repo="codefromkarl/stardrifter",
            epic_issue_number=13,
            reason_code="all_remaining_stories_blocked",
            summary="Epic #13 needs operator attention: 2 blocked stories are preventing the remaining 1 story from safely running.",
            remaining_story_issue_numbers=(44,),
            blocked_story_issue_numbers=(41, 42),
            status="open",
            opened_at=opened_at,
        )
    ]
    executed_sql = "\n".join(connection.executed_sql)
    assert "INSERT INTO operator_request" in executed_sql
    assert "SELECT repo," in executed_sql
    assert "FROM operator_request" in executed_sql


def test_postgres_operator_request_query_helpers_preserve_filter_contract():
    from taskplane.repository._postgres_operator_requests import (
        OPERATOR_REQUEST_SELECT_SQL,
        build_list_operator_requests_query,
    )

    sql, params = build_list_operator_requests_query(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        include_closed=False,
    )

    assert "SELECT repo," in OPERATOR_REQUEST_SELECT_SQL
    assert "FROM operator_request" in OPERATOR_REQUEST_SELECT_SQL
    assert "WHERE repo = %s AND epic_issue_number = %s AND status = 'open'" in sql
    assert "ORDER BY opened_at ASC, id ASC" in sql
    assert params == ("codefromkarl/stardrifter", 13)


def test_postgres_claim_helpers_preserve_skip_locked_contract():
    from taskplane.repository._postgres_claims import (
        CLAIM_READY_WORK_ITEM_SQL,
        build_claim_ready_work_item_params,
    )

    params = build_claim_ready_work_item_params(
        work_id="task-2",
        worker_name="worker-a",
        workspace_path="/tmp/task-2",
        branch_name="task/2-safe-cleanup",
        claimed_paths=("src/stardrifter_engine/projections/",),
        lease_token="lease-123",
        lease_expires_at="2026-04-06T00:00:00+00:00",
    )

    assert "FOR UPDATE SKIP LOCKED" in CLAIM_READY_WORK_ITEM_SQL
    assert "INSERT INTO work_claim" in CLAIM_READY_WORK_ITEM_SQL
    assert "jsonb_array_elements_text" in CLAIM_READY_WORK_ITEM_SQL
    assert params[:4] == (
        "task-2",
        "worker-a",
        "/tmp/task-2",
        "task/2-safe-cleanup",
    )
    assert params[4] == "lease-123"
    assert params[5] == "2026-04-06T00:00:00+00:00"
    assert params[6] == '["src/stardrifter_engine/projections/"]'


def test_postgres_governance_helpers_preserve_propagation_sql_contract():
    from taskplane.repository._postgres_governance import (
        SET_PROGRAM_EPIC_EXECUTION_STATUS_SQL,
        SET_PROGRAM_EPIC_EXECUTION_STATUS_WITH_PROPAGATION_SQL,
        SET_PROGRAM_STORY_EXECUTION_STATUS_SQL,
        SET_PROGRAM_STORY_EXECUTION_STATUS_WITH_PROPAGATION_SQL,
        build_epic_status_with_propagation_params,
        build_story_status_with_propagation_params,
    )

    epic_params = build_epic_status_with_propagation_params(
        repo="codefromkarl/stardrifter",
        issue_number=18,
        execution_status="active",
    )
    story_params = build_story_status_with_propagation_params(
        repo="codefromkarl/stardrifter",
        issue_number=41,
        execution_status="done",
    )

    assert "UPDATE program_epic" in SET_PROGRAM_EPIC_EXECUTION_STATUS_SQL
    assert "WITH direct_storys AS" in SET_PROGRAM_EPIC_EXECUTION_STATUS_WITH_PROPAGATION_SQL
    assert "UPDATE program_story" in SET_PROGRAM_STORY_EXECUTION_STATUS_SQL
    assert "WITH current_story AS" in SET_PROGRAM_STORY_EXECUTION_STATUS_WITH_PROPAGATION_SQL
    assert epic_params == (
        "codefromkarl/stardrifter",
        18,
        "codefromkarl/stardrifter",
        "codefromkarl/stardrifter",
        "active",
        "active",
        "active",
        "active",
        "codefromkarl/stardrifter",
    )
    assert story_params == (
        "codefromkarl/stardrifter",
        41,
        41,
        "codefromkarl/stardrifter",
        "codefromkarl/stardrifter",
        "codefromkarl/stardrifter",
        "done",
        "done",
        "codefromkarl/stardrifter",
    )


def test_postgres_promotion_helpers_normalize_and_preserve_review_update_contract():
    from taskplane.repository._postgres_promotion import (
        UPDATE_INTENT_PROMOTION_SQL,
        normalize_promotion_payload,
    )

    epic_payload, stories_payload = normalize_promotion_payload(
        {
            "epic": {
                "title": "Auth",
                "lane": "Lane 01",
            },
            "stories": [
                {
                    "story_key": "S1",
                    "title": "Backend auth",
                    "tasks": [
                        {
                            "title": "Implement login endpoint",
                            "planned_paths": ["src/auth.py"],
                        }
                    ],
                },
                "ignored-non-dict",
            ],
        }
    )

    assert epic_payload == {"title": "Auth", "lane": "Lane 01"}
    assert stories_payload == [
        {
            "story_key": "S1",
            "title": "Backend auth",
            "tasks": [
                {
                    "title": "Implement login endpoint",
                    "planned_paths": ["src/auth.py"],
                }
            ],
        }
    ]
    assert "UPDATE natural_language_intent" in UPDATE_INTENT_PROMOTION_SQL
    assert "reviewed_at = NOW()" in UPDATE_INTENT_PROMOTION_SQL
    assert "review_action = 'approve'" in UPDATE_INTENT_PROMOTION_SQL


def test_in_memory_repository_closes_operator_request_and_hides_it_by_default():
    opened_at = datetime(2026, 3, 1, 14, 30, tzinfo=timezone.utc)
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        operator_requests=[
            OperatorRequest(
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                reason_code="progress_timeout",
                summary="Epic #13 needs operator attention.",
                remaining_story_issue_numbers=(43,),
                blocked_story_issue_numbers=(),
                status="open",
                opened_at=opened_at,
            )
        ],
    )

    closed = repository.close_operator_request(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        reason_code="progress_timeout",
        closed_reason="acknowledged",
    )

    assert closed is not None
    assert closed.repo == "codefromkarl/stardrifter"
    assert closed.epic_issue_number == 13
    assert closed.reason_code == "progress_timeout"
    assert closed.summary == "Epic #13 needs operator attention."
    assert closed.remaining_story_issue_numbers == (43,)
    assert closed.blocked_story_issue_numbers == ()
    assert closed.status == "closed"
    assert closed.opened_at == opened_at
    assert closed.closed_reason == "acknowledged"
    assert closed.closed_at is not None
    assert repository.list_operator_requests(repo="codefromkarl/stardrifter") == []
    assert repository.list_operator_requests(
        repo="codefromkarl/stardrifter",
        include_closed=True,
    ) == [closed]


def test_in_memory_repository_creates_ad_hoc_work_item_ready_for_shadow_capture():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )

    created = repository.create_ad_hoc_work_item(
        work_id="adhoc-1",
        repo="codefromkarl/stardrifter",
        title="shadow captured task",
        lane="general",
        wave="Direct",
        task_type="core_path",
        blocking_mode="soft",
        planned_paths=("src/app.py",),
        metadata={
            "entry_mode": "shadow_wrap",
            "executor": "codex",
        },
    )

    assert created == WorkItem(
        id="adhoc-1",
        repo="codefromkarl/stardrifter",
        title="shadow captured task",
        lane="general",
        wave="Direct",
        status="ready",
        task_type="core_path",
        blocking_mode="soft",
        planned_paths=("src/app.py",),
    )
    assert repository.get_work_item("adhoc-1") == created


def test_postgres_repository_creates_ad_hoc_work_item():
    connection = FakeConnection(
        fetchone_results=[
            {
                "id": "adhoc-1",
                "repo": "codefromkarl/stardrifter",
                "title": "shadow captured task",
                "lane": "general",
                "wave": "Direct",
                "status": "ready",
                "complexity": "low",
                "attempt_count": 0,
                "last_failure_reason": None,
                "next_eligible_at": None,
                "source_issue_number": None,
                "canonical_story_issue_number": None,
                "task_type": "core_path",
                "blocking_mode": "soft",
                "blocked_reason": None,
                "decision_required": False,
                "dod_json": {
                    "story_issue_numbers": [],
                    "related_story_issue_numbers": [],
                    "planned_paths": ["src/app.py"],
                    "entry_mode": "shadow_wrap",
                    "executor": "codex",
                },
            }
        ]
    )
    repository = PostgresControlPlaneRepository(connection)

    created = repository.create_ad_hoc_work_item(
        work_id="adhoc-1",
        repo="codefromkarl/stardrifter",
        title="shadow captured task",
        lane="general",
        wave="Direct",
        task_type="core_path",
        blocking_mode="soft",
        planned_paths=("src/app.py",),
        metadata={
            "entry_mode": "shadow_wrap",
            "executor": "codex",
        },
    )

    assert created == WorkItem(
        id="adhoc-1",
        repo="codefromkarl/stardrifter",
        title="shadow captured task",
        lane="general",
        wave="Direct",
        status="ready",
        task_type="core_path",
        blocking_mode="soft",
        planned_paths=("src/app.py",),
    )
    executed_sql = "\n".join(connection.executed_sql)
    assert "INSERT INTO work_item" in executed_sql
    assert "RETURNING id, repo, title, lane, wave, status" in executed_sql


def test_in_memory_repository_close_operator_request_clears_attention_when_last_open_request_closes():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        epic_execution_states={
            ("codefromkarl/stardrifter", 13): EpicExecutionState(
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                status="awaiting_operator",
                completed_story_issue_numbers=(41,),
                blocked_story_issue_numbers=(42,),
                remaining_story_issue_numbers=(43,),
                blocked_reason_code="all_remaining_stories_blocked",
                operator_attention_required=True,
            )
        },
        operator_requests=[
            OperatorRequest(
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                reason_code="all_remaining_stories_blocked",
                summary="Epic #13 needs operator attention.",
                remaining_story_issue_numbers=(43,),
                blocked_story_issue_numbers=(42,),
                status="open",
            )
        ],
    )

    closed = repository.close_operator_request(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        reason_code="all_remaining_stories_blocked",
        closed_reason="acknowledged",
    )

    assert closed is not None
    epic_state = repository.get_epic_execution_state(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    )
    assert epic_state is not None
    assert epic_state.operator_attention_required is False
    assert epic_state.status == "awaiting_operator"
    assert epic_state.blocked_reason_code == "all_remaining_stories_blocked"
    assert epic_state.last_operator_action_at == closed.closed_at
    assert epic_state.last_operator_action_reason == "acknowledged"


def test_in_memory_repository_close_operator_request_keeps_attention_when_other_open_requests_remain():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
        epic_execution_states={
            ("codefromkarl/stardrifter", 13): EpicExecutionState(
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                status="awaiting_operator",
                completed_story_issue_numbers=(41,),
                blocked_story_issue_numbers=(42,),
                remaining_story_issue_numbers=(43, 44),
                blocked_reason_code="all_remaining_stories_blocked",
                operator_attention_required=True,
            )
        },
        operator_requests=[
            OperatorRequest(
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                reason_code="all_remaining_stories_blocked",
                summary="Epic #13 needs operator attention.",
                remaining_story_issue_numbers=(43, 44),
                blocked_story_issue_numbers=(42,),
                status="open",
            ),
            OperatorRequest(
                repo="codefromkarl/stardrifter",
                epic_issue_number=13,
                reason_code="no_batch_safe_stories_available",
                summary="Epic #13 needs another operator action.",
                remaining_story_issue_numbers=(43, 44),
                blocked_story_issue_numbers=(),
                status="open",
            ),
        ],
    )

    closed = repository.close_operator_request(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        reason_code="all_remaining_stories_blocked",
        closed_reason="acknowledged",
    )

    assert closed is not None
    epic_state = repository.get_epic_execution_state(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    )
    assert epic_state is not None
    assert epic_state.operator_attention_required is True
    assert epic_state.status == "awaiting_operator"
    assert epic_state.blocked_reason_code == "all_remaining_stories_blocked"
    assert epic_state.last_operator_action_at == closed.closed_at
    assert epic_state.last_operator_action_reason == "acknowledged"


def test_postgres_repository_closes_operator_request_and_filters_closed_rows():
    opened_at = datetime(2026, 3, 1, 14, 30, tzinfo=timezone.utc)
    closed_at = datetime(2026, 3, 1, 15, 45, tzinfo=timezone.utc)
    connection = FakeConnection(
        fetchone_results=[
            {
                "repo": "codefromkarl/stardrifter",
                "epic_issue_number": 13,
                "reason_code": "progress_timeout",
                "summary": "Epic #13 needs operator attention.",
                "remaining_story_issue_numbers_json": [43],
                "blocked_story_issue_numbers_json": [],
                "status": "closed",
                "opened_at": opened_at,
                "closed_at": closed_at,
                "closed_reason": "acknowledged",
            }
        ],
        fetchall_results=[
            [
                {
                    "repo": "codefromkarl/stardrifter",
                    "epic_issue_number": 13,
                    "reason_code": "progress_timeout",
                    "summary": "Epic #13 needs operator attention.",
                    "remaining_story_issue_numbers_json": [43],
                    "blocked_story_issue_numbers_json": [],
                    "status": "closed",
                    "opened_at": opened_at,
                    "closed_at": closed_at,
                    "closed_reason": "acknowledged",
                }
            ]
        ],
    )
    repository = PostgresControlPlaneRepository(connection)

    closed = repository.close_operator_request(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        reason_code="progress_timeout",
        closed_reason="acknowledged",
    )
    listed = repository.list_operator_requests(
        repo="codefromkarl/stardrifter",
        include_closed=True,
    )

    assert closed == OperatorRequest(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        reason_code="progress_timeout",
        summary="Epic #13 needs operator attention.",
        remaining_story_issue_numbers=(43,),
        blocked_story_issue_numbers=(),
        status="closed",
        opened_at=opened_at,
        closed_at=closed_at,
        closed_reason="acknowledged",
    )
    assert listed == [closed]
    executed_sql = "\n".join(connection.executed_sql)
    assert "UPDATE operator_request" in executed_sql
    assert "SET status = 'closed'" in executed_sql
    assert "closed_at = NOW()" in executed_sql
    assert "closed_reason = %s" in executed_sql
    assert "status = 'open'" in executed_sql


def test_postgres_repository_finalize_work_attempt_stages_status_update_then_followups(
    monkeypatch,
):
    repository = PostgresControlPlaneRepository(FakeConnection())
    calls: list[tuple[str, Any]] = []

    monkeypatch.setattr(
        repository,
        "_apply_finalization_status_update",
        lambda **kwargs: calls.append(("status", kwargs)),
        raising=False,
    )
    monkeypatch.setattr(
        repository,
        "_record_finalization_followups",
        lambda **kwargs: calls.append(("followups", kwargs)),
        raising=False,
    )

    execution_run = ExecutionRun(
        work_id="issue-41",
        worker_name="worker-a",
        status="done",
        summary="completed",
    )

    repository.finalize_work_attempt(
        work_id="issue-41",
        status="done",
        execution_run=execution_run,
        blocked_reason=None,
        decision_required=False,
        attempt_count=2,
        last_failure_reason=None,
        next_eligible_at=None,
        verification=None,
        commit_link={
            "work_id": "issue-41",
            "repo": "demo/repo",
            "issue_number": 41,
            "commit_sha": "abc123",
            "commit_message": "done",
        },
        pull_request_link={
            "work_id": "issue-41",
            "repo": "demo/repo",
            "issue_number": 41,
            "pull_number": 7,
            "pull_url": "https://example.invalid/pr/7",
        },
    )

    assert [stage for stage, _payload in calls] == ["status", "followups"]
    assert calls[0][1]["work_id"] == "issue-41"
    assert calls[0][1]["status"] == "done"
    assert calls[1][1]["execution_run"] == execution_run
    assert calls[1][1]["commit_link"] == {
        "work_id": "issue-41",
        "repo": "demo/repo",
        "issue_number": 41,
        "commit_sha": "abc123",
        "commit_message": "done",
    }
    assert calls[1][1]["pull_request_link"] == {
        "work_id": "issue-41",
        "repo": "demo/repo",
        "issue_number": 41,
        "pull_number": 7,
        "pull_url": "https://example.invalid/pr/7",
    }


def test_in_memory_repository_claim_ready_work_item_records_claim_atomically():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-2",
                title="safe cleanup",
                lane="Lane 06",
                wave="wave-5",
                status="ready",
                planned_paths=("src/stardrifter_engine/projections/",),
            )
        ],
        dependencies=[],
        targets_by_work_id={},
    )

    claimed = repository.claim_ready_work_item(
        "task-2",
        worker_name="worker-a",
        workspace_path="/tmp/task-2",
        branch_name="task/2-safe-cleanup",
        claimed_paths=("src/stardrifter_engine/projections/",),
    )

    assert claimed is not None
    assert claimed.status == "in_progress"
    claims = repository.list_work_claims()
    assert len(claims) == 1
    assert claims[0].work_id == "task-2"
    assert claims[0].worker_name == "worker-a"
    assert claims[0].workspace_path == "/tmp/task-2"
    assert claims[0].branch_name == "task/2-safe-cleanup"
    assert claims[0].lease_token is not None
    assert claims[0].lease_expires_at is not None
    assert claims[0].claimed_paths == ("src/stardrifter_engine/projections/",)


def test_in_memory_repository_claim_next_executable_work_item_skips_rejected_first_candidate():
    class FirstCandidateRejectedRepository(InMemoryControlPlaneRepository):
        def claim_ready_work_item(
            self,
            work_id: str,
            *,
            worker_name: str,
            workspace_path: str,
            branch_name: str,
            claimed_paths: tuple[str, ...],
        ):
            if work_id == "task-2":
                return None
            return super().claim_ready_work_item(
                work_id,
                worker_name=worker_name,
                workspace_path=workspace_path,
                branch_name=branch_name,
                claimed_paths=claimed_paths,
            )

    repository = FirstCandidateRejectedRepository(
        work_items=[
            WorkItem(
                id="task-2",
                title="first candidate",
                lane="Lane 06",
                wave="wave-5",
                status="ready",
                planned_paths=("src/first.py",),
            ),
            WorkItem(
                id="task-3",
                title="second candidate",
                lane="Lane 06",
                wave="wave-5",
                status="ready",
                planned_paths=("src/second.py",),
            ),
        ],
        dependencies=[],
        targets_by_work_id={},
    )

    claimed = repository.claim_next_executable_work_item(
        worker_name="worker-a",
        queue_evaluation=QueueEvaluation(
            executable_ids=["task-2", "task-3"], blocked_by_id={}
        ),
        candidate_work_items=repository.list_work_items(),
        workspace_path_by_work_id={"task-2": "/tmp/task-2", "task-3": "/tmp/task-3"},
        branch_name_by_work_id={
            "task-2": "task/2-first-candidate",
            "task-3": "task/3-second-candidate",
        },
    )

    assert claimed is not None
    assert claimed.id == "task-3"
    assert repository.work_items_by_id["task-2"].status == "ready"
    assert repository.work_items_by_id["task-3"].status == "in_progress"


def test_in_memory_repository_claim_next_executable_work_item_allows_requeued_ready_task_after_successful_run():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-20",
                title="requeued task",
                lane="Lane 07",
                wave="Wave0",
                status="ready",
                planned_paths=("src/requeued.py",),
            )
        ],
        dependencies=[],
        targets_by_work_id={},
    )
    repository.record_run(
        ExecutionRun(
            work_id="task-20",
            worker_name="worker-old",
            status="done",
            summary="previous successful run",
        )
    )

    claimed = repository.claim_next_executable_work_item(
        worker_name="worker-new",
        queue_evaluation=QueueEvaluation(executable_ids=["task-20"], blocked_by_id={}),
        candidate_work_items=repository.list_work_items(),
        workspace_path_by_work_id={"task-20": "/tmp/task-20"},
        branch_name_by_work_id={"task-20": "task/20-requeued"},
    )

    assert claimed is not None
    assert claimed.id == "task-20"
    assert repository.work_items_by_id["task-20"].status == "in_progress"


def test_in_memory_repository_claim_ready_work_item_allows_only_one_winner_under_competing_threads(
    monkeypatch,
):
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-11",
                title="concurrent claim",
                lane="Lane 06",
                wave="wave-5",
                status="ready",
                planned_paths=("src/concurrent.py",),
            )
        ],
        dependencies=[],
        targets_by_work_id={},
    )
    start_barrier = threading.Barrier(2)
    original_with_work_status = repository_module.with_work_status

    def slow_with_work_status(work_item, status):
        time.sleep(0.02)
        return original_with_work_status(work_item, status)

    monkeypatch.setattr(repository_module, "with_work_status", slow_with_work_status)
    results: list[WorkItem | None] = [None, None]

    def attempt_claim(index: int) -> None:
        start_barrier.wait()
        results[index] = repository.claim_ready_work_item(
            "task-11",
            worker_name=f"worker-{index}",
            workspace_path=f"/tmp/task-11-{index}",
            branch_name=f"task/11-worker-{index}",
            claimed_paths=("src/concurrent.py",),
        )

    threads = [
        threading.Thread(target=attempt_claim, args=(0,)),
        threading.Thread(target=attempt_claim, args=(1,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(result is not None for result in results) == 1
    assert repository.work_items_by_id["task-11"].status == "in_progress"
    assert len(repository.list_work_claims()) == 1


def test_in_memory_repository_claim_next_executable_work_item_allows_only_one_winner_under_competing_threads(
    monkeypatch,
):
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="task-12",
                title="concurrent next claim",
                lane="Lane 06",
                wave="wave-5",
                status="ready",
                planned_paths=("src/next-concurrent.py",),
            )
        ],
        dependencies=[],
        targets_by_work_id={},
    )
    queue_evaluation = QueueEvaluation(executable_ids=["task-12"], blocked_by_id={})
    start_barrier = threading.Barrier(2)
    original_with_work_status = repository_module.with_work_status

    def slow_with_work_status(work_item, status):
        time.sleep(0.02)
        return original_with_work_status(work_item, status)

    monkeypatch.setattr(repository_module, "with_work_status", slow_with_work_status)
    results: list[WorkItem | None] = [None, None]

    def attempt_claim(index: int) -> None:
        start_barrier.wait()
        results[index] = repository.claim_next_executable_work_item(
            worker_name=f"worker-{index}",
            queue_evaluation=queue_evaluation,
            candidate_work_items=repository.list_work_items(),
            workspace_path_by_work_id={"task-12": f"/tmp/task-12-{index}"},
            branch_name_by_work_id={"task-12": f"task/12-worker-{index}"},
        )

    threads = [
        threading.Thread(target=attempt_claim, args=(0,)),
        threading.Thread(target=attempt_claim, args=(1,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(result is not None for result in results) == 1
    assert repository.work_items_by_id["task-12"].status == "in_progress"
    assert len(repository.list_work_claims()) == 1


def test_postgres_repository_sync_ready_states_includes_story_dependency_gate():
    connection = FakeConnection()
    repository = PostgresControlPlaneRepository(connection)

    repository.sync_ready_states()

    executed_sql = "\n".join(connection.executed_sql)
    assert "story_dependency" in executed_sql
    assert "program_story current_story" in executed_sql
    assert "current_story.execution_status IN ('active', 'done')" in executed_sql
    assert "dep_story.execution_status <> 'done'" in executed_sql
    assert "canonical_story_issue_number" in executed_sql
    assert "blocking_mode = 'hard'" in executed_sql
    assert "CASE" in executed_sql
    assert "SELECT 1\n                                    SELECT 1" not in executed_sql


def test_postgres_repository_list_work_items_loads_story_issue_numbers_from_dod_json():
    connection = FakeConnection(
        fetchall_results=[
            [
                {
                    "id": "issue-56",
                    "title": "task 56",
                    "lane": "Lane 03",
                    "wave": "unassigned",
                    "status": "done",
                    "complexity": "low",
                    "source_issue_number": 56,
                    "dod_json": {"story_issue_numbers": [29]},
                }
            ]
        ]
    )
    repository = PostgresControlPlaneRepository(connection)

    work_items = repository.list_work_items()

    assert work_items[0].source_issue_number == 56
    assert work_items[0].story_issue_numbers == (29,)


def test_postgres_row_mapping_value_helpers_support_dicts_and_attributes():
    class RowWithAttrs:
        def __init__(self) -> None:
            self.present = "from-attr"

        def __getitem__(self, key: str) -> str:
            return {"indexed": "from-index"}[key]

    row = RowWithAttrs()

    assert value({"present": "from-dict"}, "present") == "from-dict"
    assert value(row, "present") == "from-attr"
    assert value(row, "indexed") == "from-index"
    assert value_optional({"missing": None}, "missing") is None
    assert value_optional(row, "missing") is None


def test_postgres_row_mapping_builds_work_item_from_pure_row_data():
    work_item = row_to_work_item(
        {
            "id": "issue-53",
            "repo": "codefromkarl/stardrifter",
            "title": "task 53",
            "lane": "Lane 04",
            "wave": "unassigned",
            "status": "pending",
            "complexity": "low",
            "attempt_count": 2,
            "last_failure_reason": "timeout",
            "next_eligible_at": datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
            "source_issue_number": 53,
            "canonical_story_issue_number": 30,
            "task_type": "documentation",
            "blocking_mode": "soft",
            "blocked_reason": "waiting",
            "decision_required": True,
            "dod_json": {
                "story_issue_numbers": [30],
                "related_story_issue_numbers": [31, 32],
                "planned_paths": [
                    "docs/domains/04-encounter-mediation/execution-plan.md"
                ],
            },
        }
    )

    assert work_item == WorkItem(
        id="issue-53",
        repo="codefromkarl/stardrifter",
        title="task 53",
        lane="Lane 04",
        wave="unassigned",
        status="pending",
        complexity="low",
        attempt_count=2,
        last_failure_reason="timeout",
        next_eligible_at="2026-03-20 10:00:00+00:00",
        source_issue_number=53,
        story_issue_numbers=(30,),
        canonical_story_issue_number=30,
        related_story_issue_numbers=(31, 32),
        task_type="documentation",
        blocking_mode="soft",
        planned_paths=("docs/domains/04-encounter-mediation/execution-plan.md",),
        blocked_reason="waiting",
        decision_required=True,
    )


def test_postgres_row_mapping_builds_program_story_from_pure_row_data():
    story = row_to_program_story(
        {
            "issue_number": 41,
            "repo": "codefromkarl/stardrifter",
            "epic_issue_number": 13,
            "title": "Story 41",
            "lane": "Lane 01",
            "complexity": "medium",
            "program_status": "approved",
            "execution_status": "done",
            "active_wave": None,
            "notes": "ready",
        }
    )

    assert story == ProgramStory(
        issue_number=41,
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        title="Story 41",
        lane="Lane 01",
        complexity="medium",
        program_status="approved",
        execution_status="done",
        active_wave=None,
        notes="ready",
    )


def test_postgres_row_mapping_builds_work_claim_and_operator_request_from_pure_rows():
    claim = row_to_work_claim(
        {
            "work_id": "issue-53",
            "worker_name": "worker-a",
            "workspace_path": "/tmp/task-53",
            "branch_name": "task/53-04-doc",
            "lease_token": "lease-123",
            "lease_expires_at": datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
            "claimed_paths": ["docs/domains/04-encounter-mediation/"],
        }
    )
    operator_request = row_to_operator_request(
        {
            "repo": "codefromkarl/stardrifter",
            "epic_issue_number": 13,
            "reason_code": "all_remaining_stories_blocked",
            "summary": "Epic #13 needs operator attention.",
            "remaining_story_issue_numbers_json": [44],
            "blocked_story_issue_numbers_json": [41, 42],
            "status": "closed",
            "opened_at": datetime(2026, 3, 1, 14, 30, tzinfo=timezone.utc),
            "closed_at": datetime(2026, 3, 1, 15, 45, tzinfo=timezone.utc),
            "closed_reason": "acknowledged",
        }
    )

    assert claim == WorkClaim(
        work_id="issue-53",
        worker_name="worker-a",
        workspace_path="/tmp/task-53",
        branch_name="task/53-04-doc",
        lease_token="lease-123",
        lease_expires_at="2026-03-20 10:00:00+00:00",
        claimed_paths=("docs/domains/04-encounter-mediation/",),
    )
    assert operator_request == OperatorRequest(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        reason_code="all_remaining_stories_blocked",
        summary="Epic #13 needs operator attention.",
        remaining_story_issue_numbers=(44,),
        blocked_story_issue_numbers=(41, 42),
        status="closed",
        opened_at=datetime(2026, 3, 1, 14, 30, tzinfo=timezone.utc),
        closed_at=datetime(2026, 3, 1, 15, 45, tzinfo=timezone.utc),
        closed_reason="acknowledged",
    )


def test_postgres_repository_list_work_items_loads_structured_repo_column():
    connection = FakeConnection(
        fetchall_results=[
            [
                {
                    "id": "issue-62",
                    "repo": "codefromkarl/stardrifter",
                    "title": "task 62",
                    "lane": "Lane 02",
                    "wave": "unassigned",
                    "status": "pending",
                    "complexity": "medium",
                    "source_issue_number": 62,
                    "dod_json": {},
                }
            ]
        ]
    )
    repository = PostgresControlPlaneRepository(connection)

    work_items = repository.list_work_items()

    assert work_items[0].repo == "codefromkarl/stardrifter"


def test_postgres_repository_list_work_items_loads_execution_metadata():
    connection = FakeConnection(
        fetchall_results=[
            [
                {
                    "id": "issue-53",
                    "title": "task 53",
                    "lane": "Lane 04",
                    "wave": "unassigned",
                    "status": "pending",
                    "complexity": "low",
                    "source_issue_number": 53,
                    "canonical_story_issue_number": 30,
                    "task_type": "documentation",
                    "blocking_mode": "soft",
                    "dod_json": {
                        "story_issue_numbers": [30],
                        "related_story_issue_numbers": [31, 32],
                        "planned_paths": [
                            "docs/domains/04-encounter-mediation/execution-plan.md"
                        ],
                    },
                }
            ]
        ]
    )
    repository = PostgresControlPlaneRepository(connection)

    work_items = repository.list_work_items()

    assert work_items[0].canonical_story_issue_number == 30
    assert work_items[0].related_story_issue_numbers == (31, 32)
    assert work_items[0].task_type == "documentation"
    assert work_items[0].blocking_mode == "soft"
    assert work_items[0].planned_paths == (
        "docs/domains/04-encounter-mediation/execution-plan.md",
    )


def test_postgres_repository_list_story_work_item_ids_prefers_canonical_story():
    connection = FakeConnection(fetchall_results=[[{"id": "issue-53"}]])
    repository = PostgresControlPlaneRepository(connection)

    ids = repository.list_story_work_item_ids(30)

    assert ids == ["issue-53"]
    executed_sql = "\n".join(connection.executed_sql)
    assert "canonical_story_issue_number = %s" in executed_sql


def test_postgres_repository_lists_work_claims():
    connection = FakeConnection(
        fetchall_results=[
            [
                {
                    "work_id": "issue-53",
                    "worker_name": "worker-a",
                    "workspace_path": "/tmp/task-53",
                    "branch_name": "task/53-04-doc",
                    "lease_token": "lease-123",
                    "lease_expires_at": "2026-03-20T10:00:00Z",
                    "claimed_paths": [
                        "docs/domains/04-encounter-mediation/",
                    ],
                }
            ]
        ]
    )
    repository = PostgresControlPlaneRepository(connection)

    claims = repository.list_work_claims()

    assert claims == [
        WorkClaim(
            work_id="issue-53",
            worker_name="worker-a",
            workspace_path="/tmp/task-53",
            branch_name="task/53-04-doc",
            lease_token="lease-123",
            lease_expires_at="2026-03-20T10:00:00Z",
            claimed_paths=("docs/domains/04-encounter-mediation/",),
        )
    ]


def test_postgres_repository_upserts_and_deletes_work_claim():
    connection = FakeConnection()
    repository = PostgresControlPlaneRepository(connection)

    repository.upsert_work_claim(
        WorkClaim(
            work_id="issue-53",
            worker_name="worker-a",
            workspace_path="/tmp/task-53",
            branch_name="task/53-04-doc",
            lease_token="lease-123",
            lease_expires_at="2026-03-20T10:00:00Z",
            claimed_paths=("docs/domains/04-encounter-mediation/",),
        )
    )
    repository.delete_work_claim("issue-53")

    executed_sql = "\n".join(connection.executed_sql)
    assert "INSERT INTO work_claim" in executed_sql
    assert "ON CONFLICT (work_id) DO UPDATE SET" in executed_sql
    assert "lease_token" in executed_sql
    assert "lease_expires_at" in executed_sql
    assert "DELETE FROM work_claim" in executed_sql


def test_postgres_repository_record_verification_uses_explicit_run_id():
    connection = FakeConnection(fetchone_results=[{"id": 41}])
    repository = PostgresControlPlaneRepository(connection)

    run_id = repository.record_run(
        ExecutionRun(
            work_id="issue-53",
            worker_name="worker-a",
            status="done",
            summary="patched files",
        )
    )
    repository.record_verification(
        VerificationEvidence(
            run_id=run_id,
            work_id="issue-53",
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="3 passed",
        )
    )

    verification_sql = connection.executed_sql[-1]
    verification_params = cast(tuple[object, ...], connection.executed_params[-1])
    assert "SELECT id FROM execution_run WHERE work_id" not in verification_sql
    assert "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)" in verification_sql
    assert verification_params[0] == 41
    assert verification_params[1] == "issue-53"


def test_postgres_repository_list_active_work_items_reads_from_view():
    connection = FakeConnection(
        fetchall_results=[
            [
                {
                    "id": "issue-69",
                    "title": "[Wave0-TASK] 冻结边界定义与签字确认",
                    "lane": "Lane INT",
                    "wave": "unassigned",
                    "status": "pending",
                    "complexity": "low",
                    "source_issue_number": 69,
                    "canonical_story_issue_number": -1901,
                    "task_type": "governance",
                    "blocking_mode": "hard",
                    "dod_json": {"planned_paths": ["docs/baselines/wave0-freeze.md"]},
                }
            ]
        ]
    )
    repository = PostgresControlPlaneRepository(connection)

    work_items = repository.list_active_work_items()

    assert work_items[0].source_issue_number == 69
    executed_sql = "\n".join(connection.executed_sql)
    assert "FROM v_active_task_queue" in executed_sql


def test_postgres_repository_updates_program_execution_status():
    connection = FakeConnection()
    repository = PostgresControlPlaneRepository(connection)

    repository.set_program_epic_execution_status(
        repo="codefromkarl/stardrifter",
        issue_number=19,
        execution_status="done",
    )
    repository.set_program_story_execution_status(
        repo="codefromkarl/stardrifter",
        issue_number=42,
        execution_status="blocked",
    )

    executed_sql = "\n".join(connection.executed_sql)
    assert "UPDATE program_epic" in executed_sql
    assert "UPDATE program_story" in executed_sql


def test_postgres_repository_updates_program_epic_execution_status_with_propagation():
    connection = FakeConnection()
    repository = PostgresControlPlaneRepository(connection)

    repository.set_program_epic_execution_status_with_propagation(
        repo="codefromkarl/stardrifter",
        issue_number=13,
        execution_status="active",
    )

    executed_sql = "\n".join(connection.executed_sql)
    assert "UPDATE program_epic" in executed_sql
    assert "WITH direct_storys AS" in executed_sql
    assert "unmet_dependencies" in executed_sql
    assert "dep.execution_status NOT IN ('active', 'done')" in executed_sql
    assert "UPDATE program_story" in executed_sql


def test_postgres_repository_lists_program_stories_for_epic_sql():
    connection = FakeConnection(
        fetchall_results=[
            [
                {
                    "issue_number": 41,
                    "repo": "codefromkarl/stardrifter",
                    "epic_issue_number": 13,
                    "title": "Story 41",
                    "lane": "Lane 01",
                    "complexity": "medium",
                    "program_status": "approved",
                    "execution_status": "done",
                    "active_wave": None,
                    "notes": None,
                }
            ]
        ]
    )
    repository = PostgresControlPlaneRepository(connection)

    stories = repository.list_program_stories_for_epic(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    )

    assert stories == [
        ProgramStory(
            issue_number=41,
            repo="codefromkarl/stardrifter",
            epic_issue_number=13,
            title="Story 41",
            lane="Lane 01",
            complexity="medium",
            program_status="approved",
            execution_status="done",
            active_wave=None,
            notes=None,
        )
    ]
    executed_sql = "\n".join(connection.executed_sql)
    assert "FROM program_story" in executed_sql
    assert "epic_issue_number = %s" in executed_sql


def test_postgres_repository_upserts_epic_execution_state_sql():
    connection = FakeConnection()
    repository = PostgresControlPlaneRepository(connection)

    repository.upsert_epic_execution_state(
        EpicExecutionState(
            repo="codefromkarl/stardrifter",
            epic_issue_number=13,
            status="awaiting_operator",
            completed_story_issue_numbers=(41,),
            blocked_story_issue_numbers=(42,),
            remaining_story_issue_numbers=(43,),
            blocked_reason_code="all_remaining_stories_blocked",
            operator_attention_required=True,
            last_operator_action_at=datetime(2026, 3, 1, 14, 30, tzinfo=timezone.utc),
            last_operator_action_reason="acknowledged",
            last_progress_at=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
            stalled_since=datetime(2026, 3, 1, 13, 0, tzinfo=timezone.utc),
        )
    )

    executed_sql = "\n".join(connection.executed_sql)
    assert "INSERT INTO epic_execution_state" in executed_sql
    assert "ON CONFLICT (repo, epic_issue_number) DO UPDATE SET" in executed_sql
    assert "blocked_reason_code" in executed_sql
    assert "operator_attention_required" in executed_sql
    assert "last_operator_action_at" in executed_sql
    assert "last_operator_action_reason" in executed_sql


def test_postgres_repository_reads_epic_execution_state_sql():
    connection = FakeConnection(
        fetchone_results=[
            {
                "repo": "codefromkarl/stardrifter",
                "epic_issue_number": 13,
                "status": "awaiting_operator",
                "completed_story_issue_numbers_json": [41, 42],
                "blocked_story_issue_numbers_json": [],
                "remaining_story_issue_numbers_json": [43],
                "blocked_reason_code": "no_batch_safe_stories_available",
                "operator_attention_required": True,
                "last_operator_action_at": datetime(
                    2026, 3, 1, 14, 30, tzinfo=timezone.utc
                ),
                "last_operator_action_reason": "acknowledged",
                "last_progress_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
                "stalled_since": datetime(2026, 3, 1, 13, 0, tzinfo=timezone.utc),
            }
        ]
    )
    repository = PostgresControlPlaneRepository(connection)

    state = repository.get_epic_execution_state(
        repo="codefromkarl/stardrifter", epic_issue_number=13
    )

    assert state == EpicExecutionState(
        repo="codefromkarl/stardrifter",
        epic_issue_number=13,
        status="awaiting_operator",
        completed_story_issue_numbers=(41, 42),
        blocked_story_issue_numbers=(),
        remaining_story_issue_numbers=(43,),
        blocked_reason_code="no_batch_safe_stories_available",
        operator_attention_required=True,
        last_operator_action_at=datetime(2026, 3, 1, 14, 30, tzinfo=timezone.utc),
        last_operator_action_reason="acknowledged",
        last_progress_at=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
        stalled_since=datetime(2026, 3, 1, 13, 0, tzinfo=timezone.utc),
    )
    executed_sql = "\n".join(connection.executed_sql)
    assert "FROM epic_execution_state" in executed_sql
    assert "last_operator_action_at" in executed_sql
    assert "last_operator_action_reason" in executed_sql
    assert "last_progress_at" in executed_sql
    assert "stalled_since" in executed_sql


def test_postgres_repository_updates_program_story_execution_status_with_propagation():
    connection = FakeConnection()
    repository = PostgresControlPlaneRepository(connection)

    repository.set_program_story_execution_status_with_propagation(
        repo="codefromkarl/stardrifter",
        issue_number=21,
        execution_status="done",
    )

    executed_sql = "\n".join(connection.executed_sql)
    assert "UPDATE program_story" in executed_sql
    assert "sibling_storys AS" in executed_sql
    assert "dependency_state AS" in executed_sql


@pytest.mark.usefixtures("postgres_test_db")
def test_postgres_repository_propagation_skips_archived_sibling_stories(
    postgres_test_db: str,
):
    assert psycopg is not None and dict_row is not None
    repo = f"codefromkarl/stardrifter-propagation-{uuid4().hex[:8]}"

    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO program_epic (
                    repo, issue_number, title, lane, program_status, execution_status
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    18,
                    "[Epic][06] propagation guard",
                    "Lane 06",
                    "approved",
                    "active",
                ),
            )
            cursor.execute(
                """
                INSERT INTO program_story (
                    repo, issue_number, epic_issue_number, title, lane, complexity,
                    program_status, execution_status
                )
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s),
                    (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    repo,
                    40,
                    18,
                    "[Story][06-C] current story",
                    "Lane 06",
                    "medium",
                    "approved",
                    "active",
                    repo,
                    41,
                    18,
                    "[Story][06-D] archived verification closure",
                    "Lane 06",
                    "medium",
                    "archived",
                    "backlog",
                ),
            )
            cursor.execute(
                """
                INSERT INTO program_story_dependency (
                    repo, story_issue_number, depends_on_story_issue_number
                )
                VALUES (%s, %s, %s)
                """,
                (repo, 41, 40),
            )
            cursor.execute(
                """
                INSERT INTO work_item (
                    id, repo, title, lane, wave, status, complexity,
                    source_issue_number, canonical_story_issue_number,
                    task_type, blocking_mode, dod_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    "issue-4000",
                    repo,
                    "story 40 task",
                    "Lane 06",
                    "Wave0",
                    "done",
                    "medium",
                    4000,
                    40,
                    "implementation",
                    "hard",
                    "{}",
                ),
            )
        connection.commit()

        repository = PostgresControlPlaneRepository(connection)
        repository.set_program_story_execution_status_with_propagation(
            repo=repo,
            issue_number=40,
            execution_status="done",
        )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT issue_number, program_status::text, execution_status::text
                FROM program_story
                WHERE repo = %s
                ORDER BY issue_number
                """,
                (repo,),
            )
            rows = cursor.fetchall()

    assert rows == [
        {
            "issue_number": 40,
            "program_status": "approved",
            "execution_status": "done",
        },
        {
            "issue_number": 41,
            "program_status": "archived",
            "execution_status": "backlog",
        },
    ]


@pytest.mark.usefixtures("postgres_test_db")
def test_postgres_integration_claim_ready_work_item_allows_only_one_winner_under_row_lock(
    postgres_test_db: str,
):
    assert psycopg is not None and dict_row is not None
    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as seed_connection:
        with seed_connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO work_item (
                    id, repo, title, lane, wave, status, complexity,
                    source_issue_number, canonical_story_issue_number,
                    task_type, blocking_mode, dod_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    "task-201",
                    "codefromkarl/stardrifter",
                    "concurrent claim",
                    "Lane 06",
                    "wave-5",
                    "ready",
                    "medium",
                    201,
                    None,
                    "core_path",
                    "hard",
                    '{"planned_paths": ["src/concurrent.py"]}',
                ),
            )
        seed_connection.commit()

    locker_connection = psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    )
    try:
        with locker_connection.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute(
                "SELECT id FROM work_item WHERE id = %s FOR UPDATE",
                ("task-201",),
            )

        claimant_connection = psycopg.connect(
            postgres_test_db, row_factory=cast(Any, dict_row)
        )
        observer_connection = psycopg.connect(
            postgres_test_db, row_factory=cast(Any, dict_row)
        )
        try:
            with claimant_connection.cursor() as cursor:
                cursor.execute("SET statement_timeout TO 500")
            claimant_repository = PostgresControlPlaneRepository(claimant_connection)
            observer_repository = PostgresControlPlaneRepository(observer_connection)

            blocked_claim = claimant_repository.claim_ready_work_item(
                "task-201",
                worker_name="worker-a",
                workspace_path="/tmp/task-201",
                branch_name="task/201-concurrent-claim",
                claimed_paths=("src/concurrent.py",),
            )

            assert blocked_claim is None
            assert observer_repository.list_work_claims() == []
            assert observer_repository.get_work_item("task-201").status == "ready"

            locker_connection.commit()

            claimed = claimant_repository.claim_ready_work_item(
                "task-201",
                worker_name="worker-a",
                workspace_path="/tmp/task-201",
                branch_name="task/201-concurrent-claim",
                claimed_paths=("src/concurrent.py",),
            )

            assert claimed is not None
            assert claimed.id == "task-201"
            claims = observer_repository.list_work_claims()
            assert len(claims) == 1
            assert claims[0].work_id == "task-201"
            assert claims[0].worker_name == "worker-a"
            assert claims[0].workspace_path == "/tmp/task-201"
            assert claims[0].branch_name == "task/201-concurrent-claim"
            assert claims[0].claimed_paths == ("src/concurrent.py",)
            assert observer_repository.get_work_item("task-201").status == "in_progress"
        finally:
            claimant_connection.close()
            observer_connection.close()
    finally:
        locker_connection.close()


@pytest.mark.usefixtures("postgres_test_db")
def test_postgres_integration_claim_next_executable_work_item_falls_through_locked_first_candidate(
    postgres_test_db: str,
):
    assert psycopg is not None and dict_row is not None
    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as seed_connection:
        with seed_connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO work_item (
                    id, repo, title, lane, wave, status, complexity,
                    source_issue_number, canonical_story_issue_number,
                    task_type, blocking_mode, dod_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb),
                       (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    "task-301",
                    "codefromkarl/stardrifter",
                    "first candidate",
                    "Lane 06",
                    "wave-5",
                    "ready",
                    "medium",
                    301,
                    None,
                    "core_path",
                    "hard",
                    '{"planned_paths": ["src/first.py"]}',
                    "task-302",
                    "codefromkarl/stardrifter",
                    "second candidate",
                    "Lane 06",
                    "wave-5",
                    "ready",
                    "medium",
                    302,
                    None,
                    "core_path",
                    "hard",
                    '{"planned_paths": ["src/second.py"]}',
                ),
            )
        seed_connection.commit()

    locker_connection = psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    )
    try:
        with locker_connection.cursor() as cursor:
            cursor.execute("BEGIN")
            cursor.execute(
                "SELECT id FROM work_item WHERE id = %s FOR UPDATE",
                ("task-301",),
            )

        claimant_connection = psycopg.connect(
            postgres_test_db, row_factory=cast(Any, dict_row)
        )
        observer_connection = psycopg.connect(
            postgres_test_db, row_factory=cast(Any, dict_row)
        )
        try:
            with claimant_connection.cursor() as cursor:
                cursor.execute("SET statement_timeout TO 500")
            claimant_repository = PostgresControlPlaneRepository(claimant_connection)
            observer_repository = PostgresControlPlaneRepository(observer_connection)

            claimed = claimant_repository.claim_next_executable_work_item(
                worker_name="worker-a",
                queue_evaluation=QueueEvaluation(
                    executable_ids=["task-301", "task-302"],
                    blocked_by_id={},
                ),
                candidate_work_items=claimant_repository.list_work_items(),
                workspace_path_by_work_id={
                    "task-301": "/tmp/task-301",
                    "task-302": "/tmp/task-302",
                },
                branch_name_by_work_id={
                    "task-301": "task/301-first-candidate",
                    "task-302": "task/302-second-candidate",
                },
            )

            assert claimed is not None
            assert claimed.id == "task-302"
            claims = observer_repository.list_work_claims()
            assert len(claims) == 1
            assert claims[0].work_id == "task-302"
            assert claims[0].claimed_paths == ("src/second.py",)
            assert observer_repository.get_work_item("task-301").status == "ready"
            assert observer_repository.get_work_item("task-302").status == "in_progress"
        finally:
            claimant_connection.close()
            observer_connection.close()
    finally:
        locker_connection.rollback()
        locker_connection.close()


@pytest.mark.usefixtures("postgres_test_db")
def test_postgres_integration_claim_ready_work_item_blocks_on_overlapping_active_claim(
    postgres_test_db: str,
):
    assert psycopg is not None and dict_row is not None
    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as seed_connection:
        with seed_connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO work_item (
                    id, repo, title, lane, wave, status, complexity,
                    source_issue_number, canonical_story_issue_number,
                    task_type, blocking_mode, dod_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb),
                       (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    "task-401",
                    "codefromkarl/stardrifter",
                    "active claimed task",
                    "Lane 06",
                    "wave-5",
                    "in_progress",
                    "medium",
                    401,
                    None,
                    "core_path",
                    "hard",
                    '{"planned_paths": ["src/overlap/"]}',
                    "task-402",
                    "codefromkarl/stardrifter",
                    "overlapping candidate",
                    "Lane 06",
                    "wave-5",
                    "ready",
                    "medium",
                    402,
                    None,
                    "core_path",
                    "hard",
                    '{"planned_paths": ["src/overlap/file.py"]}',
                ),
            )
            cursor.execute(
                """
                INSERT INTO work_claim (
                    work_id, worker_name, workspace_path, branch_name,
                    lease_token, lease_expires_at, claimed_paths
                )
                VALUES (%s, %s, %s, %s, %s, NOW() + INTERVAL '15 minutes', %s::jsonb)
                """,
                (
                    "task-401",
                    "worker-a",
                    "/tmp/task-401",
                    "task/401-active-claimed-task",
                    "lease-401",
                    '["src/overlap/"]',
                ),
            )
        seed_connection.commit()

    claimant_connection = psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    )
    observer_connection = psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    )
    try:
        repository = PostgresControlPlaneRepository(claimant_connection)
        observer_repository = PostgresControlPlaneRepository(observer_connection)

        claimed = repository.claim_ready_work_item(
            "task-402",
            worker_name="worker-b",
            workspace_path="/tmp/task-402",
            branch_name="task/402-overlapping-candidate",
            claimed_paths=("src/overlap/file.py",),
        )

        assert claimed is None
        assert observer_repository.get_work_item("task-402").status == "ready"
        claims = observer_repository.list_work_claims()
        assert len(claims) == 1
        assert claims[0].work_id == "task-401"
    finally:
        claimant_connection.close()
        observer_connection.close()


@pytest.mark.usefixtures("postgres_test_db")
def test_postgres_integration_claim_ready_work_item_allows_reclaim_after_overlapping_claim_expires(
    postgres_test_db: str,
):
    assert psycopg is not None and dict_row is not None
    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as seed_connection:
        with seed_connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO work_item (
                    id, repo, title, lane, wave, status, complexity,
                    source_issue_number, canonical_story_issue_number,
                    task_type, blocking_mode, dod_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb),
                       (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    "task-411",
                    "codefromkarl/stardrifter",
                    "expired claimed task",
                    "Lane 06",
                    "wave-5",
                    "in_progress",
                    "medium",
                    411,
                    None,
                    "core_path",
                    "hard",
                    '{"planned_paths": ["src/reclaim/"]}',
                    "task-412",
                    "codefromkarl/stardrifter",
                    "reclaim candidate",
                    "Lane 06",
                    "wave-5",
                    "ready",
                    "medium",
                    412,
                    None,
                    "core_path",
                    "hard",
                    '{"planned_paths": ["src/reclaim/file.py"]}',
                ),
            )
            cursor.execute(
                """
                INSERT INTO work_claim (
                    work_id, worker_name, workspace_path, branch_name,
                    lease_token, lease_expires_at, claimed_paths
                )
                VALUES (%s, %s, %s, %s, %s, NOW() - INTERVAL '1 minute', %s::jsonb)
                """,
                (
                    "task-411",
                    "worker-a",
                    "/tmp/task-411",
                    "task/411-expired-claimed-task",
                    "lease-411",
                    '["src/reclaim/"]',
                ),
            )
        seed_connection.commit()

    claimant_connection = psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    )
    observer_connection = psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    )
    try:
        repository = PostgresControlPlaneRepository(claimant_connection)
        observer_repository = PostgresControlPlaneRepository(observer_connection)

        claimed = repository.claim_ready_work_item(
            "task-412",
            worker_name="worker-b",
            workspace_path="/tmp/task-412",
            branch_name="task/412-reclaim-candidate",
            claimed_paths=("src/reclaim/file.py",),
        )

        assert claimed is not None
        assert claimed.id == "task-412"
        claims = observer_repository.list_work_claims()
        assert {claim.work_id for claim in claims} == {"task-411", "task-412"}
        assert observer_repository.get_work_item("task-412").status == "in_progress"
    finally:
        claimant_connection.close()
        observer_connection.close()


@pytest.mark.usefixtures("postgres_test_db")
def test_postgres_integration_claim_ready_work_item_allows_requeued_ready_task_after_successful_run(
    postgres_test_db: str,
):
    assert psycopg is not None and dict_row is not None
    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as connection:
        repository = PostgresControlPlaneRepository(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO work_item (
                    id, repo, title, lane, wave, status, complexity,
                    source_issue_number, canonical_story_issue_number,
                    task_type, blocking_mode, dod_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    "task-301",
                    "codefromkarl/stardrifter",
                    "requeued ready task",
                    "Lane 07",
                    "Wave0",
                    "ready",
                    "medium",
                    301,
                    None,
                    "core_path",
                    "hard",
                    '{"planned_paths": ["src/requeued.py"]}',
                ),
            )
        connection.commit()

        repository.record_run(
            ExecutionRun(
                work_id="task-301",
                worker_name="worker-old",
                status="done",
                summary="previous successful run",
            )
        )

        claimed = repository.claim_ready_work_item(
            "task-301",
            worker_name="worker-new",
            workspace_path="/tmp/task-301",
            branch_name="task/301-requeued",
            claimed_paths=("src/requeued.py",),
        )

        assert claimed is not None
        assert claimed.id == "task-301"


@pytest.mark.usefixtures("postgres_test_db")
def test_postgres_integration_renewed_overlapping_claim_blocks_again(
    postgres_test_db: str,
):
    assert psycopg is not None and dict_row is not None
    with psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    ) as seed_connection:
        with seed_connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO work_item (
                    id, repo, title, lane, wave, status, complexity,
                    source_issue_number, canonical_story_issue_number,
                    task_type, blocking_mode, dod_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb),
                       (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    "task-421",
                    "codefromkarl/stardrifter",
                    "renewed conflict task",
                    "Lane 06",
                    "wave-5",
                    "in_progress",
                    "medium",
                    421,
                    None,
                    "core_path",
                    "hard",
                    '{"planned_paths": ["src/renew/"]}',
                    "task-422",
                    "codefromkarl/stardrifter",
                    "renew blocked candidate",
                    "Lane 06",
                    "wave-5",
                    "ready",
                    "medium",
                    422,
                    None,
                    "core_path",
                    "hard",
                    '{"planned_paths": ["src/renew/file.py"]}',
                ),
            )
            cursor.execute(
                """
                INSERT INTO work_claim (
                    work_id, worker_name, workspace_path, branch_name,
                    lease_token, lease_expires_at, claimed_paths
                )
                VALUES (%s, %s, %s, %s, %s, NOW() + INTERVAL '1 minute', %s::jsonb)
                """,
                (
                    "task-421",
                    "worker-a",
                    "/tmp/task-421",
                    "task/421-renewed-conflict-task",
                    "lease-421",
                    '["src/renew/"]',
                ),
            )
        seed_connection.commit()

    claimant_connection = psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    )
    observer_connection = psycopg.connect(
        postgres_test_db, row_factory=cast(Any, dict_row)
    )
    try:
        repository = PostgresControlPlaneRepository(claimant_connection)
        observer_repository = PostgresControlPlaneRepository(observer_connection)

        renewed = repository.renew_work_claim("task-421", lease_token="lease-421")
        assert renewed is not None

        claimed = repository.claim_ready_work_item(
            "task-422",
            worker_name="worker-b",
            workspace_path="/tmp/task-422",
            branch_name="task/422-renew-blocked-candidate",
            claimed_paths=("src/renew/file.py",),
        )

        assert claimed is None
        assert observer_repository.get_work_item("task-422").status == "ready"
        claims = observer_repository.list_active_work_claims()
        assert [claim.work_id for claim in claims] == ["task-421"]
    finally:
        claimant_connection.close()
        observer_connection.close()


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    def execute(self, sql: str, params=None) -> None:
        self.connection.executed_sql.append(sql)
        self.connection.executed_params.append(params)

    def fetchone(self):
        if not self.connection.fetchone_results:
            return None
        return self.connection.fetchone_results.pop(0)

    def fetchall(self):
        if not self.connection.fetchall_results:
            return []
        return self.connection.fetchall_results.pop(0)

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class FakeConnection:
    def __init__(self, fetchone_results=None, fetchall_results=None) -> None:
        self.fetchone_results = list(fetchone_results or [])
        self.fetchall_results = list(fetchall_results or [])
        self.executed_sql: list[str] = []
        self.executed_params: list[object] = []
        self.commits = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1
