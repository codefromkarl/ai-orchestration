import json

from taskplane.io_schemas import (
    CheckResult,
    FailureReport,
    PatchProposal,
    TaskSummary,
    VerificationResult,
)


def test_failure_report_roundtrip():
    report = FailureReport(
        work_id="task-123",
        attempt=2,
        reason_code="timeout",
        summary="Execution timed out after 1800s",
        execution_journal="step1 done, step2 failed",
        artifacts=["task-123/stdout/01.txt"],
        changed_files=["src/main.py"],
        test_output="TestFoo::test_bar FAILED",
        timestamp="2026-01-01T00:00:00",
    )

    raw = report.to_json()
    restored = FailureReport.from_json(raw)

    assert restored.work_id == "task-123"
    assert restored.attempt == 2
    assert restored.reason_code == "timeout"
    assert restored.artifacts == ["task-123/stdout/01.txt"]
    assert restored.changed_files == ["src/main.py"]


def test_patch_proposal_roundtrip():
    proposal = PatchProposal(
        work_id="task-456",
        attempt=1,
        patch_diff="--- a/src/main.py\n+++ b/src/main.py\n@@ -1,3 +1,4 @@\n+import os",
        changed_files=["src/main.py"],
        rationale="Added missing import",
        risk_level="low",
        verification_hints=["run pytest tests/test_main.py"],
        author_agent="claude-code",
    )

    raw = proposal.to_json()
    restored = PatchProposal.from_json(raw)

    assert restored.work_id == "task-456"
    assert restored.risk_level == "low"
    assert restored.author_agent == "claude-code"
    assert "import os" in restored.patch_diff


def test_verification_result_roundtrip():
    result = VerificationResult(
        work_id="task-789",
        run_id=42,
        checks=[
            CheckResult(
                check_type="pytest",
                passed=True,
                command="pytest tests/",
                output_digest="sha256:abc",
                exit_code=0,
                elapsed_ms=5000,
            ),
            CheckResult(
                check_type="lint",
                passed=True,
                command="ruff check src/",
                output_digest="sha256:def",
                exit_code=0,
            ),
        ],
        overall_passed=True,
        evidence_artifacts=["task-789/verification_result/01.json"],
        summary="All checks passed",
    )

    raw = result.to_json()
    restored = VerificationResult.from_json(raw)

    assert restored.work_id == "task-789"
    assert restored.overall_passed is True
    assert len(restored.checks) == 2
    assert restored.checks[0].check_type == "pytest"
    assert restored.checks[1].check_type == "lint"


def test_task_summary_roundtrip():
    summary = TaskSummary(
        work_id="task-101",
        outcome="done",
        changed_files=["src/main.py", "tests/test_main.py"],
        commit_sha="abc123",
        verification_passed=True,
        artifacts=["task-101/task_summary/01.json"],
        summary="Task completed successfully",
        attempt_count=1,
    )

    raw = summary.to_json()
    restored = TaskSummary.from_json(raw)

    assert restored.work_id == "task-101"
    assert restored.outcome == "done"
    assert restored.commit_sha == "abc123"
    assert restored.verification_passed is True


def test_task_summary_failed_outcome():
    summary = TaskSummary(
        work_id="task-202",
        outcome="failed",
        summary="Could not resolve dependency",
        attempt_count=3,
    )

    raw = summary.to_json()
    data = json.loads(raw)

    assert data["outcome"] == "failed"
    assert data["attempt_count"] == 3


def test_failure_report_serialization_is_valid_json():
    report = FailureReport(
        work_id="task-303",
        attempt=1,
        reason_code="assertion_failure",
        summary="Test failed",
    )

    raw = report.to_json()
    data = json.loads(raw)

    assert data["work_id"] == "task-303"
    assert data["reason_code"] == "assertion_failure"


def test_verification_result_empty_checks():
    result = VerificationResult(
        work_id="task-404",
        run_id=1,
        overall_passed=False,
        summary="No checks configured",
    )

    raw = result.to_json()
    restored = VerificationResult.from_json(raw)

    assert restored.checks == []
    assert restored.overall_passed is False


def test_patch_proposal_default_values():
    proposal = PatchProposal(
        work_id="task-505",
        attempt=1,
        patch_diff="diff content",
    )

    assert proposal.risk_level == "medium"
    assert proposal.verification_hints == []
    assert proposal.author_agent == ""
    assert proposal.changed_files == []
    assert proposal.rationale == ""
