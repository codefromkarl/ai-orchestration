from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import Any

from .epic_resume_cli import _format_refresh_result, refresh_epic_execution_state
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
    request = repository.close_operator_request(
        repo=args.repo,
        epic_issue_number=args.epic_issue_number,
        reason_code=args.reason_code,
        closed_reason=args.closed_reason,
    )
    if request is None:
        print(
            "operator request not found for "
            f"epic={args.epic_issue_number} reason={args.reason_code}"
        )
        return 1
    _print_closed_operator_request(request)
    refresh_result = refresh_epic_execution_state(
        repository=repository,
        repo=args.repo,
        epic_issue_number=args.epic_issue_number,
    )
    print(_format_refresh_result(mode="apply", result=refresh_result))
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stardrifter-orchestration-operator-request-ack",
        description="Close an operator request for a repository.",
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--epic-issue-number", required=True, type=int)
    parser.add_argument("--reason-code", required=True)
    parser.add_argument("--closed-reason", required=True)
    return parser


def _print_closed_operator_request(request: OperatorRequest) -> None:
    print(
        f"closed operator request epic={request.epic_issue_number} "
        f"reason={request.reason_code} "
        f"status={request.status} "
        f"closed_reason={request.closed_reason}"
    )


if __name__ == "__main__":
    entrypoint()
