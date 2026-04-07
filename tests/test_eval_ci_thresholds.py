from taskplane.eval_ci_thresholds import DEFAULT_CI_THRESHOLD_PROFILE_ID
from taskplane.eval_ci_thresholds import build_default_ci_threshold_profile
from taskplane.eval_ci_thresholds import evaluate_attempt_report_against_thresholds


def test_build_default_ci_threshold_profile_exposes_stable_contract():
    profile = build_default_ci_threshold_profile()

    assert profile["schema_version"] == "v1"
    assert profile["kind"] == "eval_ci_threshold_profile"
    assert profile["profile_id"] == DEFAULT_CI_THRESHOLD_PROFILE_ID
    assert profile["suite_id"] == "smoke-core"


def test_build_default_ci_threshold_profile_contains_minimal_gate_keys():
    profile = build_default_ci_threshold_profile()

    assert profile["thresholds"] == {
        "minimum_success_rate": 0.75,
        "maximum_protocol_failures": 0,
        "maximum_average_attempts_to_success": 2.0,
        "minimum_first_attempt_success_rate": 0.5,
    }


def test_evaluate_attempt_report_against_thresholds_passes_when_metrics_clear_barriers():
    result = evaluate_attempt_report_against_thresholds(
        report={
            "summary": {
                "total_runs": 4,
                "done_runs": 4,
                "total_work_items": 4,
                "first_attempt_success_runs": 3,
                "average_attempts_to_success": 1.25,
            },
            "taxonomy": {"protocol_failures": 0},
        },
        profile=build_default_ci_threshold_profile(),
    )

    assert result["passed"] is True
    assert result["violations"] == []
    assert result["computed"]["success_rate"] == 1.0
    assert result["computed"]["first_attempt_success_rate"] == 0.75


def test_evaluate_attempt_report_against_thresholds_returns_all_violations():
    result = evaluate_attempt_report_against_thresholds(
        report={
            "summary": {
                "total_runs": 4,
                "done_runs": 2,
                "total_work_items": 4,
                "first_attempt_success_runs": 1,
                "average_attempts_to_success": 2.5,
            },
            "taxonomy": {"protocol_failures": 2},
        },
        profile=build_default_ci_threshold_profile(),
    )

    assert result["passed"] is False
    assert [item["threshold"] for item in result["violations"]] == [
        "minimum_success_rate",
        "maximum_protocol_failures",
        "maximum_average_attempts_to_success",
        "minimum_first_attempt_success_rate",
    ]
