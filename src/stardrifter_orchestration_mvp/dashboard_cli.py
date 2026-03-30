from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import Any

from .factory import build_postgres_repository
from .governance_report_cli import _load_report_rows
from .models import (
    EPIC_RUNTIME_STATUSES,
    EpicExecutionState,
    EpicRuntimeStatus,
    OperatorRequest,
)
from .settings import load_postgres_settings_from_env


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_builder: Callable[..., Any] = build_postgres_repository,
    report_loader: Callable[..., list[dict[str, Any]]] | None = None,
    operator_request_loader: Callable[..., list[OperatorRequest]] | None = None,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)
    connection = getattr(repository, "_connection", repository)
    rows = (
        report_loader(connection=connection, repo=args.repo)
        if report_loader is not None
        else _load_report_rows(connection=connection, repo=args.repo)
    )
    requests = (
        operator_request_loader(repository=repository, repo=args.repo)
        if operator_request_loader is not None
        else repository.list_operator_requests(repo=args.repo, include_closed=False)
    )

    _print_dashboard(
        repository=repository, repo=args.repo, rows=rows, requests=requests
    )
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stardrifter-orchestration-dashboard",
        description="Print a concise governance/operator dashboard for a repository.",
    )
    parser.add_argument("--repo", required=True)
    return parser


def _print_dashboard(
    *,
    repository: Any,
    repo: str,
    rows: Sequence[dict[str, Any]],
    requests: Sequence[OperatorRequest],
) -> None:
    active_epics = {
        row["epic_issue_number"]
        for row in rows
        if row.get("epic_execution_status") == "active"
    }
    print(
        f"repo={repo} active_epics={len(active_epics)} rows={len(rows)} "
        f"open_operator_requests={len(requests)}"
    )

    if not rows and not requests:
        return

    requests_by_reason = _group_requests_by_reason(requests)
    for reason_code in sorted(requests_by_reason):
        reason_requests = requests_by_reason[reason_code]
        print(
            f"operator_reason={reason_code} "
            f"requests={len(reason_requests)} "
            f"epics={len({request.epic_issue_number for request in reason_requests})}"
        )

    epic_ids = sorted(
        {
            row["epic_issue_number"]
            for row in rows
            if row.get("epic_issue_number") is not None
        }
    )
    requests_by_epic = _group_requests_by_epic(requests)
    for epic_issue_number in epic_ids:
        state = repository.get_epic_execution_state(
            repo=repo,
            epic_issue_number=epic_issue_number,
        )
        if state is None:
            state = _state_from_rows(
                repo=repo, epic_issue_number=epic_issue_number, rows=rows
            )
        print(
            f"epic={epic_issue_number} "
            f"runtime_status={state.status} "
            f"operator_attention={_format_bool(state.operator_attention_required)} "
            f"open_requests={len(requests_by_epic.get(epic_issue_number, []))}"
        )


def _group_requests_by_reason(
    requests: Sequence[OperatorRequest],
) -> dict[str, list[OperatorRequest]]:
    grouped_requests: dict[str, list[OperatorRequest]] = {}
    for request in requests:
        grouped_requests.setdefault(request.reason_code, []).append(request)
    return grouped_requests


def _group_requests_by_epic(
    requests: Sequence[OperatorRequest],
) -> dict[int, list[OperatorRequest]]:
    grouped_requests: dict[int, list[OperatorRequest]] = {}
    for request in requests:
        grouped_requests.setdefault(request.epic_issue_number, []).append(request)
    return grouped_requests


def _state_from_rows(
    *,
    repo: str,
    epic_issue_number: int,
    rows: Sequence[dict[str, Any]],
) -> EpicExecutionState:
    epic_rows = [
        row for row in rows if row.get("epic_issue_number") == epic_issue_number
    ]
    status: EpicRuntimeStatus = "backlog"
    if epic_rows:
        status = _coerce_runtime_status(epic_rows[0].get("epic_execution_status"))
    return EpicExecutionState(
        repo=repo,
        epic_issue_number=epic_issue_number,
        status=status,
        operator_attention_required=False,
        verification_status=None,
        verification_reason_code=None,
        last_verification_at=None,
        verification_summary=None,
    )


def _coerce_runtime_status(raw_status: Any) -> EpicRuntimeStatus:
    status = str(raw_status or "backlog")
    if status in EPIC_RUNTIME_STATUSES:
        return status
    return "backlog"


def _format_bool(value: bool) -> str:
    return "true" if value else "false"


if __name__ == "__main__":
    entrypoint()
