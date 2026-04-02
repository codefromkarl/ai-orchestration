from __future__ import annotations

from pathlib import Path
from typing import Protocol
from typing import TYPE_CHECKING
from typing import runtime_checkable

from .models import ExecutionContext, WorkClaim, WorkItem
from .protocols import ExecutorAdapter, invoke_executor

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
    return invoke_executor(
        executor,
        work_item=work_item,
        workspace_path=workspace_path,
        execution_context=execution_context,
        heartbeat=lambda: _renew_claim_after_prepare(repository, work_id),
    )
