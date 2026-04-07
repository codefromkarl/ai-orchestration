from __future__ import annotations

DEFAULT_SMOKE_SUITE_ID = "smoke-core"


def build_default_smoke_suite_manifest() -> dict[str, object]:
    scenarios = [
        {
            "scenario_id": "first-attempt-success",
            "summary": "A task succeeds on the first attempt without retries or escalation.",
            "expected_pattern": "success",
        },
        {
            "scenario_id": "retry-then-success",
            "summary": "A task fails once, retries, and then succeeds.",
            "expected_pattern": "retry_success",
        },
        {
            "scenario_id": "blocked-then-escalate",
            "summary": "A task blocks and requires explicit operator escalation.",
            "expected_pattern": "operator_escalation",
        },
        {
            "scenario_id": "verify-fail-then-replan",
            "summary": "Verification fails and the next transition is a replan.",
            "expected_pattern": "replan_after_verify_failure",
        },
    ]
    return {
        "schema_version": "v1",
        "kind": "eval_smoke_suite",
        "suite_id": DEFAULT_SMOKE_SUITE_ID,
        "scenario_ids": [item["scenario_id"] for item in scenarios],
        "scenarios": scenarios,
    }
