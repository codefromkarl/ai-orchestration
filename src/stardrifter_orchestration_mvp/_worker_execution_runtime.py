from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any
from typing import Protocol
from typing import TYPE_CHECKING
from typing import cast
from typing import runtime_checkable

from .models import ExecutionContext, WorkClaim, WorkItem
from .protocols import ExecutorAdapter

if TYPE_CHECKING:
    from .worker import ExecutionResult


@runtime_checkable
class _ClaimRenewalRepository(Protocol):
    def list_active_work_claims(self) -> list[WorkClaim]: ...

    def renew_work_claim(
        self, work_id: str, *, lease_token: str
    ) -> WorkClaim | None: ...


def _renew_claim_after_prepare(
    repository: _ClaimRenewalRepository | object,
    work_id: str,
) -> None:
    if not isinstance(repository, _ClaimRenewalRepository):
        return
    active_claims = repository.list_active_work_claims()
    claim = next((claim for claim in active_claims if claim.work_id == work_id), None)
    if claim is None or claim.lease_token is None:
        return
    repository.renew_work_claim(work_id, lease_token=claim.lease_token)


def _run_executor_with_heartbeat(
    *,
    executor: ExecutorAdapter,
    repository: _ClaimRenewalRepository | object,
    work_id: str,
    work_item: WorkItem,
    workspace_path: Path | None,
    execution_context: ExecutionContext,
) -> ExecutionResult:
    signature = inspect.signature(executor)
    if "heartbeat" not in signature.parameters:
        if "execution_context" in signature.parameters:
            return cast(Any, executor)(
                work_item,
                workspace_path,
                execution_context=execution_context,
            )
        return executor(work_item, workspace_path)
    heartbeat_executor = cast(Any, executor)
    kwargs: dict[str, Any] = {
        "heartbeat": lambda: _renew_claim_after_prepare(repository, work_id),
    }
    if "execution_context" in signature.parameters:
        kwargs["execution_context"] = execution_context
    return heartbeat_executor(work_item, workspace_path, **kwargs)
