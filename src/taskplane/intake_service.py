from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
import re
from typing import Any, Protocol
from uuid import uuid4

from .model_gateway.factory import build_model_client
from .model_gateway.settings import load_executor_model_settings_from_env
from .model_gateway.settings import load_provider_settings_from_env
from .models import NaturalLanguageIntent
from .repository import ControlPlaneRepository


class IntakeAnalyzer(Protocol):
    def __call__(
        self, *, repo: str, conversation: list[dict[str, str]]
    ) -> dict[str, Any]: ...


class NaturalLanguageIntakeService:
    def __init__(
        self,
        *,
        repository: ControlPlaneRepository,
        analyzer: IntakeAnalyzer,
    ) -> None:
        self.repository = repository
        self.analyzer = analyzer

    def submit_intent(self, *, repo: str, prompt: str) -> NaturalLanguageIntent:
        now = datetime.now(UTC)
        intent = NaturalLanguageIntent(
            id=str(uuid4()),
            repo=repo,
            prompt=prompt,
            status="awaiting_clarification",
            conversation=(({"role": "user", "content": prompt}),),
            created_at=now,
            updated_at=now,
        )
        analyzed = self._analyze(intent)
        self.repository.record_natural_language_intent(analyzed)
        return analyzed

    def answer_intent(self, *, intent_id: str, answer: str) -> NaturalLanguageIntent:
        intent = self._require_intent(intent_id)
        updated = replace(
            intent,
            conversation=intent.conversation + (({"role": "user", "content": answer}),),
            updated_at=datetime.now(UTC),
        )
        analyzed = self._analyze(updated)
        self.repository.update_natural_language_intent(analyzed)
        return analyzed

    def approve_intent(self, *, intent_id: str, approver: str) -> NaturalLanguageIntent:
        intent = self._require_intent(intent_id)
        if intent.status != "awaiting_review":
            raise ValueError(f"intent is not awaiting review: {intent.status}")
        reviewed_at = datetime.now(UTC)
        epic_issue_number = self.repository.promote_natural_language_proposal(
            intent_id=intent.id,
            proposal=intent.proposal_json,
            approver=approver,
            promotion_mode=str(intent.proposal_json.get("promotion_mode") or "local"),
        )
        promoted = replace(
            intent,
            status="promoted",
            promoted_epic_issue_number=epic_issue_number,
            approved_by=approver,
            approved_at=reviewed_at,
            reviewed_at=reviewed_at,
            reviewed_by=approver,
            review_action="approve",
            review_feedback=None,
            updated_at=reviewed_at,
        )
        self.repository.update_natural_language_intent(promoted)
        return promoted

    def reject_intent(
        self, *, intent_id: str, reviewer: str, reason: str
    ) -> NaturalLanguageIntent:
        reason_text = reason.strip()
        if not reason_text:
            raise ValueError("reject reason is required")
        intent = self._require_intent(intent_id)
        if intent.status != "awaiting_review":
            raise ValueError(f"intent is not awaiting review: {intent.status}")
        reviewed_at = datetime.now(UTC)
        rejected = replace(
            intent,
            status="rejected",
            reviewed_at=reviewed_at,
            reviewed_by=reviewer,
            review_action="reject",
            review_feedback=reason_text,
            updated_at=reviewed_at,
        )
        self.repository.update_natural_language_intent(rejected)
        return rejected

    def revise_intent(
        self, *, intent_id: str, reviewer: str, feedback: str
    ) -> NaturalLanguageIntent:
        feedback_text = feedback.strip()
        if not feedback_text:
            raise ValueError("revise feedback is required")
        intent = self._require_intent(intent_id)
        if intent.status != "awaiting_review":
            raise ValueError(f"intent is not awaiting review: {intent.status}")
        revised_input = replace(
            intent,
            conversation=intent.conversation
            + (({"role": "reviewer", "content": feedback_text}),),
            reviewed_at=datetime.now(UTC),
            reviewed_by=reviewer,
            review_action="revise",
            review_feedback=feedback_text,
            updated_at=datetime.now(UTC),
        )
        analyzed = self._analyze(revised_input)
        self.repository.update_natural_language_intent(analyzed)
        return analyzed

    def _require_intent(self, intent_id: str) -> NaturalLanguageIntent:
        intent = self.repository.get_natural_language_intent(intent_id)
        if intent is None:
            raise ValueError(f"unknown intent: {intent_id}")
        return intent

    def _analyze(self, intent: NaturalLanguageIntent) -> NaturalLanguageIntent:
        payload = self.analyzer(
            repo=intent.repo,
            conversation=[dict(message) for message in intent.conversation],
        )
        outcome = str(payload.get("outcome") or "needs_clarification")
        summary = str(payload.get("summary") or "").strip()
        questions = tuple(
            str(item).strip()
            for item in payload.get("questions") or []
            if str(item).strip()
        )
        proposal = {
            "epic": payload.get("epic") or {},
            "stories": payload.get("stories") or [],
        }
        if outcome == "ready_for_review":
            status = "awaiting_review"
        elif outcome == "rejected":
            status = "rejected"
        else:
            status = "awaiting_clarification"
        return replace(
            intent,
            status=status,
            summary=summary,
            clarification_questions=questions,
            proposal_json=proposal,
            analysis_model=str(
                payload.get("analysis_model") or intent.analysis_model or ""
            ),
            updated_at=datetime.now(UTC),
        )


class LLMIntakeAnalyzer:
    def __init__(self) -> None:
        self.settings = load_executor_model_settings_from_env()
        self.client = build_model_client(self.settings.provider)

    def __call__(
        self, *, repo: str, conversation: list[dict[str, str]]
    ) -> dict[str, Any]:
        prompt = _build_intake_prompt(repo=repo, conversation=conversation)
        raw = self.client.complete_text(
            model=self.settings.executor_model,
            messages=[
                {"role": "system", "content": _build_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            timeout_seconds=self.settings.timeout_seconds,
            max_output_tokens=self.settings.executor_max_output_tokens,
        )
        payload = _extract_json_payload(raw)
        if payload is None:
            raise ValueError("intake analyzer did not return JSON payload")
        return payload


def build_default_analyzer(
    repository: ControlPlaneRepository | None = None,
) -> IntakeAnalyzer:
    provider_settings = load_provider_settings_from_env()
    model_settings = load_executor_model_settings_from_env()
    provider = model_settings.provider.lower()
    if provider == "anthropic":
        if not provider_settings.anthropic_api_key:
            return HeuristicIntakeAnalyzer()
    elif not provider_settings.openai_api_key:
        return HeuristicIntakeAnalyzer()
    return LLMIntakeAnalyzer()


class HeuristicIntakeAnalyzer:
    def __call__(
        self, *, repo: str, conversation: list[dict[str, str]]
    ) -> dict[str, Any]:
        user_messages = [
            str(message.get("content") or "").strip()
            for message in conversation
            if str(message.get("role") or "") == "user"
            and str(message.get("content") or "").strip()
        ]
        latest = user_messages[-1] if user_messages else ""
        combined = "\n".join(user_messages).strip()

        if len(user_messages) == 1 and _needs_clarification(latest):
            return {
                "outcome": "needs_clarification",
                "summary": "当前需求还不够稳定，先补齐关键约束后再进入任务池。",
                "questions": [
                    "目标范围是什么？请明确首个可交付版本包含哪些能力。",
                    "是否有技术边界、目标仓库路径或验收方式需要提前锁定？",
                ],
                "analysis_model": "heuristic-fallback",
            }

        return {
            "outcome": "ready_for_review",
            "summary": "当前环境未配置外部模型密钥，已使用本地 fallback planner 生成受控拆解。",
            "epic": {
                "title": _derive_epic_title(combined),
                "lane": "Lane 01",
                "notes": f"heuristic-fallback for {repo}",
            },
            "stories": _derive_story_payloads(combined),
            "analysis_model": "heuristic-fallback",
        }


def _build_system_prompt() -> str:
    return (
        "You are the TaskPlane intake planner. "
        "First brainstorm the request like a pragmatic technical lead: identify scope, constraints, risks, missing inputs, "
        "and a safe decomposition strategy. "
        "If key information is missing, ask clarification questions instead of guessing. "
        "If the request is sufficiently clear, produce a bounded epic/stories/tasks proposal that can be approved into the control plane. "
        "Keep stories cohesive, express dependencies explicitly, keep tasks executable, and prefer verifiable outputs. "
        "Return JSON only."
    )


def _build_intake_prompt(*, repo: str, conversation: list[dict[str, str]]) -> str:
    return (
        "Repository: "
        f"{repo}\n"
        "Conversation:\n"
        f"{json.dumps(conversation, ensure_ascii=False, indent=2)}\n\n"
        "Before producing the final structured output, mentally brainstorm:\n"
        "- what the user is really asking for\n"
        "- what is in scope vs out of scope\n"
        "- what must be clarified before safe execution\n"
        "- what epic/story/task breakdown best fits controlled execution\n\n"
        "Return JSON with shape:\n"
        "{\n"
        '  "outcome": "needs_clarification" | "ready_for_review" | "rejected",\n'
        '  "summary": "...",\n'
        '  "questions": ["..."],\n'
        '  "epic": {"title": "...", "lane": "Lane 01", "notes": "..."},\n'
        '  "stories": [\n'
        "    {\n"
        '      "story_key": "S1",\n'
        '      "title": "...",\n'
        '      "lane": "Lane 01",\n'
        '      "complexity": "low|medium|high",\n'
        '      "depends_on_story_keys": ["S0"],\n'
        '      "tasks": [\n'
        "        {\n"
        '          "task_key": "T1",\n'
        '          "title": "...",\n'
        '          "lane": "Lane 01",\n'
        '          "wave": "wave-1",\n'
        '          "task_type": "core_path",\n'
        '          "blocking_mode": "hard",\n'
        '          "planned_paths": ["src/..."],\n'
        '          "dod": ["..."],\n'
        '          "verification": ["pytest ..."]\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "If clarification is still required, keep epic/stories empty."
    )


def _extract_json_payload(raw_text: str) -> dict[str, Any] | None:
    text = raw_text.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def _needs_clarification(prompt: str) -> bool:
    compact = re.sub(r"\s+", "", prompt)
    if len(compact) < 14:
        return True
    vague_keywords = ("优化一下", "搞一下", "看看", "处理一下", "做个")
    return any(keyword in compact for keyword in vague_keywords)


def _derive_epic_title(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return "Natural language request"
    if len(clean) <= 36:
        return clean
    return clean[:36].rstrip("，,。.;；:：") + "…"


def _derive_story_payloads(text: str) -> list[dict[str, Any]]:
    normalized = text.lower()
    stories: list[dict[str, Any]] = []

    if any(
        keyword in normalized
        for keyword in (
            "api",
            "backend",
            "后端",
            "接口",
            "auth",
            "认证",
            "token",
            "jwt",
        )
    ):
        stories.append(
            {
                "story_key": "S1",
                "title": "Backend capability slice",
                "lane": "Lane 01",
                "complexity": "medium",
                "tasks": [
                    {
                        "task_key": "T1",
                        "title": "Implement backend flow for requested capability",
                        "lane": "Lane 01",
                        "wave": "wave-1",
                        "task_type": "core_path",
                        "blocking_mode": "hard",
                        "planned_paths": ["src/"],
                        "dod": ["核心后端流程可执行"],
                        "verification": ["pytest -q"],
                    }
                ],
            }
        )

    if any(
        keyword in normalized
        for keyword in ("frontend", "ui", "页面", "表单", "web", "前端")
    ):
        stories.append(
            {
                "story_key": f"S{len(stories) + 1}",
                "title": "Frontend interaction slice",
                "lane": "Lane 02",
                "complexity": "medium",
                "depends_on_story_keys": ["S1"] if stories else [],
                "tasks": [
                    {
                        "task_key": "T1",
                        "title": "Implement frontend interaction for requested capability",
                        "lane": "Lane 02",
                        "wave": "wave-2",
                        "task_type": "core_path",
                        "blocking_mode": "hard",
                        "planned_paths": ["frontend/src/"],
                        "dod": ["前端交互可使用"],
                        "verification": ["npm run build"],
                    }
                ],
            }
        )

    if not stories:
        stories.append(
            {
                "story_key": "S1",
                "title": "Core implementation slice",
                "lane": "Lane 01",
                "complexity": "medium",
                "tasks": [
                    {
                        "task_key": "T1",
                        "title": "Implement requested capability",
                        "lane": "Lane 01",
                        "wave": "wave-1",
                        "task_type": "core_path",
                        "blocking_mode": "hard",
                        "planned_paths": ["src/"],
                        "dod": ["功能实现完成"],
                        "verification": ["pytest -q"],
                    }
                ],
            }
        )

    existing_story_keys = [str(story["story_key"]) for story in stories]
    stories.append(
        {
            "story_key": f"S{len(stories) + 1}",
            "title": "Verification and stabilization",
            "lane": "Lane 03",
            "complexity": "low",
            "depends_on_story_keys": existing_story_keys,
            "tasks": [
                {
                    "task_key": "T1",
                    "title": "Add verification coverage and confirm acceptance criteria",
                    "lane": "Lane 03",
                    "wave": f"wave-{len(stories) + 1}",
                    "task_type": "governance",
                    "blocking_mode": "soft",
                    "planned_paths": ["tests/"],
                    "dod": ["具备最小验证闭环"],
                    "verification": ["python -m pytest -q"],
                }
            ],
        }
    )
    return stories
