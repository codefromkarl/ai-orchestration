from taskplane.reconciliation import (
    build_reconciliation_report,
    repair_reconciliation_drift,
)


def test_build_reconciliation_report_detects_task_done_vs_github_status_drift():
    report = build_reconciliation_report(
        task_rows=[
            {
                "issue_number": 24,
                "db_status": "done",
                "db_decision_required": False,
                "github_state": "OPEN",
                "status_label": "status:blocked",
                "pull_url": None,
            }
        ],
        epic_rows=[],
        story_rows=[],
    )

    assert report["task_drift"] == [
        {
            "issue_number": 24,
            "kind": "task_status_mismatch",
            "db_status": "done",
            "github_state": "OPEN",
            "github_status_label": "status:blocked",
        }
    ]


def test_build_reconciliation_report_treats_pending_task_with_pending_label_as_aligned():
    report = build_reconciliation_report(
        task_rows=[
            {
                "issue_number": 91,
                "db_status": "pending",
                "db_decision_required": False,
                "github_state": "OPEN",
                "status_label": "status:pending",
                "pull_url": None,
            }
        ],
        epic_rows=[],
        story_rows=[],
    )

    assert report["task_drift"] == []


def test_build_reconciliation_report_treats_in_progress_task_with_in_progress_label_as_aligned():
    report = build_reconciliation_report(
        task_rows=[
            {
                "issue_number": 135,
                "db_status": "in_progress",
                "db_decision_required": False,
                "github_state": "OPEN",
                "status_label": "status:in-progress",
                "pull_url": None,
            }
        ],
        epic_rows=[],
        story_rows=[],
    )

    assert report["task_drift"] == []


def test_build_reconciliation_report_detects_story_done_vs_github_status_drift():
    report = build_reconciliation_report(
        task_rows=[],
        epic_rows=[],
        story_rows=[
            {
                "issue_number": 29,
                "db_story_complete": True,
                "github_state": "OPEN",
                "status_label": "status:blocked",
            }
        ],
    )

    assert report["story_drift"] == [
        {
            "issue_number": 29,
            "kind": "story_status_mismatch",
            "db_story_complete": True,
            "github_state": "OPEN",
            "github_status_label": "status:blocked",
        }
    ]


def test_build_reconciliation_report_detects_missing_pr_link_for_done_task():
    report = build_reconciliation_report(
        task_rows=[
            {
                "issue_number": 26,
                "db_status": "done",
                "db_decision_required": False,
                "github_state": "CLOSED",
                "status_label": "status:done",
                "pull_url": None,
            }
        ],
        epic_rows=[],
        story_rows=[],
    )

    assert report["task_drift"] == [
        {
            "issue_number": 26,
            "kind": "missing_pull_request_link",
            "db_status": "done",
        }
    ]


def test_build_reconciliation_report_ignores_aligned_rows():
    report = build_reconciliation_report(
        task_rows=[
            {
                "issue_number": 27,
                "db_status": "done",
                "db_decision_required": False,
                "github_state": "CLOSED",
                "status_label": "status:done",
                "pull_url": "https://github.com/codefromkarl/stardrifter/pull/81",
            }
        ],
        epic_rows=[
            {
                "issue_number": 13,
                "db_epic_complete": True,
                "github_state": "CLOSED",
                "status_label": "status:done",
            }
        ],
        story_rows=[
            {
                "issue_number": 30,
                "db_story_complete": True,
                "github_state": "CLOSED",
                "status_label": "status:done",
            }
        ],
    )

    assert report["task_drift"] == []
    assert report["epic_drift"] == []
    assert report["story_drift"] == []


def test_build_reconciliation_report_detects_missing_story_branch_and_worktree():
    report = build_reconciliation_report(
        task_rows=[],
        epic_rows=[],
        story_rows=[
            {
                "issue_number": 41,
                "db_story_complete": False,
                "execution_status": "active",
                "story_task_count": 1,
                "canonical_branch_exists": False,
                "canonical_worktree_exists": False,
                "github_state": "OPEN",
                "status_label": "status:pending",
            }
        ],
    )

    assert report["story_drift"] == [
        {
            "issue_number": 41,
            "kind": "missing_story_branch",
            "execution_status": "active",
            "story_task_count": 1,
        },
        {
            "issue_number": 41,
            "kind": "missing_story_worktree",
            "execution_status": "active",
            "story_task_count": 1,
        },
    ]


def test_build_reconciliation_report_detects_stale_done_story_execution_status():
    report = build_reconciliation_report(
        task_rows=[],
        epic_rows=[],
        story_rows=[
            {
                "issue_number": 25,
                "db_story_complete": False,
                "execution_status": "done",
                "story_task_count": 3,
                "canonical_branch_exists": True,
                "canonical_worktree_exists": True,
                "github_state": "OPEN",
                "status_label": "status:pending",
            }
        ],
    )

    assert report["story_drift"] == [
        {
            "issue_number": 25,
            "kind": "story_execution_state_stale",
            "execution_status": "done",
            "story_task_count": 3,
        }
    ]


def test_build_reconciliation_report_detects_epic_done_vs_github_status_drift():
    report = build_reconciliation_report(
        task_rows=[],
        epic_rows=[
            {
                "issue_number": 13,
                "db_epic_complete": True,
                "github_state": "OPEN",
                "status_label": "status:blocked",
            }
        ],
        story_rows=[],
    )

    assert report["epic_drift"] == [
        {
            "issue_number": 13,
            "kind": "epic_status_mismatch",
            "db_epic_complete": True,
            "github_state": "OPEN",
            "github_status_label": "status:blocked",
        }
    ]


def test_repair_reconciliation_drift_repairs_task_status_mismatch_only():
    repairs: list[dict[str, object]] = []

    result = repair_reconciliation_drift(
        report={
            "task_drift": [
                {
                    "issue_number": 24,
                    "kind": "task_status_mismatch",
                    "db_status": "done",
                    "db_decision_required": False,
                },
                {
                    "issue_number": 26,
                    "kind": "missing_pull_request_link",
                    "db_status": "done",
                },
            ],
            "epic_drift": [],
            "story_drift": [],
        },
        repo="codefromkarl/stardrifter",
        task_repair=lambda **kwargs: repairs.append(kwargs),
        epic_repair=lambda **kwargs: repairs.append(kwargs),
        story_repair=lambda **kwargs: repairs.append(kwargs),
    )

    assert repairs == [
        {
            "repo": "codefromkarl/stardrifter",
            "issue_number": 24,
            "status": "done",
            "decision_required": False,
        }
    ]
    assert result == {
        "task_repaired": 1,
        "epic_repaired": 0,
        "story_repaired": 0,
        "task_skipped": 1,
        "epic_skipped": 0,
        "story_skipped": 0,
    }


def test_repair_reconciliation_drift_repairs_story_status_mismatch():
    repairs: list[dict[str, object]] = []

    result = repair_reconciliation_drift(
        report={
            "task_drift": [],
            "epic_drift": [],
            "story_drift": [
                {
                    "issue_number": 29,
                    "kind": "story_status_mismatch",
                    "db_story_complete": True,
                }
            ],
        },
        repo="codefromkarl/stardrifter",
        task_repair=lambda **kwargs: repairs.append(kwargs),
        epic_repair=lambda **kwargs: repairs.append(kwargs),
        story_repair=lambda **kwargs: repairs.append(kwargs),
    )

    assert repairs == [
        {
            "repo": "codefromkarl/stardrifter",
            "issue_number": 29,
            "status": "done",
            "decision_required": False,
        }
    ]
    assert result == {
        "task_repaired": 0,
        "epic_repaired": 0,
        "story_repaired": 1,
        "task_skipped": 0,
        "epic_skipped": 0,
        "story_skipped": 0,
    }


def test_repair_reconciliation_drift_repairs_epic_status_mismatch():
    repairs: list[dict[str, object]] = []

    result = repair_reconciliation_drift(
        report={
            "task_drift": [],
            "epic_drift": [
                {
                    "issue_number": 13,
                    "kind": "epic_status_mismatch",
                    "db_epic_complete": True,
                }
            ],
            "story_drift": [],
        },
        repo="codefromkarl/stardrifter",
        task_repair=lambda **kwargs: repairs.append(kwargs),
        epic_repair=lambda **kwargs: repairs.append(kwargs),
        story_repair=lambda **kwargs: repairs.append(kwargs),
    )

    assert repairs == [
        {
            "repo": "codefromkarl/stardrifter",
            "issue_number": 13,
            "status": "done",
            "decision_required": False,
        }
    ]
    assert result == {
        "task_repaired": 0,
        "epic_repaired": 1,
        "story_repaired": 0,
        "task_skipped": 0,
        "epic_skipped": 0,
        "story_skipped": 0,
    }
