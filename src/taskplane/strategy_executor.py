from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .models import ExecutionSession


@dataclass(frozen=True)
class StrategyAdjustment:
    prompt_suffix: str
    timeout_override: int | None = None
    bounded_mode_override: bool | None = None


STRATEGY_PROMPTS: dict[str, str] = {
    "retry_fresh": "",
    "retry_with_narrowed_scope": (
        "\n重要：上一轮执行未能完成。请缩小执行范围：\n"
        "- 只关注最关键的文件\n"
        "- 不要做大规模探索\n"
        "- 直接进入最小必要修改\n"
    ),
    "diagnose_then_retry": (
        "\n重要：上一轮验证失败。在继续之前：\n"
        "- 先运行诊断命令确认失败原因\n"
        "- 检查测试输出和错误日志\n"
        "- 只修复已确认的问题\n"
    ),
    "retry_after_clean": (
        "\n重要：工作区可能被污染。请：\n"
        "- 检查当前文件状态\n"
        "- 如果发现意外修改，先清理\n"
        "- 然后继续执行任务\n"
    ),
}


def resolve_strategy(
    *,
    session: ExecutionSession,
    strategy_name: str | None = None,
) -> StrategyAdjustment:
    name = strategy_name or ""
    prompt_suffix = STRATEGY_PROMPTS.get(name, "")

    if name == "retry_with_narrowed_scope":
        return StrategyAdjustment(
            prompt_suffix=prompt_suffix,
            bounded_mode_override=True,
        )
    if name == "retry_fresh":
        return StrategyAdjustment(
            prompt_suffix=prompt_suffix,
        )
    if name in STRATEGY_PROMPTS:
        return StrategyAdjustment(
            prompt_suffix=prompt_suffix,
        )
    return StrategyAdjustment(prompt_suffix="")


def apply_strategy_to_prompt(
    *,
    base_prompt: str,
    adjustment: StrategyAdjustment,
) -> str:
    if not adjustment.prompt_suffix:
        return base_prompt
    return f"{base_prompt}\n{adjustment.prompt_suffix}"


def apply_strategy_to_executor_kwargs(
    *,
    kwargs: dict[str, Any],
    adjustment: StrategyAdjustment,
) -> dict[str, Any]:
    result = dict(kwargs)
    if adjustment.timeout_override is not None:
        result["timeout_seconds"] = adjustment.timeout_override
    if adjustment.bounded_mode_override is not None:
        result["bounded_mode"] = adjustment.bounded_mode_override
    return result
