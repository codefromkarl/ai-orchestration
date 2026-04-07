from taskplane.attempt_report import build_attempt_report


def test_build_attempt_report_counts_execution_outcomes():
    report = build_attempt_report(
        execution_runs=[
            {
                "status": "done",
                "result_payload_json": {"outcome": "done"},
            },
            {
                "status": "blocked",
                "result_payload_json": {"outcome": "needs_decision"},
            },
            {
                "status": "blocked",
                "result_payload_json": {"reason_code": "timeout"},
            },
            {
                "status": "blocked",
                "result_payload_json": {"reason_code": "protocol_error"},
            },
            {
                "status": "blocked",
                "result_payload_json": {"reason_code": "invalid-result-payload"},
            },
            {
                "status": "blocked",
                "result_payload_json": {"reason_code": "missing-terminal-payload"},
            },
            {
                "status": "blocked",
                "result_payload_json": {"reason_code": "multiple-terminal-payloads"},
            },
            {
                "status": "blocked",
                "result_payload_json": {"reason_code": "non_terminal_result_payload"},
            },
            {
                "status": "blocked",
                "result_payload_json": {"reason_code": "interrupted_retryable"},
            },
            {
                "status": "blocked",
                "result_payload_json": {"reason_code": "tooling_error"},
            },
            {
                "status": "blocked",
                "result_payload_json": {"reason_code": "upstream_api_error"},
            },
        ]
    )

    expected_summary = {
        "total_runs": 11,
        "done_runs": 1,
        "needs_decision_runs": 1,
        "timeout_runs": 1,
        "protocol_error_runs": 1,
        "invalid_payload_runs": 1,
        "missing_terminal_runs": 1,
        "multiple_terminal_runs": 1,
        "non_terminal_runs": 1,
        "interrupted_runs": 1,
        "tooling_error_runs": 1,
        "upstream_api_error_runs": 1,
        "first_attempt_success_runs": 0,
        "eventual_success_runs": 0,
        "successful_work_items": 0,
        "total_work_items": 0,
        "average_attempts_to_success": 0.0,
    }
    for key, value in expected_summary.items():
        assert report[key] == value
    assert report["summary"] == expected_summary


def test_build_attempt_report_computes_success_rate_metrics_by_work_item():
    report = build_attempt_report(
        execution_runs=[
            {
                "work_id": "task-1",
                "status": "done",
                "result_payload_json": {"outcome": "done"},
            },
            {
                "work_id": "task-2",
                "status": "blocked",
                "result_payload_json": {"reason_code": "timeout"},
            },
            {
                "work_id": "task-2",
                "status": "done",
                "result_payload_json": {"outcome": "done"},
            },
            {
                "work_id": "task-3",
                "status": "blocked",
                "result_payload_json": {"outcome": "needs_decision"},
            },
        ]
    )

    assert report["first_attempt_success_runs"] == 1
    assert report["eventual_success_runs"] == 2
    assert report["successful_work_items"] == 2
    assert report["total_work_items"] == 3
    assert report["average_attempts_to_success"] == 1.5


def test_build_attempt_report_emits_versioned_fact_summary():
    report = build_attempt_report(
        execution_runs=[
            {
                "work_id": "task-1",
                "status": "done",
                "result_payload_json": {"outcome": "done"},
            }
        ]
    )

    assert report["schema_version"] == "v1"
    assert report["kind"] == "attempt_report"
    assert report["summary"]["total_runs"] == 1
    assert report["summary"]["done_runs"] == 1
