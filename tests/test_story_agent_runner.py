from taskplane.models import (
    ExecutionGuardrailContext,
    StoryRunResult,
    VerificationEvidence,
    WorkItem,
)
from taskplane.story_agent_runner import run_story_agent
from taskplane.worker import ExecutionResult


def test_run_story_agent_loads_story_scope_and_delegates_to_story_runner():
    repository = object()
    executor = lambda work_item: ExecutionResult(success=True, summary=work_item.id)
    verifier = lambda work_item: VerificationEvidence(
        work_id=work_item.id,
        check_type="pytest",
        command="python3 -m pytest -q",
        passed=True,
        output_digest="ok",
    )
    committer = object()
    calls: list[dict[str, object]] = []
    context = ExecutionGuardrailContext(
        allowed_waves={"wave-2"},
        frozen_prefixes=("docs/authority/",),
    )

    result = run_story_agent(
        story_issue_number=29,
        repository=repository,
        context=context,
        worker_name="story-agent",
        executor=executor,
        verifier=verifier,
        committer=committer,
        story_loader=lambda repository, story_issue_number: ["issue-56", "issue-57"],
        story_runner=lambda **kwargs: (
            calls.append(kwargs)
            or StoryRunResult(
                story_issue_number=kwargs["story_issue_number"],
                completed_work_item_ids=["issue-56", "issue-57"],
                blocked_work_item_ids=[],
                remaining_work_item_ids=[],
                story_complete=True,
            )
        ),
    )

    assert result.story_complete is True
    assert calls == [
        {
            "story_issue_number": 29,
            "story_work_item_ids": ["issue-56", "issue-57"],
            "repository": repository,
            "context": context,
            "worker_name": "story-agent",
            "executor": executor,
            "verifier": verifier,
            "committer": committer,
            "story_github_writeback": None,
            "story_integrator": None,
            "workspace_manager": None,
            "max_cycles": 100,
            "dsn": None,
        }
    ]
