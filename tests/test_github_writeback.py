from taskplane.github_writeback import sync_issue_status_via_gh


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
    assert "gh api repos/codefromkarl/stardrifter/issues/21/labels --method PUT" in captured[1]
    assert "-f labels[]=status:done" in captured[1]
    assert "-f labels[]=status:pending" not in captured[1]
    assert "gh api repos/codefromkarl/stardrifter/issues/21 --method PATCH" in captured[2]
    assert "-f state=closed" in captured[2]


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
    assert "gh api repos/codefromkarl/stardrifter/issues/22/labels --method PUT" in captured[1]
    assert "-f labels[]=status:blocked" in captured[1]
    assert "status:done" not in captured[1]
    assert "gh api repos/codefromkarl/stardrifter/issues/22 --method PATCH" in captured[2]
    assert "-f state=open" in captured[2]


def test_sync_issue_status_via_gh_sets_decision_required_label():
    captured = []

    def fake_runner(command: str) -> str:
        captured.append(command)
        if "gh issue view" in command:
            return '{"labels":[{"name":"status:blocked"},{"name":"status:ready"}]}'
        return "ok"

    sync_issue_status_via_gh(
        repo="codefromkarl/stardrifter",
        issue_number=23,
        status="blocked",
        decision_required=True,
        runner=fake_runner,
    )

    assert "-f labels[]=decision-required" in captured[1]
    assert "-f labels[]=status:blocked" in captured[1]
    assert "status:ready" not in captured[1]
