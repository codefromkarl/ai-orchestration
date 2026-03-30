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
        epic_issue_number=args.epic_issue_number,
        include_closed=args.include_closed,
    )
    _print_operator_requests(requests)
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stardrifter-orchestration-operator-requests",
        description="List operator requests for a repository.",
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--epic-issue-number", type=int)
    parser.add_argument("--include-closed", action="store_true")
    return parser


def _print_operator_requests(requests: Sequence[OperatorRequest]) -> None:
    if not requests:
        print("no open operator requests")
        return

    for request in requests:
        print(
            f"epic={request.epic_issue_number} "
            f"reason={request.reason_code} "
            f"remaining={len(request.remaining_story_issue_numbers)} "
            f"blocked={len(request.blocked_story_issue_numbers)} "
            f"status={request.status} "
            f"summary={request.summary}"
        )


if __name__ == "__main__":
    entrypoint()
