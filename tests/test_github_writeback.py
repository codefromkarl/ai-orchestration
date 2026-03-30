from stardrifter_orchestration_mvp.github_writeback import sync_issue_status_via_gh


def test_sync_issue_status_via_gh_sets_done_label_and_closes_issue():
    captured = []

    def fake_runner(command: str) -> str:
        captured.append(command)
        if "gh issue view" in command:
            return '{"labels":[{"name":"status:pending"}]}'
        return "ok"

    sync_issue_status_via_gh(
        repo="codefromkarl/stardrifter",
        issue_number=21,
        status="done",
        runner=fake_runner,
    )

    assert len(captured) == 3
    assert (
        "gh issue view 21 --repo codefromkarl/stardrifter --json labels" in captured[0]
    )
    assert "gh issue edit 21 --repo codefromkarl/stardrifter" in captured[1]
    assert "--add-label status:done" in captured[1]
    assert "--remove-label status:blocked" not in captured[1]
    assert "gh issue close 21 --repo codefromkarl/stardrifter" in captured[2]


def test_sync_issue_status_via_gh_sets_blocked_label_without_closing_issue():
    captured = []

    def fake_runner(command: str) -> str:
        captured.append(command)
        if "gh issue view" in command:
            return '{"labels":[{"name":"status:done"}]}'
        return "ok"

    sync_issue_status_via_gh(
        repo="codefromkarl/stardrifter",
        issue_number=22,
        status="blocked",
        runner=fake_runner,
    )

    assert len(captured) == 3
    assert "--add-label status:blocked" in captured[1]
    assert "--remove-label status:done" in captured[1]
    assert "gh issue reopen 22 --repo codefromkarl/stardrifter" in captured[2]


def test_sync_issue_status_via_gh_sets_decision_required_label():
    captured = []

    def fake_runner(command: str) -> str:
        captured.append(command)
        if "gh issue view" in command:
            return '{"labels":[{"name":"status:blocked"}]}'
        return "ok"

    sync_issue_status_via_gh(
        repo="codefromkarl/stardrifter",
        issue_number=23,
        status="blocked",
        decision_required=True,
        runner=fake_runner,
    )

    assert "--add-label decision-required" in captured[1]
