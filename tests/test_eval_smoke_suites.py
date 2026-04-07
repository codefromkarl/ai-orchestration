from taskplane.eval_smoke_suites import DEFAULT_SMOKE_SUITE_ID
from taskplane.eval_smoke_suites import build_default_smoke_suite_manifest


def test_build_default_smoke_suite_manifest_exposes_stable_suite_contract():
    manifest = build_default_smoke_suite_manifest()

    assert manifest["schema_version"] == "v1"
    assert manifest["kind"] == "eval_smoke_suite"
    assert manifest["suite_id"] == DEFAULT_SMOKE_SUITE_ID
    assert manifest["scenario_ids"] == [
        "first-attempt-success",
        "retry-then-success",
        "blocked-then-escalate",
        "verify-fail-then-replan",
    ]


def test_build_default_smoke_suite_manifest_describes_minimal_scenarios():
    manifest = build_default_smoke_suite_manifest()

    scenarios = {item["scenario_id"]: item for item in manifest["scenarios"]}
    assert scenarios["first-attempt-success"]["expected_pattern"] == "success"
    assert scenarios["retry-then-success"]["expected_pattern"] == "retry_success"
    assert (
        scenarios["blocked-then-escalate"]["expected_pattern"] == "operator_escalation"
    )
    assert (
        scenarios["verify-fail-then-replan"]["expected_pattern"]
        == "replan_after_verify_failure"
    )
