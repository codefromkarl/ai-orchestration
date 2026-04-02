from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from taskplane.models import ExecutionContext, VerificationEvidence, WorkItem
from taskplane.protocols import (
    as_executor_adapter,
    as_intake_adapter,
    as_story_integrator_adapter,
    as_task_writeback_adapter,
    as_verifier_adapter,
    invoke_executor,
    invoke_intake,
    invoke_story_integrator,
    invoke_task_writeback,
    invoke_verifier,
)
from taskplane.worker import ExecutionResult


def _make_work_item() -> WorkItem:
    return WorkItem(
        id="w1",
        title="Add feature",
        lane="lane-a",
        wave="wave-1",
        status="ready",
        repo="repo-a",
    )


def _make_execution_context() -> ExecutionContext:
    return ExecutionContext(
        work_id="w1",
        title="Add feature",
        lane="lane-a",
        wave="wave-1",
        repo="repo-a",
    )


def _make_verification_evidence() -> VerificationEvidence:
    return VerificationEvidence(
        work_id="w1",
        check_type="pytest",
        command="pytest -q",
        passed=True,
        output_digest="ok",
    )


class TestExecutorAdapterNormalization:
    def test_method_based_adapter_receives_optional_arguments(self) -> None:
        calls: list[tuple[str, Any]] = []

        class ExplicitExecutor:
            def execute(
                self,
                *,
                work_item: WorkItem,
                workspace_path: Path | None = None,
                execution_context: ExecutionContext | None = None,
                heartbeat: Any | None = None,
            ) -> ExecutionResult:
                if heartbeat is not None:
                    heartbeat()
                calls.append(
                    (
                        "execute",
                        work_item.id,
                        str(workspace_path) if workspace_path is not None else None,
                        execution_context.work_id if execution_context else None,
                    )
                )
                return ExecutionResult(success=True, summary="ok")

        executor = ExplicitExecutor()
        adapter = as_executor_adapter(executor)
        assert adapter is not executor

        heartbeat_count = {"n": 0}
        result = invoke_executor(
            adapter,
            work_item=_make_work_item(),
            workspace_path=Path("/tmp/workspace"),
            execution_context=_make_execution_context(),
            heartbeat=lambda: heartbeat_count.__setitem__("n", heartbeat_count["n"] + 1),
        )

        assert result.success is True
        assert calls == [("execute", "w1", "/tmp/workspace", "w1")]
        assert heartbeat_count["n"] == 1

    def test_method_based_adapter_with_narrow_signature_still_works(self) -> None:
        calls: list[tuple[str, Any]] = []

        class NarrowExecutor:
            def execute(
                self,
                *,
                work_item: WorkItem,
                workspace_path: Path | None = None,
            ) -> ExecutionResult:
                calls.append(
                    (
                        work_item.id,
                        str(workspace_path) if workspace_path is not None else None,
                    )
                )
                return ExecutionResult(success=True, summary="narrow ok")

        result = invoke_executor(
            as_executor_adapter(NarrowExecutor()),
            work_item=_make_work_item(),
            workspace_path=Path("/tmp/narrow"),
            execution_context=_make_execution_context(),
            heartbeat=lambda: None,
        )

        assert result.summary == "narrow ok"
        assert calls == [("w1", "/tmp/narrow")]

    def test_plain_callable_adapter_is_wrapped_and_receives_heartbeat(self) -> None:
        calls: list[tuple[str, Any]] = []

        def legacy_executor(
            work_item: WorkItem,
            workspace_path: Path | None = None,
            execution_context: ExecutionContext | None = None,
            heartbeat: Any | None = None,
        ) -> ExecutionResult:
            if heartbeat is not None:
                heartbeat()
            calls.append(
                (
                    work_item.id,
                    str(workspace_path) if workspace_path is not None else None,
                    execution_context.work_id if execution_context else None,
                )
            )
            return ExecutionResult(success=True, summary="legacy ok")

        adapter = as_executor_adapter(legacy_executor)
        assert adapter is not legacy_executor

        heartbeat_count = {"n": 0}
        result = invoke_executor(
            adapter,
            work_item=_make_work_item(),
            workspace_path=Path("/tmp/legacy"),
            execution_context=_make_execution_context(),
            heartbeat=lambda: heartbeat_count.__setitem__("n", heartbeat_count["n"] + 1),
        )

        assert result.summary == "legacy ok"
        assert calls == [("w1", "/tmp/legacy", "w1")]
        assert heartbeat_count["n"] == 1


class TestVerifierAdapterNormalization:
    def test_plain_callable_adapter_receives_execution_context(self) -> None:
        calls: list[tuple[str, Any]] = []

        def legacy_verifier(
            work_item: WorkItem,
            workspace_path: Path | None = None,
            execution_context: ExecutionContext | None = None,
        ) -> VerificationEvidence:
            calls.append(
                (
                    work_item.id,
                    str(workspace_path) if workspace_path is not None else None,
                    execution_context.work_id if execution_context else None,
                )
            )
            return replace(_make_verification_evidence(), output_digest="legacy")

        adapter = as_verifier_adapter(legacy_verifier)
        result = invoke_verifier(
            adapter,
            work_item=_make_work_item(),
            workspace_path=Path("/tmp/verifier"),
            execution_context=_make_execution_context(),
        )

        assert result.output_digest == "legacy"
        assert calls == [("w1", "/tmp/verifier", "w1")]

    def test_method_based_adapter_with_narrow_signature_still_works(self) -> None:
        calls: list[tuple[str, Any]] = []

        class NarrowVerifier:
            def verify(
                self,
                *,
                work_item: WorkItem,
                workspace_path: Path | None = None,
            ) -> VerificationEvidence:
                calls.append(
                    (
                        work_item.id,
                        str(workspace_path) if workspace_path is not None else None,
                    )
                )
                return replace(_make_verification_evidence(), output_digest="narrow")

        result = invoke_verifier(
            as_verifier_adapter(NarrowVerifier()),
            work_item=_make_work_item(),
            workspace_path=Path("/tmp/verifier-narrow"),
            execution_context=_make_execution_context(),
        )

        assert result.output_digest == "narrow"
        assert calls == [("w1", "/tmp/verifier-narrow")]


class TestWritebackAndIntakeNormalization:
    def test_plain_task_writeback_callable_is_wrapped(self) -> None:
        calls: list[tuple[Any, ...]] = []

        def legacy_writeback(
            repo: str,
            issue_number: int,
            status: str,
            decision_required: bool = False,
        ) -> None:
            calls.append((repo, issue_number, status, decision_required))

        adapter = as_task_writeback_adapter(legacy_writeback)
        invoke_task_writeback(
            adapter,
            repo="repo-a",
            issue_number=17,
            status="done",
            decision_required=True,
        )

        assert calls == [("repo-a", 17, "done", True)]

    def test_method_based_task_writeback_adapter_with_narrow_signature_still_works(
        self,
    ) -> None:
        calls: list[tuple[Any, ...]] = []

        class NarrowWriteback:
            def write_back(
                self,
                *,
                repo: str,
                issue_number: int,
                status: str,
            ) -> None:
                calls.append((repo, issue_number, status))

        invoke_task_writeback(
            as_task_writeback_adapter(NarrowWriteback()),
            repo="repo-a",
            issue_number=17,
            status="done",
            decision_required=True,
        )

        assert calls == [("repo-a", 17, "done")]

    def test_plain_intake_callable_is_wrapped(self) -> None:
        calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        def legacy_intake(*args: Any, **kwargs: Any) -> str:
            calls.append((args, kwargs))
            return "ingested"

        adapter = as_intake_adapter(legacy_intake)
        result = invoke_intake(adapter, connection="conn-1", repo="repo-a")

        assert result == "ingested"
        assert calls == [((), {"connection": "conn-1", "repo": "repo-a"})]

    def test_plain_story_integrator_callable_is_wrapped(self) -> None:
        calls: list[tuple[int, list[str]]] = []

        def legacy_integrator(
            story_issue_number: int,
            story_work_items: list[WorkItem],
        ) -> dict[str, Any]:
            calls.append(
                (story_issue_number, [work_item.id for work_item in story_work_items])
            )
            return {"merged": True}

        adapter = as_story_integrator_adapter(legacy_integrator)
        result = invoke_story_integrator(
            adapter,
            story_issue_number=88,
            story_work_items=[_make_work_item()],
        )

        assert result == {"merged": True}
        assert calls == [(88, ["w1"])]
