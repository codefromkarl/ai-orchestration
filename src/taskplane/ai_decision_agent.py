"""
AI Decision Agent Module

AI 自主决策代理模块。
当执行器返回 needs_decision 时，先让 AI 决策 agent 评估：
- 如果是 AI 可以自己解决的 → 返回 auto_resolvable，触发 retry
- 如果确实需要人工 → 返回 requires_human，进入 operator 队列
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

import psycopg
from psycopg.rows import dict_row

from .models import AIDecision, WorkItem


class DecisionOutcome:
    """决策结果常量"""

    AUTO_RESOLVABLE = "auto_resolvable"
    REQUIRES_HUMAN = "requires_human"
    RETRY_WITH_CONTEXT = "retry_with_context"
    ESCALATE_TO_OPERATOR = "escalate_to_operator"


@dataclass
class DecisionResult:
    """AI 决策结果"""

    outcome: Literal[
        "auto_resolvable",
        "requires_human",
        "retry_with_context",
        "escalate_to_operator",
    ]
    reasoning: str
    suggested_action: str
    can_retry_with_prompt: bool = False
    retry_prompt_template: str | None = None


class AIDecisionAgent:
    """
    AI 自主决策代理

    评估 needs_decision 情况，决定是否可以通过 AI 自动恢复
    """

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn

    def evaluate_needs_decision(
        self,
        work_item: WorkItem,
        execution_result: dict,
        context_summary: str | None = None,
        conversation_history: list | None = None,
    ) -> DecisionResult:
        """
        评估 needs_decision 情况

        决策优先级：
        1. 安全/权限相关 -> 始终需要人工 (最高优先级)
        2. attempt_count >= 5 -> 升级到 operator
        3. attempt_count >= 3 -> 升级到 operator
        4. 可自动恢复模式 -> 自动重试
        5. 有上下文 -> 使用上下文重试
        6. 其他 -> 需要人工
        """
        reason_code = execution_result.get("reason_code", "")
        summary = execution_result.get("summary", "")

        # 预定义的可自动恢复场景
        auto_resolvable_patterns = [
            "awaiting_user_input",
            "ask_next_step",
            "awaiting_next_step",
            "paused_for_input",
            "unclear_requirements",
            "ambiguous_task",
        ]

        # 安全/权限相关，始终需要人工 (最高优先级)
        requires_human_patterns = [
            "permission_required",
            "security_concern",
            "data_loss_risk",
            "external_dependency",
            "api_key_required",
            "credential_required",
        ]

        # 检查是否需要人工 (最高优先级，涉及安全/权限)
        for pattern in requires_human_patterns:
            if pattern in reason_code.lower() or pattern in summary.lower():
                return DecisionResult(
                    outcome=DecisionOutcome.REQUIRES_HUMAN,
                    reasoning=f"检测到需要人工介入的模式：{pattern} (安全/权限相关，始终需要人工)",
                    suggested_action="通知人类操作员进行决策",
                )

        # 检查 attempt_count >= 5 (最高重试次数)
        if work_item.attempt_count >= 5:
            return DecisionResult(
                outcome=DecisionOutcome.ESCALATE_TO_OPERATOR,
                reasoning=f"已尝试 {work_item.attempt_count} 次，超过最大自动重试次数，应升级为 operator 处理",
                suggested_action="升级到 operator 队列",
            )

        # 检查 attempt_count >= 3 (升级阈值)
        if work_item.attempt_count >= 3:
            return DecisionResult(
                outcome=DecisionOutcome.ESCALATE_TO_OPERATOR,
                reasoning=f"已尝试 {work_item.attempt_count} 次，应升级为 operator 处理",
                suggested_action="升级到 operator 队列",
            )

        # 检查是否可自动恢复
        for pattern in auto_resolvable_patterns:
            if pattern in reason_code.lower() or pattern in summary.lower():
                return DecisionResult(
                    outcome=DecisionOutcome.AUTO_RESOLVABLE,
                    reasoning=f"检测到可自动恢复的模式：{pattern}",
                    suggested_action="使用默认选项或推断最可能的意图后重试",
                    can_retry_with_prompt=True,
                    retry_prompt_template=self._build_retry_prompt(
                        pattern, work_item, context_summary
                    ),
                )

        # 默认：尝试使用上下文 resume
        if context_summary:
            return DecisionResult(
                outcome=DecisionOutcome.RETRY_WITH_CONTEXT,
                reasoning="有可用上下文，尝试 resume 后重试",
                suggested_action="使用对话摘要 resume 后重试",
                can_retry_with_prompt=True,
            )

        # 最终默认：需要人工
        return DecisionResult(
            outcome=DecisionOutcome.REQUIRES_HUMAN,
            reasoning="无法确定自动恢复策略，需要人工决策",
            suggested_action="通知人类操作员",
        )

    def _build_retry_prompt(
        self,
        pattern: str,
        work_item: WorkItem,
        context_summary: str | None,
    ) -> str:
        """构建重试 prompt"""

        prompts = {
            "awaiting_user_input": (
                "用户暂时无法提供输入。请根据任务标题和上下文推断最合理的实现方式，"
                "使用保守但有效的默认选项完成实现。如果无法推断，选择最简单的可行方案。"
            ),
            "ask_next_step": (
                "系统询问下一步操作。请分析任务目标，自主选择下一个最必要的步骤并执行。"
                "优先完成核心功能，然后再处理边界情况。"
            ),
            "unclear_requirements": (
                "需求不够清晰。请根据任务标题和已有的描述，推断最小必要实现范围，"
                "并专注于完成这个最小范围。"
            ),
            "ambiguous_task": (
                "任务存在歧义。请选择最常见/标准的实现方式，或者实现一个最小可行版本。"
            ),
        }

        base_prompt = prompts.get(
            pattern,
            "请分析当前情况，自主选择最佳方案继续执行。",
        )

        if context_summary:
            base_prompt += f"\n\n当前上下文摘要：\n{context_summary}"

        return base_prompt

    def record_decision(
        self,
        conn: psycopg.Connection,
        work_id: str,
        decision: DecisionResult,
        original_reason_code: str | None = None,
    ) -> int:
        """
        记录决策到数据库

        Args:
            conn: 数据库连接
            work_id: 工作项 ID
            decision: 决策结果
            original_reason_code: 原始原因码

        Returns:
            决策记录 ID
        """
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ai_decision_log (
                    work_id,
                    decision_type,
                    original_reason_code,
                    ai_reasoning,
                    context_summary,
                    outcome
                ) VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    work_id,
                    decision.outcome,
                    original_reason_code,
                    decision.reasoning,
                    decision.suggested_action,
                    None,
                ),
            )
            row = cur.fetchone()
            return row["id"] if row else -1


# =============================================================================
# 与 worker 集成
# =============================================================================


def handle_needs_decision(
    *,
    work_item: WorkItem,
    execution_result: dict,
    context_summary: str | None,
    notification_webhook,
    conn: psycopg.Connection,
) -> tuple[bool, str | None]:
    """
    处理 needs_decision 情况

    Args:
        work_item: 工作项
        execution_result: 执行结果
        context_summary: 上下文摘要
        notification_webhook: 通知 webhook
        conn: 数据库连接

    Returns:
        (是否需要人工，backoff 时间（如有）)
    """
    agent = AIDecisionAgent()
    decision = agent.evaluate_needs_decision(
        work_item=work_item,
        execution_result=execution_result,
        context_summary=context_summary,
    )

    # 记录决策
    agent.record_decision(
        conn=conn,
        work_id=work_item.id,
        decision=decision,
        original_reason_code=execution_result.get("reason_code"),
    )

    if decision.outcome == DecisionOutcome.AUTO_RESOLVABLE:
        # 可自动恢复 - 返回 retry 提示
        return False, decision.retry_prompt_template

    elif decision.outcome == DecisionOutcome.RETRY_WITH_CONTEXT:
        # 使用上下文重试
        return False, None

    elif decision.outcome == DecisionOutcome.ESCALATE_TO_OPERATOR:
        # 升级到 operator
        return True, None

    else:
        # 需要人工 - 发送通知
        reason_code = execution_result.get("reason_code", "unknown")
        summary = execution_result.get("summary", "需要决策")

        notification_webhook.notify_human_decision_required(
            work_id=work_item.id,
            reason=decision.reasoning,
            context_summary=context_summary or summary,
            story_issue_number=work_item.canonical_story_issue_number,
        )

        return True, None


# =============================================================================
# 便捷函数
# =============================================================================


def is_auto_resolvable(
    reason_code: str,
    summary: str,
) -> bool:
    """
    判断是否是可自动恢复的失败类型

    Args:
        reason_code: 失败原因码
        summary: 失败摘要

    Returns:
        是否可自动恢复
    """
    auto_resolvable_patterns = [
        "awaiting_user_input",
        "ask_next_step",
        "awaiting_next_step",
        "paused_for_input",
        "unclear_requirements",
        "ambiguous_task",
        "context_gathering",
        "research_in_progress",
    ]

    combined = f"{reason_code} {summary}".lower()
    return any(pattern in combined for pattern in auto_resolvable_patterns)
