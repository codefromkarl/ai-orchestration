from __future__ import annotations

from dataclasses import dataclass
import inspect
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING, Protocol, cast

from .models import (
    ExecutionCheckpoint,
    ExecutionContext,
    ExecutionSession,
    PolicyResolutionRecord,
    SessionStatus,
    VerificationEvidence,
    WorkItem,
)

if TYPE_CHECKING:
    from .models import ExecutionWakeup
    from .worker import ExecutionResult


@dataclass(frozen=True)
class SessionTurnRequest:
    session_id: str
    work_id: str
    resume_context: str
    current_phase: str


def _has_keyword_parameter(callable_obj: Any, parameter_name: str) -> bool:
    signature = inspect.signature(callable_obj)
    parameter = signature.parameters.get(parameter_name)
    if parameter is not None and parameter.kind != inspect.Parameter.POSITIONAL_ONLY:
        return True
    return any(
        candidate.kind == inspect.Parameter.VAR_KEYWORD
        for candidate in signature.parameters.values()
    )


def _accepts_required_keywords(callable_obj: Any, parameter_names: tuple[str, ...]) -> bool:
    signature = inspect.signature(callable_obj)
    parameters = signature.parameters
    has_var_keyword = any(
        candidate.kind == inspect.Parameter.VAR_KEYWORD
        for candidate in parameters.values()
    )
    if has_var_keyword:
        return True
    for parameter_name in parameter_names:
        parameter = parameters.get(parameter_name)
        if parameter is None or parameter.kind == inspect.Parameter.POSITIONAL_ONLY:
            return False
    return True


def _accepts_positional_parameter(
    callable_obj: Any,
    position_index: int,
) -> bool:
    signature = inspect.signature(callable_obj)
    positional_slots = 0
    for parameter in signature.parameters.values():
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            positional_slots += 1
        elif parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            return True
        if positional_slots >= position_index:
            return True
    return False


@dataclass(frozen=True)
class _CallableExecutorAdapter:
    execute_fn: Callable[..., Any]

    def execute(
        self,
        *,
        work_item: WorkItem,
        workspace_path: Path | None = None,
        execution_context: ExecutionContext | None = None,
        heartbeat: Any | None = None,
    ) -> "ExecutionResult":
        kwargs: dict[str, Any] = {
            "work_item": work_item,
            "workspace_path": workspace_path,
        }
        if _has_keyword_parameter(self.execute_fn, "execution_context"):
            kwargs["execution_context"] = execution_context
        if _has_keyword_parameter(self.execute_fn, "heartbeat"):
            kwargs["heartbeat"] = heartbeat
        if _accepts_required_keywords(self.execute_fn, ("work_item", "workspace_path")):
            return self.execute_fn(**kwargs)
        args: list[Any] = [work_item, workspace_path]
        if _accepts_positional_parameter(self.execute_fn, 3):
            args.append(execution_context)
        if _accepts_positional_parameter(self.execute_fn, 4):
            args.append(heartbeat)
        return self.execute_fn(*args)


@dataclass(frozen=True)
class _CallableVerifierAdapter:
    verify_fn: Callable[..., Any]

    def verify(
        self,
        *,
        work_item: WorkItem,
        workspace_path: Path | None = None,
        execution_context: ExecutionContext | None = None,
    ) -> VerificationEvidence:
        kwargs: dict[str, Any] = {
            "work_item": work_item,
            "workspace_path": workspace_path,
        }
        if _has_keyword_parameter(self.verify_fn, "execution_context"):
            kwargs["execution_context"] = execution_context
        if _accepts_required_keywords(self.verify_fn, ("work_item", "workspace_path")):
            return self.verify_fn(**kwargs)
        args: list[Any] = [work_item, workspace_path]
        if _accepts_positional_parameter(self.verify_fn, 3):
            args.append(execution_context)
        return self.verify_fn(*args)


@dataclass(frozen=True)
class _CallableWriteBackAdapter:
    write_back_fn: Callable[..., Any]

    def write_back(
        self,
        *,
        repo: str,
        issue_number: int,
        status: str,
        decision_required: bool = False,
    ) -> None:
        kwargs: dict[str, Any] = {
            "repo": repo,
            "issue_number": issue_number,
            "status": status,
        }
        if _has_keyword_parameter(self.write_back_fn, "decision_required"):
            kwargs["decision_required"] = decision_required
        if _accepts_required_keywords(
            self.write_back_fn, ("repo", "issue_number", "status")
        ):
            self.write_back_fn(**kwargs)
            return
        args = [repo, issue_number, status]
        if _accepts_positional_parameter(self.write_back_fn, 4):
            args.append(decision_required)
        self.write_back_fn(*args)


@dataclass(frozen=True)
class _CallableStoryIntegratorAdapter:
    integrate_fn: Callable[..., Any]

    def integrate(
        self,
        *,
        story_issue_number: int,
        story_work_items: list[WorkItem],
    ) -> Any:
        kwargs = {
            "story_issue_number": story_issue_number,
            "story_work_items": story_work_items,
        }
        if _accepts_required_keywords(
            self.integrate_fn, ("story_issue_number", "story_work_items")
        ):
            return self.integrate_fn(**kwargs)
        return self.integrate_fn(story_issue_number, story_work_items)


@dataclass(frozen=True)
class _CallableIntakeAdapter:
    ingest_fn: Callable[..., Any]

    def ingest(self, *args: Any, **kwargs: Any) -> Any:
        return self.ingest_fn(*args, **kwargs)


def as_executor_adapter(executor: Any) -> ExecutorAdapter:
    execute = getattr(executor, "execute", None)
    if callable(execute):
        return _CallableExecutorAdapter(cast(Callable[..., Any], execute))
    if callable(executor):
        return _CallableExecutorAdapter(cast(Callable[..., Any], executor))
    raise TypeError(f"{executor!r} is not a valid executor")


def as_verifier_adapter(verifier: Any) -> VerifierAdapter:
    verify = getattr(verifier, "verify", None)
    if callable(verify):
        return _CallableVerifierAdapter(cast(Callable[..., Any], verify))
    if callable(verifier):
        return _CallableVerifierAdapter(cast(Callable[..., Any], verifier))
    raise TypeError(f"{verifier!r} is not a valid verifier")


def as_task_writeback_adapter(writeback: Any) -> TaskWritebackAdapter:
    write_back = getattr(writeback, "write_back", None)
    if callable(write_back):
        return _CallableWriteBackAdapter(cast(Callable[..., Any], write_back))
    if callable(writeback):
        return _CallableWriteBackAdapter(cast(Callable[..., Any], writeback))
    raise TypeError(f"{writeback!r} is not a valid task writeback")


def as_story_writeback_adapter(writeback: Any) -> StoryWritebackAdapter:
    write_back = getattr(writeback, "write_back", None)
    if callable(write_back):
        return _CallableWriteBackAdapter(cast(Callable[..., Any], write_back))
    if callable(writeback):
        return _CallableWriteBackAdapter(cast(Callable[..., Any], writeback))
    raise TypeError(f"{writeback!r} is not a valid story writeback")


def as_story_integrator_adapter(integrator: Any) -> StoryIntegratorAdapter:
    integrate = getattr(integrator, "integrate", None)
    if callable(integrate):
        return _CallableStoryIntegratorAdapter(cast(Callable[..., Any], integrate))
    if callable(integrator):
        return _CallableStoryIntegratorAdapter(cast(Callable[..., Any], integrator))
    raise TypeError(f"{integrator!r} is not a valid story integrator")


def as_intake_adapter(intake: Any) -> IntakeAdapter:
    ingest = getattr(intake, "ingest", None)
    if callable(ingest):
        return _CallableIntakeAdapter(cast(Callable[..., Any], ingest))
    if callable(intake):
        return _CallableIntakeAdapter(cast(Callable[..., Any], intake))
    raise TypeError(f"{intake!r} is not a valid intake adapter")


def invoke_executor(
    executor: Any,
    *,
    work_item: WorkItem,
    workspace_path: Path | None = None,
    execution_context: ExecutionContext | None = None,
    heartbeat: Any | None = None,
) -> "ExecutionResult":
    return as_executor_adapter(executor).execute(
        work_item=work_item,
        workspace_path=workspace_path,
        execution_context=execution_context,
        heartbeat=heartbeat,
    )


def invoke_verifier(
    verifier: Any,
    *,
    work_item: WorkItem,
    workspace_path: Path | None = None,
    execution_context: ExecutionContext | None = None,
) -> VerificationEvidence:
    return as_verifier_adapter(verifier).verify(
        work_item=work_item,
        workspace_path=workspace_path,
        execution_context=execution_context,
    )


def invoke_task_writeback(
    writeback: Any,
    *,
    repo: str,
    issue_number: int,
    status: str,
    decision_required: bool = False,
) -> None:
    as_task_writeback_adapter(writeback).write_back(
        repo=repo,
        issue_number=issue_number,
        status=status,
        decision_required=decision_required,
    )


def invoke_story_writeback(
    writeback: Any,
    *,
    repo: str,
    issue_number: int,
    status: str,
    decision_required: bool = False,
) -> None:
    as_story_writeback_adapter(writeback).write_back(
        repo=repo,
        issue_number=issue_number,
        status=status,
        decision_required=decision_required,
    )


def invoke_story_integrator(
    integrator: Any,
    *,
    story_issue_number: int,
    story_work_items: list[WorkItem],
) -> Any:
    return as_story_integrator_adapter(integrator).integrate(
        story_issue_number=story_issue_number,
        story_work_items=story_work_items,
    )


def invoke_intake(
    intake: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    return as_intake_adapter(intake).ingest(*args, **kwargs)


class ExecutorAdapter(Protocol):
    def execute(
        self,
        *,
        work_item: WorkItem,
        workspace_path: Path | None = None,
        execution_context: ExecutionContext | None = None,
        heartbeat: Any | None = None,
    ) -> "ExecutionResult": ...


class VerifierAdapter(Protocol):
    def verify(
        self,
        *,
        work_item: WorkItem,
        workspace_path: Path | None = None,
        execution_context: ExecutionContext | None = None,
    ) -> VerificationEvidence: ...


class TaskWritebackAdapter(Protocol):
    def write_back(
        self,
        *,
        repo: str,
        issue_number: int,
        status: str,
        decision_required: bool = False,
    ) -> None: ...


class StoryWritebackAdapter(Protocol):
    def write_back(
        self,
        *,
        repo: str,
        issue_number: int,
        status: str,
        decision_required: bool = False,
    ) -> None: ...


class StoryIntegratorAdapter(Protocol):
    def integrate(
        self,
        *,
        story_issue_number: int,
        story_work_items: list[WorkItem],
    ) -> Any: ...


class WorkspaceAdapter(Protocol):
    repo_root: Path
    worktree_root: Path

    def prewarm(self, *, work_items: list[WorkItem]) -> list[Path]: ...

    def prepare(
        self, *, work_item: WorkItem, worker_name: str, repository: Any
    ) -> Path: ...

    def release(self, *, work_item: WorkItem, repository: Any) -> None: ...


class IntakeAdapter(Protocol):
    def ingest(self, *args: Any, **kwargs: Any) -> Any: ...


class HierarchyRunnerAdapter(Protocol):
    def run(self, *args: Any, **kwargs: Any) -> Any: ...


class SessionTurnExecutor(Protocol):
    def run_turn(self, request: SessionTurnRequest) -> Any: ...


class SessionManagerProtocol(Protocol):
    def create_session(
        self,
        *,
        work_id: str,
        current_phase: str = "planning",
        strategy_name: str | None = None,
        context_summary: str | None = None,
        attempt_index: int = 1,
        parent_session_id: str | None = None,
    ) -> ExecutionSession: ...

    def get_session(self, session_id: str) -> ExecutionSession | None: ...

    def update_session_status(
        self,
        session_id: str,
        status: SessionStatus,
    ) -> ExecutionSession | None: ...

    def suspend_session(
        self,
        session_id: str,
        waiting_reason: str,
        wake_after: str | None = None,
        wake_condition: dict[str, Any] | None = None,
    ) -> ExecutionSession | None: ...

    def resume_session(self, session_id: str) -> ExecutionSession | None: ...

    def update_session_phase(
        self,
        session_id: str,
        phase: str,
        strategy_name: str | None = None,
    ) -> ExecutionSession | None: ...

    def append_checkpoint(
        self,
        session_id: str,
        *,
        phase: str,
        summary: str,
        artifacts: dict[str, Any] | None = None,
        tool_state: dict[str, Any] | None = None,
        subtasks: list[Any] | None = None,
        failure_context: dict[str, Any] | None = None,
        next_action_hint: str | None = None,
        next_action_params: dict[str, Any] | None = None,
    ) -> ExecutionCheckpoint | None: ...

    def get_latest_checkpoint(self, session_id: str) -> ExecutionCheckpoint | None: ...

    def record_policy_resolution(
        self,
        *,
        session_id: str,
        work_id: str,
        risk_level: str,
        trigger_reason: str,
        evidence_json: dict[str, Any] | None = None,
        resolution: str,
        resolution_detail_json: dict[str, Any] | None = None,
        applied: bool = False,
    ) -> PolicyResolutionRecord | None: ...

    def get_latest_policy_resolution(
        self, session_id: str
    ) -> PolicyResolutionRecord | None: ...

    def build_resume_context(self, session_id: str) -> str: ...

    def list_active_sessions_for_work(self, work_id: str) -> list[ExecutionSession]: ...


class WakeupDispatcherProtocol(Protocol):
    def register_wakeup(
        self,
        *,
        session_id: str,
        work_id: str,
        wake_type: str,
        wake_condition: dict[str, Any],
        scheduled_at: str | None = None,
    ) -> "ExecutionWakeup": ...

    def process_fireable(self) -> list[str]: ...

    def list_by_session(self, session_id: str) -> list["ExecutionWakeup"]: ...

    def fire_wakeup(self, wakeup_id: str) -> "ExecutionWakeup" | None: ...
