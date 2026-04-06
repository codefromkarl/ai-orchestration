from taskplane.eval_exports import (
    EVAL_EXPORT_CURSOR_PARAMS,
    EXECUTION_OUTCOME_VALUES,
    EXECUTION_REASON_CODE_VALUES,
    VERIFICATION_CLASSIFICATION_VALUES,
    ExecutionAttemptExport,
    VerificationResultExport,
    WorkSnapshotExport,
    build_collection_response,
    build_eval_export_endpoints,
)
from taskplane.eval_exports.serializers import (
    serialize_execution_attempt,
    serialize_verification_result,
    serialize_work_snapshot,
)
from taskplane.eval_exports.read_api import (
    get_work_snapshot_export,
    list_execution_attempt_exports,
    list_verification_result_exports,
    list_work_snapshot_exports,
)
from taskplane.models import ExecutionRun, VerificationEvidence, WorkItem


def test_build_eval_export_endpoints_defines_minimal_read_only_surface():
    endpoints = build_eval_export_endpoints()

    assert [endpoint.path for endpoint in endpoints] == [
        "/api/eval/v1/work-items",
        "/api/eval/v1/work-items/{work_id}",
        "/api/eval/v1/attempts",
        "/api/eval/v1/verifications",
    ]
    assert endpoints[0].cursor_param == "after_work_id"
    assert endpoints[2].cursor_param == "after_run_id"
    assert endpoints[3].cursor_param == "after_id"


def test_eval_export_cursor_params_define_single_source_of_truth():
    assert EVAL_EXPORT_CURSOR_PARAMS == {
        "work_items": "after_work_id",
        "attempts": "after_run_id",
        "verifications": "after_id",
    }


def test_build_collection_response_wraps_export_objects_in_versioned_envelope():
    item = WorkSnapshotExport(
        work_id="task-1",
        repo="owner/repo",
        title="Test task",
        status="ready",
        lane="core",
        wave="wave-1",
    )

    payload = build_collection_response([item], next_cursor="cursor-2", has_more=True)

    assert payload["schema_version"] == "v1"
    assert payload["page"] == {
        "next_cursor": "cursor-2",
        "has_more": True,
    }
    assert payload["data"][0]["kind"] == "work_snapshot"
    assert payload["data"][0]["work_id"] == "task-1"
    assert payload["emitted_at"] is not None


def test_export_dataclasses_serialize_expected_fields():
    attempt = ExecutionAttemptExport(
        run_id=7,
        work_id="task-7",
        attempt_number=2,
        worker_name="worker-a",
        status="blocked",
        result_payload={"reason_code": "timeout"},
    )
    verification = VerificationResultExport(
        verification_id="ver-7-default",
        run_id=7,
        work_id="task-7",
        attempt_number=2,
        verifier_name="task_verifier",
        check_type="pytest",
        command="pytest -q",
        passed=False,
        classification={"result": "failed", "reason_code": "assertion_failure"},
    )

    assert attempt.to_dict()["kind"] == "execution_attempt"
    assert attempt.to_dict()["result_payload"] == {"reason_code": "timeout"}
    assert verification.to_dict()["kind"] == "verification_result"
    assert verification.to_dict()["classification"]["result"] == "failed"


def test_taxonomy_exports_match_documented_minimal_contract():
    assert EXECUTION_OUTCOME_VALUES == (
        "done",
        "blocked",
        "needs_decision",
        "already_satisfied",
    )
    assert "timeout" in EXECUTION_REASON_CODE_VALUES
    assert "protocol_error" in EXECUTION_REASON_CODE_VALUES
    assert VERIFICATION_CLASSIFICATION_VALUES == (
        "passed",
        "failed",
        "retryable_failure",
        "awaiting_approval",
    )


def test_serialize_work_snapshot_maps_core_work_item_fields():
    work_item = WorkItem(
        id="task-9",
        title="Add export schema",
        lane="core",
        wave="wave-2",
        status="blocked",
        repo="owner/repo",
        attempt_count=3,
        last_failure_reason="timeout",
        next_eligible_at="2026-04-03T12:00:00Z",
        source_issue_number=90,
        canonical_story_issue_number=12,
        task_type="documentation",
        blocking_mode="soft",
        blocked_reason="verifier timeout",
        decision_required=True,
    )

    export = serialize_work_snapshot(work_item)

    assert export == WorkSnapshotExport(
        work_id="task-9",
        repo="owner/repo",
        title="Add export schema",
        status="blocked",
        lane="core",
        wave="wave-2",
        task_type="documentation",
        blocking_mode="soft",
        attempt_count=3,
        last_failure_reason="timeout",
        next_eligible_at="2026-04-03T12:00:00Z",
        decision_required=True,
        blocked_reason="verifier timeout",
        source_issue_number=90,
        canonical_story_issue_number=12,
    )


def test_serialize_execution_attempt_maps_execution_run_fields():
    run = ExecutionRun(
        work_id="task-10",
        worker_name="worker-a",
        status="done",
        branch_name="task/task-10",
        command_digest="python -m taskplane.opencode_task_executor",
        exit_code=0,
        elapsed_ms=1400,
        stdout_digest="sha256:stdout",
        stderr_digest="sha256:stderr",
        result_payload_json={"outcome": "done"},
        partial_artifacts=("artifact://trace/10",),
    )

    export = serialize_execution_attempt(
        run,
        run_id=10,
        attempt_number=2,
        executor_name="opencode",
        session_id="ses-10",
        workspace_path="/tmp/task-10",
    )

    assert export == ExecutionAttemptExport(
        run_id=10,
        work_id="task-10",
        attempt_number=2,
        worker_name="worker-a",
        status="done",
        executor_name="opencode",
        session_id="ses-10",
        branch_name="task/task-10",
        workspace_path="/tmp/task-10",
        elapsed_ms=1400,
        exit_code=0,
        command_digest="python -m taskplane.opencode_task_executor",
        stdout_digest="sha256:stdout",
        stderr_digest="sha256:stderr",
        result_payload={"outcome": "done"},
        partial_artifacts=("artifact://trace/10",),
    )


def test_serialize_verification_result_uses_explicit_or_default_classification():
    evidence = VerificationEvidence(
        work_id="task-11",
        check_type="pytest",
        command="pytest -q",
        passed=False,
        output_digest="sha256:out",
        run_id=11,
        exit_code=1,
        elapsed_ms=2200,
        stdout_digest="sha256:stdout",
        stderr_digest="sha256:stderr",
    )

    export = serialize_verification_result(
        evidence,
        attempt_number=4,
        verifier_name="task_verifier",
    )

    assert export == VerificationResultExport(
        verification_id="ver-11-task_verifier",
        run_id=11,
        work_id="task-11",
        attempt_number=4,
        verifier_name="task_verifier",
        check_type="pytest",
        command="pytest -q",
        passed=False,
        exit_code=1,
        elapsed_ms=2200,
        stdout_digest="sha256:stdout",
        stderr_digest="sha256:stderr",
        output_digest="sha256:out",
        classification={"result": "failed"},
    )

    overridden = serialize_verification_result(
        evidence,
        attempt_number=4,
        verifier_name="task_verifier",
        classification={"result": "retryable_failure", "reason_code": "timeout"},
    )
    assert overridden.classification == {
        "result": "retryable_failure",
        "reason_code": "timeout",
    }


def test_list_work_snapshot_exports_maps_rows_to_exports_and_envelope():
    rows = [
        {
            "id": "task-20",
            "repo": "owner/repo",
            "title": "Export snapshots",
            "lane": "core",
            "wave": "wave-4",
            "status": "ready",
            "complexity": "low",
            "attempt_count": 1,
            "last_failure_reason": None,
            "next_eligible_at": None,
            "source_issue_number": 20,
            "canonical_story_issue_number": 10,
            "task_type": "core_path",
            "blocking_mode": "hard",
            "blocked_reason": None,
            "decision_required": False,
            "dod_json": {"planned_paths": ["docs/eval-boundary.md"]},
        },
        {
            "id": "task-21",
            "repo": "owner/repo",
            "title": "Export snapshots 2",
            "lane": "core",
            "wave": "wave-4",
            "status": "ready",
            "complexity": "low",
            "attempt_count": 1,
            "last_failure_reason": None,
            "next_eligible_at": None,
            "source_issue_number": 21,
            "canonical_story_issue_number": 10,
            "task_type": "core_path",
            "blocking_mode": "hard",
            "blocked_reason": None,
            "decision_required": False,
            "dod_json": {"planned_paths": ["docs/eval-boundary.md"]},
        },
    ]

    payload = list_work_snapshot_exports(
        connection=None,
        repo="owner/repo",
        after_work_id="task-19",
        limit=1,
        row_fetcher=lambda connection, repo, after_work_id, limit: rows,
        emitted_at="2026-04-03T00:00:00Z",
    )

    assert payload["schema_version"] == "v1"
    assert payload["data"][0]["kind"] == "work_snapshot"
    assert payload["data"][0]["work_id"] == "task-20"
    assert payload["page"] == {"next_cursor": "task-20", "has_more": True}


def test_work_snapshot_pagination_assumes_id_ascending_order():
    rows = [
        {
            "id": "task-101",
            "repo": "owner/repo",
            "title": "Later task",
            "lane": "core",
            "wave": "wave-6",
            "status": "ready",
            "complexity": "low",
            "attempt_count": 1,
            "last_failure_reason": None,
            "next_eligible_at": None,
            "source_issue_number": 101,
            "canonical_story_issue_number": 11,
            "task_type": "core_path",
            "blocking_mode": "hard",
            "blocked_reason": None,
            "decision_required": False,
            "dod_json": {"planned_paths": []},
        },
        {
            "id": "task-102",
            "repo": "owner/repo",
            "title": "Latest task",
            "lane": "core",
            "wave": "wave-6",
            "status": "ready",
            "complexity": "low",
            "attempt_count": 1,
            "last_failure_reason": None,
            "next_eligible_at": None,
            "source_issue_number": 102,
            "canonical_story_issue_number": 11,
            "task_type": "core_path",
            "blocking_mode": "hard",
            "blocked_reason": None,
            "decision_required": False,
            "dod_json": {"planned_paths": []},
        },
    ]

    payload = list_work_snapshot_exports(
        connection=None,
        repo="owner/repo",
        after_work_id="task-100",
        limit=1,
        row_fetcher=lambda connection, repo, after_work_id, limit: rows,
        emitted_at="2026-04-03T00:00:00Z",
    )

    assert payload["data"][0]["work_id"] == "task-101"
    assert payload["page"] == {"next_cursor": "task-101", "has_more": True}


def test_list_work_snapshot_exports_marks_final_page_without_extra_row():
    rows = [
        {
            "id": "task-30",
            "repo": "owner/repo",
            "title": "Final page",
            "lane": "core",
            "wave": "wave-5",
            "status": "ready",
            "complexity": "low",
            "attempt_count": 1,
            "last_failure_reason": None,
            "next_eligible_at": None,
            "source_issue_number": 30,
            "canonical_story_issue_number": 11,
            "task_type": "core_path",
            "blocking_mode": "hard",
            "blocked_reason": None,
            "decision_required": False,
            "dod_json": {"planned_paths": []},
        }
    ]

    payload = list_work_snapshot_exports(
        connection=None,
        repo="owner/repo",
        after_work_id="task-29",
        limit=1,
        row_fetcher=lambda connection, repo, after_work_id, limit: rows,
        emitted_at="2026-04-03T00:00:00Z",
    )

    assert payload["data"][0]["work_id"] == "task-30"
    assert payload["page"] == {"next_cursor": None, "has_more": False}


def test_list_execution_attempt_exports_maps_rows_to_exports_and_passes_cursor():
    rows = [
        {
            "id": 50,
            "work_id": "task-50",
            "worker_name": "worker-z",
            "status": "blocked",
            "branch_name": "task/task-50",
            "command_digest": "python -m taskplane.opencode_task_executor",
            "exit_code": 1,
            "elapsed_ms": 500,
            "stdout_digest": "sha256:stdout",
            "stderr_digest": "sha256:stderr",
            "result_payload_json": {"reason_code": "timeout"},
            "started_at": "2026-04-03T00:00:00Z",
            "finished_at": "2026-04-03T00:01:00Z",
            "attempt_number": 1,
        },
        {
            "id": 51,
            "work_id": "task-50",
            "worker_name": "worker-z",
            "status": "done",
            "branch_name": "task/task-50",
            "command_digest": "python -m taskplane.opencode_task_executor",
            "exit_code": 0,
            "elapsed_ms": 450,
            "stdout_digest": "sha256:stdout2",
            "stderr_digest": "sha256:stderr2",
            "result_payload_json": {"outcome": "done"},
            "started_at": "2026-04-03T00:02:00Z",
            "finished_at": "2026-04-03T00:03:00Z",
            "attempt_number": 2,
        },
    ]

    payload = list_execution_attempt_exports(
        connection=None,
        repo="owner/repo",
        after_run_id=40,
        limit=1,
        row_fetcher=lambda connection, repo, after_run_id, limit: rows,
        emitted_at="2026-04-03T00:00:00Z",
    )

    assert payload["data"][0]["kind"] == "execution_attempt"
    assert payload["data"][0]["run_id"] == 50
    assert payload["data"][0]["attempt_number"] == 1
    assert payload["page"] == {"next_cursor": "50", "has_more": True}


def test_list_verification_result_exports_maps_rows_to_exports():
    rows = [
        {
            "id": 61,
            "run_id": 50,
            "work_id": "task-50",
            "check_type": "pytest",
            "command": "pytest -q",
            "passed": True,
            "output_digest": "sha256:out",
            "exit_code": 0,
            "elapsed_ms": 300,
            "stdout_digest": "sha256:stdout",
            "stderr_digest": "sha256:stderr",
            "attempt_number": 1,
        },
        {
            "id": 62,
            "run_id": 51,
            "work_id": "task-50",
            "check_type": "pytest",
            "command": "pytest -q",
            "passed": False,
            "output_digest": "sha256:out2",
            "exit_code": 1,
            "elapsed_ms": 350,
            "stdout_digest": "sha256:stdout2",
            "stderr_digest": "sha256:stderr2",
            "attempt_number": 2,
        },
    ]

    payload = list_verification_result_exports(
        connection=None,
        repo="owner/repo",
        after_id=60,
        limit=1,
        row_fetcher=lambda connection, repo, after_id, limit: rows,
        emitted_at="2026-04-03T00:00:00Z",
    )

    assert payload["data"][0]["kind"] == "verification_result"
    assert payload["data"][0]["verification_id"] == "ver-50-task_verifier"
    assert payload["data"][0]["attempt_number"] == 1
    assert payload["data"][0]["classification"] == {"result": "passed"}
    assert payload["page"] == {"next_cursor": "61", "has_more": True}


def test_list_execution_attempt_exports_marks_final_page_without_extra_row():
    rows = [
        {
            "id": 70,
            "work_id": "task-70",
            "worker_name": "worker-a",
            "status": "done",
            "branch_name": "task/task-70",
            "command_digest": "digest",
            "exit_code": 0,
            "elapsed_ms": 100,
            "stdout_digest": "stdout",
            "stderr_digest": "stderr",
            "result_payload_json": {"outcome": "done"},
            "started_at": "2026-04-03T00:00:00Z",
            "finished_at": "2026-04-03T00:00:01Z",
            "attempt_number": 1,
        }
    ]

    payload = list_execution_attempt_exports(
        connection=None,
        repo="owner/repo",
        after_run_id=69,
        limit=1,
        row_fetcher=lambda connection, repo, after_run_id, limit: rows,
        emitted_at="2026-04-03T00:00:00Z",
    )

    assert payload["data"][0]["run_id"] == 70
    assert payload["page"] == {"next_cursor": None, "has_more": False}


def test_get_work_snapshot_export_returns_single_export_or_none():
    row = {
        "id": "task-21",
        "repo": "owner/repo",
        "title": "Export single snapshot",
        "lane": "core",
        "wave": "wave-4",
        "status": "ready",
        "complexity": "low",
        "attempt_count": 1,
        "last_failure_reason": None,
        "next_eligible_at": None,
        "source_issue_number": 21,
        "canonical_story_issue_number": 10,
        "task_type": "core_path",
        "blocking_mode": "hard",
        "blocked_reason": None,
        "decision_required": False,
        "dod_json": {"planned_paths": ["docs/eval-boundary.md"]},
    }

    export = get_work_snapshot_export(
        connection=None,
        repo="owner/repo",
        work_id="task-21",
        row_fetcher=lambda connection, repo, work_id: row,
    )
    missing = get_work_snapshot_export(
        connection=None,
        repo="owner/repo",
        work_id="missing",
        row_fetcher=lambda connection, repo, work_id: None,
    )

    assert export is not None
    assert export.work_id == "task-21"
    assert export.kind == "work_snapshot"
    assert missing is None
