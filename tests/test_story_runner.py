from taskplane.models import (
    ExecutionGuardrailContext,
    StoryVerificationRun,
    VerificationEvidence,
    WorkDependency,
    WorkItem,
    WorkTarget,
)
from taskplane.repository import InMemoryControlPlaneRepository
from taskplane.story_runner import run_story_until_settled
from taskplane.worker import ExecutionResult
from taskplane import story_runner as story_runner_module
from taskplane.git_committer import StoryIntegrationResult


def test_run_story_until_settled_completes_all_story_tasks():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-56",
                title="task 56",
                lane="Lane 03",
                wave="wave-2",
                status="pending",
            ),
            WorkItem(
                id="issue-57",
                title="task 57",
                lane="Lane 03",
                wave="wave-2",
                status="pending",
            ),
        ],
        dependencies=[
            WorkDependency(work_id="issue-57", depends_on_work_id="issue-56")
        ],
        targets_by_work_id={
            "issue-56": [
                WorkTarget(
                    work_id="issue-56",
                    target_path="docs/domains/03-economy-markets/execution-plan.md",
                    target_type="doc",
                    owner_lane="Lane 03",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ],
            "issue-57": [
                WorkTarget(
                    work_id="issue-57",
                    target_path="docs/domains/03-economy-markets/execution-plan.md",
                    target_type="doc",
                    owner_lane="Lane 03",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ],
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-2"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_story_until_settled(
        story_issue_number=29,
        story_work_item_ids=["issue-56", "issue-57"],
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True, summary=f"executed {work_item.id}"
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
        committer=None,
    )

    assert result.story_issue_number == 29
    assert result.story_complete is True
    assert result.completed_work_item_ids == ["issue-56", "issue-57"]
    assert result.blocked_work_item_ids == []


def test_run_story_until_settled_stops_when_task_blocks():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-47",
                title="task 47",
                lane="Lane 02",
                wave="wave-2",
                status="pending",
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "issue-47": [
                WorkTarget(
                    work_id="issue-47",
                    target_path="src/stardrifter_engine/campaign/runtime.py",
                    target_type="file",
                    owner_lane="Lane 02",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ],
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-2"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_story_until_settled(
        story_issue_number=24,
        story_work_item_ids=["issue-47"],
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=False, summary="compile failed"
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=False,
            output_digest="should not run",
        ),
        committer=None,
    )

    assert result.story_complete is False
    assert result.blocked_work_item_ids == ["issue-47"]


def test_run_story_until_settled_handles_checkpoint_then_completion():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-58",
                title="task 58",
                lane="Lane 02",
                wave="wave-2",
                status="pending",
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "issue-58": [
                WorkTarget(
                    work_id="issue-58",
                    target_path="src/stardrifter_engine/campaign/runtime.py",
                    target_type="file",
                    owner_lane="Lane 02",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ],
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-2"},
        frozen_prefixes=("docs/authority/",),
    )
    calls = 0

    def executor(work_item, workspace_path=None, execution_context=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ExecutionResult(
                success=True,
                summary="checkpoint",
                result_payload_json={
                    "execution_kind": "checkpoint",
                    "phase": "implementing",
                    "summary": "step 1 complete",
                },
            )
        return ExecutionResult(
            success=True,
            summary="done",
            result_payload_json={
                "outcome": "done",
                "summary": "finished",
                "changed_paths": [
                    "src/stardrifter_engine/campaign/runtime.py"
                ],
            },
        )

    result = run_story_until_settled(
        story_issue_number=24,
        story_work_item_ids=["issue-58"],
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=executor,
        verifier=lambda work_item, workspace_path=None, execution_context=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
        committer=None,
    )

    assert result.story_complete is True
    assert calls == 2


def test_run_story_until_settled_does_not_mark_empty_story_as_complete():
    repository = InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-2"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_story_until_settled(
        story_issue_number=29,
        story_work_item_ids=[],
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True, summary="noop"
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
        committer=None,
    )

    assert result.story_complete is False
    assert result.completed_work_item_ids == []
    assert result.remaining_work_item_ids == []


def test_run_story_until_settled_syncs_story_done_to_github_when_complete():
    writes: list[dict[str, object]] = []
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-56",
                title="task 56",
                lane="Lane 03",
                wave="wave-2",
                status="pending",
                repo="codefromkarl/stardrifter",
                source_issue_number=56,
                canonical_story_issue_number=29,
            ),
            WorkItem(
                id="issue-57",
                title="task 57",
                lane="Lane 03",
                wave="wave-2",
                status="pending",
                repo="codefromkarl/stardrifter",
                source_issue_number=57,
                canonical_story_issue_number=29,
            ),
        ],
        dependencies=[
            WorkDependency(work_id="issue-57", depends_on_work_id="issue-56")
        ],
        targets_by_work_id={
            "issue-56": [
                WorkTarget(
                    work_id="issue-56",
                    target_path="docs/domains/03-economy-markets/execution-plan.md",
                    target_type="doc",
                    owner_lane="Lane 03",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ],
            "issue-57": [
                WorkTarget(
                    work_id="issue-57",
                    target_path="docs/domains/03-economy-markets/execution-plan.md",
                    target_type="doc",
                    owner_lane="Lane 03",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ],
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-2"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_story_until_settled(
        story_issue_number=29,
        story_work_item_ids=["issue-56", "issue-57"],
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True, summary=f"executed {work_item.id}"
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
        committer=None,
        story_github_writeback=lambda **kwargs: writes.append(kwargs),
    )

    assert result.story_complete is True
    assert result.reason_code == "story_complete"
    assert writes == [
        {
            "repo": "codefromkarl/stardrifter",
            "issue_number": 29,
            "status": "done",
            "decision_required": False,
        }
    ]


def test_run_story_until_settled_requires_story_verification_before_marking_done():
    writes: list[dict[str, object]] = []
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-56",
                title="task 56",
                lane="Lane 03",
                wave="wave-2",
                status="done",
                repo="codefromkarl/stardrifter",
                source_issue_number=56,
                canonical_story_issue_number=29,
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "issue-56": [
                WorkTarget(
                    work_id="issue-56",
                    target_path="tests/unit/test_story.py",
                    target_type="file",
                    owner_lane="Lane 03",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ],
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-2"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_story_until_settled(
        story_issue_number=29,
        story_work_item_ids=["issue-56"],
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True, summary=f"executed {work_item.id}"
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
        story_verifier=lambda **kwargs: StoryVerificationRun(
            repo="codefromkarl/stardrifter",
            story_issue_number=29,
            check_type="pytest",
            command="python3 -m pytest -q tests/integration/test_story_29.py",
            passed=False,
            summary="story regression failed",
            output_digest="failed",
            exit_code=1,
        ),
        committer=None,
        story_github_writeback=lambda **kwargs: writes.append(kwargs),
    )

    assert result.story_complete is False
    assert result.reason_code == "story_verification_failed"
    assert writes == []
    assert len(repository.story_verification_runs) == 1
    assert repository.story_verification_runs[0].passed is False


def test_run_story_until_settled_accepts_explicit_story_writeback_and_integrator_objects():
    writes: list[dict[str, object]] = []
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-156",
                title="task 156",
                lane="Lane 06",
                wave="wave-2",
                status="done",
                repo="codefromkarl/stardrifter",
                source_issue_number=156,
                canonical_story_issue_number=39,
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "issue-156": [
                WorkTarget(
                    work_id="issue-156",
                    target_path="src/story39.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-2"},
        frozen_prefixes=("docs/authority/",),
    )

    class IntegrationResult:
        merged = True
        promoted = False
        merge_commit_sha = "abc123"
        promotion_commit_sha = None
        blocked_reason = None
        summary = "merged"
        pull_number = 77
        pull_url = "https://example.test/pull/77"

    class ExplicitStoryWriteback:
        def write_back(
            self,
            *,
            repo: str,
            issue_number: int,
            status: str,
            decision_required: bool = False,
        ) -> None:
            writes.append(
                {
                    "repo": repo,
                    "issue_number": issue_number,
                    "status": status,
                    "decision_required": decision_required,
                }
            )

    class ExplicitStoryIntegrator:
        def integrate(
            self,
            *,
            story_issue_number: int,
            story_work_items: list[WorkItem],
        ) -> IntegrationResult:
            assert story_issue_number == 39
            assert [item.id for item in story_work_items] == ["issue-156"]
            return IntegrationResult()

    result = run_story_until_settled(
        story_issue_number=39,
        story_work_item_ids=["issue-156"],
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True, summary=f"executed {work_item.id}"
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
        committer=None,
        story_github_writeback=ExplicitStoryWriteback(),
        story_integrator=ExplicitStoryIntegrator(),
    )

    assert result.story_complete is True
    assert writes == [
        {
            "repo": "codefromkarl/stardrifter",
            "issue_number": 39,
            "status": "done",
            "decision_required": False,
        }
    ]
    assert repository.story_integration_runs[-1].merged is True
    assert repository.story_pull_request_links[("codefromkarl/stardrifter", 39)] == {
        "repo": "codefromkarl/stardrifter",
        "story_issue_number": 39,
        "pull_number": 77,
        "pull_url": "https://example.test/pull/77",
    }


def test_run_story_until_settled_records_story_integration_run():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-103",
                title="task 103",
                lane="Lane 06",
                wave="Wave0",
                status="done",
                repo="codefromkarl/stardrifter",
                source_issue_number=103,
                canonical_story_issue_number=41,
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "issue-103": [
                WorkTarget(
                    work_id="issue-103",
                    target_path="tests/unit/test_projection.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ],
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"Wave0"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_story_until_settled(
        story_issue_number=41,
        story_work_item_ids=["issue-103"],
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True, summary=f"executed {work_item.id}"
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
        committer=None,
        story_integrator=lambda **kwargs: StoryIntegrationResult(
            merged=True,
            merge_commit_sha="abc123",
            promoted=False,
            summary="merged story/41 into main",
        ),
    )

    assert result.story_complete is True
    assert len(repository.story_integration_runs) == 1
    run = repository.story_integration_runs[0]
    assert run.repo == "codefromkarl/stardrifter"
    assert run.story_issue_number == 41
    assert run.merged is True
    assert run.merge_commit_sha == "abc123"
    assert run.summary == "merged story/41 into main"


def test_run_story_until_settled_records_story_pull_request_link_from_integration_result():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-103",
                title="task 103",
                lane="Lane 06",
                wave="Wave0",
                status="done",
                repo="codefromkarl/stardrifter",
                source_issue_number=103,
                canonical_story_issue_number=41,
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "issue-103": [
                WorkTarget(
                    work_id="issue-103",
                    target_path="tests/unit/test_projection.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ],
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"Wave0"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_story_until_settled(
        story_issue_number=41,
        story_work_item_ids=["issue-103"],
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True, summary=f"executed {work_item.id}"
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
        committer=None,
        story_integrator=lambda **kwargs: StoryIntegrationResult(
            merged=True,
            merge_commit_sha="abc123",
            pull_number=203,
            pull_url="https://github.com/codefromkarl/stardrifter/pull/203",
            summary="merged story/41 into main",
        ),
    )

    assert result.story_complete is True
    assert repository.get_story_pull_request_link(
        repo="codefromkarl/stardrifter", story_issue_number=41
    ) == {
        "repo": "codefromkarl/stardrifter",
        "story_issue_number": 41,
        "pull_number": 203,
        "pull_url": "https://github.com/codefromkarl/stardrifter/pull/203",
    }


def test_run_story_until_settled_surfaces_missing_story_branch_clearly():
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-103",
                title="task 103",
                lane="Lane 06",
                wave="Wave0",
                status="done",
                repo="codefromkarl/stardrifter",
                source_issue_number=103,
                canonical_story_issue_number=41,
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "issue-103": [
                WorkTarget(
                    work_id="issue-103",
                    target_path="tests/unit/test_projection.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ],
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"Wave0"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_story_until_settled(
        story_issue_number=41,
        story_work_item_ids=["issue-103"],
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True, summary=f"executed {work_item.id}"
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
        committer=None,
        story_integrator=lambda **kwargs: StoryIntegrationResult(
            merged=False,
            blocked_reason="missing_story_branch",
            summary="story/41 branch does not exist",
        ),
    )

    assert result.story_complete is False
    assert result.merge_blocked_reason == "missing_story_branch"
    assert result.reason_code == "missing_story_branch"


def test_run_story_until_settled_rechecks_repository_before_returning_incomplete_when_no_claim_made(
    monkeypatch,
):
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-103",
                title="task 103",
                lane="Lane 06",
                wave="Wave0",
                status="ready",
                repo="codefromkarl/stardrifter",
                source_issue_number=103,
                canonical_story_issue_number=41,
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "issue-103": [
                WorkTarget(
                    work_id="issue-103",
                    target_path="tests/unit/test_projection.py",
                    target_type="file",
                    owner_lane="Lane 06",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ],
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"Wave0"},
        frozen_prefixes=("docs/authority/",),
    )

    def fake_run_worker_cycle(**kwargs):
        repository.update_work_status("issue-103", "done")
        return type("CycleResult", (), {"claimed_work_id": None})()

    monkeypatch.setattr(story_runner_module, "run_worker_cycle", fake_run_worker_cycle)

    result = run_story_until_settled(
        story_issue_number=41,
        story_work_item_ids=["issue-103"],
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True, summary=f"executed {work_item.id}"
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
        committer=None,
    )

    assert result.story_complete is True
    assert result.completed_work_item_ids == ["issue-103"]
    assert result.remaining_work_item_ids == []
    assert result.reason_code == "story_complete"


def test_run_story_until_settled_does_not_sync_story_when_incomplete():
    writes: list[dict[str, object]] = []
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-47",
                title="task 47",
                lane="Lane 02",
                wave="wave-2",
                status="pending",
                repo="codefromkarl/stardrifter",
                source_issue_number=47,
                canonical_story_issue_number=24,
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "issue-47": [
                WorkTarget(
                    work_id="issue-47",
                    target_path="src/stardrifter_engine/campaign/runtime.py",
                    target_type="file",
                    owner_lane="Lane 02",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ],
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-2"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_story_until_settled(
        story_issue_number=24,
        story_work_item_ids=["issue-47"],
        repository=repository,
        context=context,
        worker_name="worker-a",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=False, summary="compile failed"
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=False,
            output_digest="should not run",
        ),
        committer=None,
        story_github_writeback=lambda **kwargs: writes.append(kwargs),
    )

    assert result.story_complete is False
    assert writes == []


def test_run_story_until_settled_merges_story_branch_before_marking_story_complete():
    writes: list[dict[str, object]] = []
    merges: list[dict[str, object]] = []
    repository = InMemoryControlPlaneRepository(
        work_items=[
            WorkItem(
                id="issue-70",
                title="task 70",
                lane="Lane 01",
                wave="wave-1",
                status="pending",
                repo="codefromkarl/stardrifter",
                source_issue_number=70,
                canonical_story_issue_number=42,
            ),
            WorkItem(
                id="issue-71",
                title="task 71",
                lane="Lane 01",
                wave="wave-1",
                status="pending",
                repo="codefromkarl/stardrifter",
                source_issue_number=71,
                canonical_story_issue_number=42,
            ),
        ],
        dependencies=[
            WorkDependency(work_id="issue-71", depends_on_work_id="issue-70")
        ],
        targets_by_work_id={
            "issue-70": [
                WorkTarget(
                    work_id="issue-70",
                    target_path="docs/domains/01-campaign-topology/starsector-reference.md",
                    target_type="doc",
                    owner_lane="Lane 01",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ],
            "issue-71": [
                WorkTarget(
                    work_id="issue-71",
                    target_path="docs/domains/01-campaign-topology/README.md",
                    target_type="doc",
                    owner_lane="Lane 01",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ],
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-1"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_story_until_settled(
        story_issue_number=42,
        story_work_item_ids=["issue-70", "issue-71"],
        repository=repository,
        context=context,
        worker_name="story-runner",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True, summary=f"executed {work_item.id}"
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
        committer=None,
        story_github_writeback=lambda **kwargs: writes.append(kwargs),
        story_integrator=lambda **kwargs: merges.append(kwargs),
    )

    assert result.story_complete is True
    assert merges == [
        {
            "story_issue_number": 42,
            "story_work_items": [
                repository.get_work_item("issue-70"),
                repository.get_work_item("issue-71"),
            ],
        }
    ]
    assert writes == [
        {
            "repo": "codefromkarl/stardrifter",
            "issue_number": 42,
            "status": "done",
            "decision_required": False,
        }
    ]


def test_run_story_until_settled_marks_program_story_done_with_propagation():
    writes: list[tuple[str, int, str]] = []

    class FakeRepository(InMemoryControlPlaneRepository):
        def set_program_story_execution_status_with_propagation(
            self, *, repo: str, issue_number: int, execution_status: str
        ) -> None:
            writes.append((repo, issue_number, execution_status))

    repository = FakeRepository(
        work_items=[
            WorkItem(
                id="issue-78",
                title="task 78",
                lane="Lane 01",
                wave="unassigned",
                status="pending",
                repo="codefromkarl/stardrifter",
                source_issue_number=78,
                canonical_story_issue_number=22,
            ),
        ],
        dependencies=[],
        targets_by_work_id={
            "issue-78": [
                WorkTarget(
                    work_id="issue-78",
                    target_path="tests/unit/test_campaign_topology_schema_closure.py",
                    target_type="file",
                    owner_lane="Lane 01",
                    is_frozen=False,
                    requires_human_approval=False,
                )
            ]
        },
    )
    context = ExecutionGuardrailContext(
        allowed_waves={"unassigned"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_story_until_settled(
        story_issue_number=22,
        story_work_item_ids=["issue-78"],
        repository=repository,
        context=context,
        worker_name="story-runner",
        executor=lambda work_item, workspace_path=None: ExecutionResult(
            success=True, summary="already satisfied"
        ),
        verifier=lambda work_item, workspace_path=None: VerificationEvidence(
            work_id=work_item.id,
            check_type="pytest",
            command="python3 -m pytest -q",
            passed=True,
            output_digest="ok",
        ),
        committer=None,
    )

    assert result.story_complete is True
    assert writes == [("codefromkarl/stardrifter", 22, "done")]
