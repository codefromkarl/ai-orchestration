from __future__ import annotations

from typing import Any


def build_attempt_report(*, execution_runs: list[dict[str, Any]]) -> dict[str, int]:
    report = {
        "total_runs": len(execution_runs),
        "done_runs": 0,
        "needs_decision_runs": 0,
        "timeout_runs": 0,
        "protocol_error_runs": 0,
        "invalid_payload_runs": 0,
        "missing_terminal_runs": 0,
        "multiple_terminal_runs": 0,
        "non_terminal_runs": 0,
        "interrupted_runs": 0,
        "tooling_error_runs": 0,
        "upstream_api_error_runs": 0,
        "first_attempt_success_runs": 0,
        "eventual_success_runs": 0,
        "successful_work_items": 0,
        "total_work_items": 0,
        "average_attempts_to_success": 0.0,
    }
    runs_by_work_id: dict[str, list[dict[str, Any]]] = {}
    for run in execution_runs:
        status = str(run.get("status") or "")
        payload = run.get("result_payload_json") or {}
        outcome = str(payload.get("outcome") or "")
        reason_code = str(payload.get("reason_code") or "")
        work_id = str(run.get("work_id") or "")

        if work_id:
            runs_by_work_id.setdefault(work_id, []).append(run)

        if status == "done" or outcome == "done":
            report["done_runs"] += 1
        if outcome == "needs_decision":
            report["needs_decision_runs"] += 1
        if reason_code == "timeout":
            report["timeout_runs"] += 1
        if reason_code == "protocol_error":
            report["protocol_error_runs"] += 1
        if reason_code == "invalid-result-payload":
            report["invalid_payload_runs"] += 1
        if reason_code == "missing-terminal-payload":
            report["missing_terminal_runs"] += 1
        if reason_code == "multiple-terminal-payloads":
            report["multiple_terminal_runs"] += 1
        if reason_code == "non_terminal_result_payload":
            report["non_terminal_runs"] += 1
        if reason_code == "interrupted_retryable":
            report["interrupted_runs"] += 1
        if reason_code == "tooling_error":
            report["tooling_error_runs"] += 1
        if reason_code == "upstream_api_error":
            report["upstream_api_error_runs"] += 1

    attempts_to_success: list[int] = []
    report["total_work_items"] = len(runs_by_work_id)
    for runs in runs_by_work_id.values():
        first_run = runs[0]
        first_payload = first_run.get("result_payload_json") or {}
        first_done = (
            str(first_run.get("status") or "") == "done"
            or str(first_payload.get("outcome") or "") == "done"
        )
        if first_done:
            report["first_attempt_success_runs"] += 1

        success_index = None
        for index, run in enumerate(runs, start=1):
            payload = run.get("result_payload_json") or {}
            if (
                str(run.get("status") or "") == "done"
                or str(payload.get("outcome") or "") == "done"
            ):
                success_index = index
                break
        if success_index is not None:
            report["eventual_success_runs"] += 1
            report["successful_work_items"] += 1
            attempts_to_success.append(success_index)

    if attempts_to_success:
        report["average_attempts_to_success"] = round(
            sum(attempts_to_success) / len(attempts_to_success), 2
        )
    return report
