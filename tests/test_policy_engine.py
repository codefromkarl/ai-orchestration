from __future__ import annotations

from taskplane.policy_engine import (
    PolicyResolution,
    evaluate_policy,
)
from taskplane.session_manager import InMemorySessionManager


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

    def test_guardrail_reason_code_requires_human_review(self) -> None:
        session, _ = _make_session_with_context()
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context={"reason_code": "human-approval-required"},
            attempt_index=1,
        )
        assert res.resolution == "human_required"
        assert res.detail == {"reason_class": "guardrail_hard_stop"}

    def test_workspace_conflict_prefers_retry_after_clean(self) -> None:
        session, _ = _make_session_with_context()
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context={"reason_code": "path-conflict:src/foo.py"},
            attempt_index=1,
        )
        assert res.resolution == "auto_resolve"
        assert res.detail == {
            "reason_class": "workspace_conflict",
            "matched_prefix": "path-conflict:",
        }

    def test_interrupted_retryable_prefers_retry_fresh(self) -> None:
        session, _ = _make_session_with_context()
        res = evaluate_policy(
            session=session,
            checkpoint=None,
            failure_context={"reason_code": "interrupted_retryable"},
            attempt_index=1,
        )
        assert res.resolution == "retry_strategy"
        assert res.detail == {
            "reason_class": "transient_executor_failure",
            "strategy": "retry_fresh",
        }
