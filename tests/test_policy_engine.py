from __future__ import annotations

from stardrifter_orchestration_mvp.policy_engine import (
    PolicyResolution,
    evaluate_policy,
)
from stardrifter_orchestration_mvp.session_manager import InMemorySessionManager


def _make_session_with_context(**kwargs):
    mgr = InMemorySessionManager()
    session = mgr.create_session(work_id="w1", **kwargs)
    return session, mgr


class TestEvaluatePolicy:
    def test_human_required_for_approval_keyword(self) -> None:
        session, _ = _make_session_with_context()
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context={"outcome": "needs_decision", "summary": "需要审批"},
            attempt_index=1,
        )
        assert res.resolution == "human_required"
        assert res.risk_level == "high"

    def test_auto_resolve_for_dirty_tree(self) -> None:
        session, _ = _make_session_with_context()
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context={"summary": "dirty worktree detected"},
            attempt_index=1,
        )
        assert res.resolution == "auto_resolve"

    def test_retry_strategy_for_needs_decision_low_attempts(self) -> None:
        session, _ = _make_session_with_context()
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context={"outcome": "needs_decision", "summary": "unclear scope"},
            attempt_index=1,
        )
        assert res.resolution == "retry_strategy"

    def test_human_required_for_needs_decision_high_attempts(self) -> None:
        session, _ = _make_session_with_context()
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context={"outcome": "needs_decision", "summary": "unclear scope"},
            attempt_index=5,
        )
        assert res.resolution == "human_required"

    def test_retry_strategy_for_timeout_low_attempts(self) -> None:
        session, _ = _make_session_with_context()
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context={"reason_code": "timeout"},
            attempt_index=2,
        )
        assert res.resolution == "retry_strategy"
        assert res.risk_level == "low"

    def test_human_required_for_timeout_high_attempts(self) -> None:
        session, _ = _make_session_with_context()
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context={"reason_code": "timeout"},
            attempt_index=6,
        )
        assert res.resolution == "human_required"

    def test_retry_strategy_for_verifier_failure(self) -> None:
        session, _ = _make_session_with_context()
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context={"summary": "verifier failed: test_x"},
            attempt_index=1,
        )
        assert res.resolution == "retry_strategy"

    def test_default_retry_for_non_specific(self) -> None:
        session, _ = _make_session_with_context()
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context={"summary": "something went wrong"},
            attempt_index=1,
        )
        assert res.resolution == "retry_strategy"

    def test_default_human_required_after_many_attempts(self) -> None:
        session, _ = _make_session_with_context()
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context={"summary": "something went wrong"},
            attempt_index=5,
        )
        assert res.resolution == "human_required"
