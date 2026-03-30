from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import Any

from .factory import build_postgres_repository
from .models import OperatorRequest
from .settings import load_postgres_settings_from_env


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_builder: Callable[..., Any] = build_postgres_repository,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)
    requests = repository.list_operator_requests(
        repo=args.repo,
        include_closed=False,
    )
    _print_operator_request_report(requests)
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stardrifter-orchestration-operator-request-report",
        description="Print a grouped summary of open operator requests for a repository.",
    )
    parser.add_argument("--repo", required=True)
    return parser


def _print_operator_request_report(requests: Sequence[OperatorRequest]) -> None:
    if not requests:
        print("no open operator requests")
        return

    grouped_requests: dict[str, list[OperatorRequest]] = {}
    for request in requests:
        grouped_requests.setdefault(request.reason_code, []).append(request)

    for reason_code in sorted(grouped_requests):
        reason_requests = grouped_requests[reason_code]
        oldest_request = _select_oldest_request(reason_requests)
        oldest_opened_at = "unknown"
        if oldest_request.opened_at is not None:
            oldest_opened_at = oldest_request.opened_at.isoformat()
        print(
            f"reason={reason_code} "
            f"requests={len(reason_requests)} "
            f"epics={len({request.epic_issue_number for request in reason_requests})} "
            f"oldest_epic={oldest_request.epic_issue_number} "
            f"oldest_opened_at={oldest_opened_at}"
        )


def _select_oldest_request(requests: Sequence[OperatorRequest]) -> OperatorRequest:
    dated_requests = [request for request in requests if request.opened_at is not None]
    if dated_requests:
        return min(
            dated_requests,
            key=lambda request: (request.opened_at, request.epic_issue_number),
        )
    return min(requests, key=lambda request: request.epic_issue_number)


if __name__ == "__main__":
    entrypoint()
