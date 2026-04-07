from __future__ import annotations

from .eval_smoke_suites import DEFAULT_SMOKE_SUITE_ID

DEFAULT_CI_THRESHOLD_PROFILE_ID = "smoke-core-default-thresholds"


def build_default_ci_threshold_profile() -> dict[str, object]:
    return {
        "schema_version": "v1",
        "kind": "eval_ci_threshold_profile",
        "profile_id": DEFAULT_CI_THRESHOLD_PROFILE_ID,
        "suite_id": DEFAULT_SMOKE_SUITE_ID,
        "thresholds": {
            "minimum_success_rate": 0.75,
            "maximum_protocol_failures": 0,
            "maximum_average_attempts_to_success": 2.0,
            "minimum_first_attempt_success_rate": 0.5,
        },
    }


def evaluate_attempt_report_against_thresholds(
    *, report: dict[str, object], profile: dict[str, object]
) -> dict[str, object]:
    summary = dict(report.get("summary") or {})
    taxonomy = dict(report.get("taxonomy") or {})
    thresholds = dict(profile.get("thresholds") or {})

    total_runs = int(summary.get("total_runs") or 0)
    done_runs = int(summary.get("done_runs") or 0)
    total_work_items = int(summary.get("total_work_items") or 0)
    first_attempt_success_runs = int(summary.get("first_attempt_success_runs") or 0)
    average_attempts_to_success = float(
        summary.get("average_attempts_to_success") or 0.0
    )
    protocol_failures = int(taxonomy.get("protocol_failures") or 0)

    success_rate = round(done_runs / total_runs, 4) if total_runs else 0.0
    first_attempt_success_rate = (
        round(first_attempt_success_runs / total_work_items, 4)
        if total_work_items
        else 0.0
    )

    violations: list[dict[str, object]] = []

    minimum_success_rate = float(thresholds.get("minimum_success_rate") or 0.0)
    if success_rate < minimum_success_rate:
        violations.append(
            {
                "threshold": "minimum_success_rate",
                "actual": success_rate,
                "expected": minimum_success_rate,
            }
        )

    maximum_protocol_failures = int(thresholds.get("maximum_protocol_failures") or 0)
    if protocol_failures > maximum_protocol_failures:
        violations.append(
            {
                "threshold": "maximum_protocol_failures",
                "actual": protocol_failures,
                "expected": maximum_protocol_failures,
            }
        )

    maximum_average_attempts_to_success = float(
        thresholds.get("maximum_average_attempts_to_success") or 0.0
    )
    if average_attempts_to_success > maximum_average_attempts_to_success:
        violations.append(
            {
                "threshold": "maximum_average_attempts_to_success",
                "actual": average_attempts_to_success,
                "expected": maximum_average_attempts_to_success,
            }
        )

    minimum_first_attempt_success_rate = float(
        thresholds.get("minimum_first_attempt_success_rate") or 0.0
    )
    if first_attempt_success_rate < minimum_first_attempt_success_rate:
        violations.append(
            {
                "threshold": "minimum_first_attempt_success_rate",
                "actual": first_attempt_success_rate,
                "expected": minimum_first_attempt_success_rate,
            }
        )

    return {
        "passed": not violations,
        "violations": violations,
        "computed": {
            "success_rate": success_rate,
            "first_attempt_success_rate": first_attempt_success_rate,
            "protocol_failures": protocol_failures,
            "average_attempts_to_success": average_attempts_to_success,
        },
    }
