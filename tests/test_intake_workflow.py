from __future__ import annotations

import json

from taskplane.repository import InMemoryControlPlaneRepository
from taskplane.models import ExecutionGuardrailContext
from taskplane.queue import evaluate_work_queue


def _build_repository() -> InMemoryControlPlaneRepository:
    return InMemoryControlPlaneRepository(
        work_items=[],
        dependencies=[],
        targets_by_work_id={},
    )


def test_intake_service_clarifies_then_promotes_into_program_pool():
    from taskplane.intake_service import NaturalLanguageIntakeService

    repository = _build_repository()

    def fake_analyzer(*, repo: str, conversation: list[dict[str, str]]) -> dict[str, object]:
        user_messages = [message for message in conversation if message["role"] == "user"]
        if len(user_messages) == 1:
            return {
                "outcome": "needs_clarification",
                "summary": "需要先确认认证方案。",
                "questions": ["认证方式使用 JWT 还是 Session？"],
            }
        return {
            "outcome": "ready_for_review",
            "summary": "认证能力可拆为后端与前端两个 story，先做后端再做前端。",
            "epic": {
                "title": "Authentication",
                "lane": "Lane 01",
                "notes": "Natural-language intake generated epic",
            },
            "stories": [
                {
                    "story_key": "S1",
                    "title": "Backend authentication endpoints",
                    "lane": "Lane 01",
                    "complexity": "high",
                    "tasks": [
                        {
                            "task_key": "T1",
                            "title": "Implement login endpoint",
                            "lane": "Lane 01",
                            "wave": "wave-1",
                            "task_type": "core_path",
                            "blocking_mode": "hard",
                            "planned_paths": ["src/taskplane/auth_backend.py"],
                            "dod": ["login endpoint works"],
                            "verification": ["pytest tests/test_auth_backend.py"],
                        }
                    ],
                },
                {
                    "story_key": "S2",
                    "title": "Frontend sign-in experience",
                    "lane": "Lane 02",
                    "complexity": "medium",
                    "depends_on_story_keys": ["S1"],
                    "tasks": [
                        {
                            "task_key": "T2",
                            "title": "Build sign-in form",
                            "lane": "Lane 02",
                            "wave": "wave-2",
                            "task_type": "core_path",
                            "blocking_mode": "hard",
                            "planned_paths": ["frontend/src/components/SignInForm.tsx"],
                            "dod": ["sign-in form renders"],
                            "verification": ["npm test -- SignInForm"],
                        }
                    ],
                },
            ],
        }

    service = NaturalLanguageIntakeService(
        repository=repository,
        analyzer=fake_analyzer,
    )

    first = service.submit_intent(
        repo="codefromkarl/stardrifter",
        prompt="实现完整的用户认证能力，包含前后端。",
    )

    assert first.status == "awaiting_clarification"
    assert first.clarification_questions == ("认证方式使用 JWT 还是 Session？",)

    second = service.answer_intent(
        intent_id=first.id,
        answer="使用 JWT。",
    )

    assert second.status == "awaiting_review"
    assert second.proposal_json["epic"]["title"] == "Authentication"
    assert len(second.proposal_json["stories"]) == 2

    promoted = service.approve_intent(intent_id=second.id, approver="alice")

    assert promoted.status == "promoted"
    assert promoted.promoted_epic_issue_number is not None

    promoted_stories = repository.list_program_stories_for_epic(
        repo="codefromkarl/stardrifter",
        epic_issue_number=promoted.promoted_epic_issue_number,
    )
    assert [story.title for story in promoted_stories] == [
        "Backend authentication endpoints",
        "Frontend sign-in experience",
    ]
    assert all(story.program_status == "approved" for story in promoted_stories)
    assert all(story.execution_status == "active" for story in promoted_stories)

    work_items = {item.title: item for item in repository.list_work_items()}
    assert set(work_items) == {
        "Implement login endpoint",
        "Build sign-in form",
    }
    assert work_items["Implement login endpoint"].status == "ready"
    assert work_items["Build sign-in form"].status == "pending"

    queue_evaluation = evaluate_work_queue(
        work_items=repository.list_work_items(),
        dependencies=repository.list_dependencies(),
        targets_by_work_id=repository.list_targets_by_work_id(),
        context=ExecutionGuardrailContext(
            allowed_waves={"wave-1", "wave-2"},
            frozen_prefixes=("docs/authority/",),
        ),
        active_claims=repository.list_active_work_claims(),
    )
    claimed = repository.claim_next_executable_work_item(
        worker_name="agent-a",
        queue_evaluation=queue_evaluation,
        candidate_work_items=repository.list_work_items(),
        workspace_path_by_work_id={
            "intent-" + second.id + "-t1-1": "/tmp/worktrees/intent-1"
        },
        branch_name_by_work_id={
            "intent-" + second.id + "-t1-1": "task/intent-1"
        },
    )

    assert claimed is not None
    assert claimed.title == "Implement login endpoint"



def test_intake_cli_submit_and_approve_emit_json(monkeypatch, capsys):
    from taskplane.intake_cli import main

    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    repository = _build_repository()

    def fake_analyzer(*, repo: str, conversation: list[dict[str, str]]) -> dict[str, object]:
        return {
            "outcome": "ready_for_review",
            "summary": "可以直接进入审核。",
            "epic": {
                "title": "Console intake epic",
                "lane": "Lane 03",
                "notes": "Generated from CLI test",
            },
            "stories": [
                {
                    "story_key": "S1",
                    "title": "Console story",
                    "lane": "Lane 03",
                    "complexity": "medium",
                    "tasks": [
                        {
                            "task_key": "T1",
                            "title": "Console task",
                            "lane": "Lane 03",
                            "wave": "wave-1",
                            "task_type": "core_path",
                            "blocking_mode": "hard",
                            "planned_paths": ["src/taskplane/console_task.py"],
                            "dod": ["task created"],
                            "verification": ["pytest tests/test_console_task.py"],
                        }
                    ],
                }
            ],
        }

    exit_code = main(
        [
            "submit",
            "--repo",
            "codefromkarl/stardrifter",
            "--prompt",
            "实现控制台 intake 工作流",
        ],
        repository_builder=lambda *, dsn: repository,
        analyzer_builder=lambda repository: fake_analyzer,
    )

    assert exit_code == 0
    submit_payload = json.loads(capsys.readouterr().out)
    assert submit_payload["status"] == "awaiting_review"
    assert submit_payload["proposal"]["epic"]["title"] == "Console intake epic"

    exit_code = main(
        [
            "approve",
            "--intent-id",
            submit_payload["intent_id"],
            "--approver",
            "operator",
        ],
        repository_builder=lambda *, dsn: repository,
        analyzer_builder=lambda repository: fake_analyzer,
    )

    assert exit_code == 0
    approve_payload = json.loads(capsys.readouterr().out)
    assert approve_payload["status"] == "promoted"
    assert approve_payload["promoted_epic_issue_number"] is not None


def test_intake_service_reject_records_reviewer_and_reason():
    from taskplane.intake_service import NaturalLanguageIntakeService

    repository = _build_repository()

    def fake_analyzer(*, repo: str, conversation: list[dict[str, str]]) -> dict[str, object]:
        del repo, conversation
        return {
            "outcome": "ready_for_review",
            "summary": "需求已经拆解完成，等待审核。",
            "epic": {
                "title": "Authentication",
                "lane": "Lane 01",
            },
            "stories": [],
        }

    service = NaturalLanguageIntakeService(
        repository=repository,
        analyzer=fake_analyzer,
    )

    intent = service.submit_intent(
        repo="codefromkarl/stardrifter",
        prompt="实现认证系统。",
    )

    rejected = service.reject_intent(
        intent_id=intent.id,
        reviewer="alice",
        reason="需求范围过大，需要先拆清首个可交付版本。",
    )

    assert rejected.status == "rejected"
    assert rejected.reviewed_by == "alice"
    assert rejected.review_action == "reject"
    assert (
        rejected.review_feedback
        == "需求范围过大，需要先拆清首个可交付版本。"
    )
    assert rejected.reviewed_at is not None


def test_intake_service_revise_records_feedback_and_reanalyzes():
    from taskplane.intake_service import NaturalLanguageIntakeService

    repository = _build_repository()

    def fake_analyzer(*, repo: str, conversation: list[dict[str, str]]) -> dict[str, object]:
        del repo
        reviewer_messages = [
            message.get("content", "")
            for message in conversation
            if message.get("role") == "reviewer"
        ]
        if reviewer_messages:
            return {
                "outcome": "needs_clarification",
                "summary": f"已收到审核反馈：{reviewer_messages[-1]}",
                "questions": ["请明确首个版本只覆盖后端还是前端。"],
            }
        return {
            "outcome": "ready_for_review",
            "summary": "需求已经拆解完成，等待审核。",
            "epic": {
                "title": "Authentication",
                "lane": "Lane 01",
            },
            "stories": [],
        }

    service = NaturalLanguageIntakeService(
        repository=repository,
        analyzer=fake_analyzer,
    )

    intent = service.submit_intent(
        repo="codefromkarl/stardrifter",
        prompt="实现认证系统。",
    )

    revised = service.revise_intent(
        intent_id=intent.id,
        reviewer="alice",
        feedback="请先限定 MVP，只做后端登录与刷新 token。",
    )

    assert revised.status == "awaiting_clarification"
    assert (
        revised.summary
        == "已收到审核反馈：请先限定 MVP，只做后端登录与刷新 token。"
    )
    assert revised.reviewed_by == "alice"
    assert revised.review_action == "revise"
    assert revised.review_feedback == "请先限定 MVP，只做后端登录与刷新 token。"
    assert revised.reviewed_at is not None
    assert revised.conversation[-1] == {
        "role": "reviewer",
        "content": "请先限定 MVP，只做后端登录与刷新 token。",
    }


def test_build_default_analyzer_falls_back_without_provider_credentials(monkeypatch):
    from taskplane.intake_service import HeuristicIntakeAnalyzer, build_default_analyzer

    monkeypatch.delenv("TASKPLANE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TASKPLANE_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("TASKPLANE_LLM_PROVIDER", "openai")

    analyzer = build_default_analyzer()

    assert isinstance(analyzer, HeuristicIntakeAnalyzer)


def test_heuristic_intake_analyzer_returns_reviewable_proposal():
    from taskplane.intake_service import HeuristicIntakeAnalyzer

    analyzer = HeuristicIntakeAnalyzer()

    payload = analyzer(
        repo="demo/taskplane",
        conversation=[
            {
                "role": "user",
                "content": "实现认证系统，包含 JWT 登录、刷新 token、前端登录页和权限守卫。",
            }
        ],
    )

    assert payload["outcome"] == "ready_for_review"
    assert payload["analysis_model"] == "heuristic-fallback"
    assert payload["epic"]["title"]
    assert len(payload["stories"]) >= 2
