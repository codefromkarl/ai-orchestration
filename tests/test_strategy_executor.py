from __future__ import annotations

from stardrifter_orchestration_mvp.models import ExecutionSession
from stardrifter_orchestration_mvp.strategy_executor import (
    apply_strategy_to_executor_kwargs,
    apply_strategy_to_prompt,
    resolve_strategy,
)


class TestResolveStrategy:
    def test_retry_fresh(self) -> None:
        session = ExecutionSession(id="s1", work_id="w1", current_phase="researching")
        adj = resolve_strategy(session=session, strategy_name="retry_fresh")
        assert adj.timeout_override is None
        assert adj.bounded_mode_override is None

    def test_retry_with_narrowed_scope(self) -> None:
        session = ExecutionSession(id="s1", work_id="w1", current_phase="researching")
        adj = resolve_strategy(
            session=session, strategy_name="retry_with_narrowed_scope"
        )
        assert adj.bounded_mode_override is True
        assert "缩小执行范围" in adj.prompt_suffix

    def test_diagnose_then_retry(self) -> None:
        session = ExecutionSession(id="s1", work_id="w1", current_phase="researching")
        adj = resolve_strategy(session=session, strategy_name="diagnose_then_retry")
        assert "诊断" in adj.prompt_suffix

    def test_unknown_strategy(self) -> None:
        session = ExecutionSession(id="s1", work_id="w1", current_phase="researching")
        adj = resolve_strategy(session=session, strategy_name="nonexistent")
        assert adj.prompt_suffix == ""

    def test_empty_strategy(self) -> None:
        session = ExecutionSession(id="s1", work_id="w1", current_phase="researching")
        adj = resolve_strategy(session=session, strategy_name="")
        assert adj.prompt_suffix == ""


class TestApplyStrategy:
    def test_apply_prompt_suffix(self) -> None:
        from stardrifter_orchestration_mvp.strategy_executor import StrategyAdjustment

        adj = StrategyAdjustment(prompt_suffix="\nExtra instruction")
        result = apply_strategy_to_prompt(base_prompt="Base prompt", adjustment=adj)
        assert result == "Base prompt\n\nExtra instruction"

    def test_apply_empty_suffix(self) -> None:
        from stardrifter_orchestration_mvp.strategy_executor import StrategyAdjustment

        adj = StrategyAdjustment(prompt_suffix="")
        result = apply_strategy_to_prompt(base_prompt="Base prompt", adjustment=adj)
        assert result == "Base prompt"

    def test_apply_executor_kwargs(self) -> None:
        from stardrifter_orchestration_mvp.strategy_executor import StrategyAdjustment

        adj = StrategyAdjustment(prompt_suffix="", bounded_mode_override=True)
        kwargs = {"timeout_seconds": 1200, "other": "value"}
        result = apply_strategy_to_executor_kwargs(kwargs=kwargs, adjustment=adj)
        assert result["bounded_mode"] is True
        assert result["timeout_seconds"] == 1200
        assert result["other"] == "value"
