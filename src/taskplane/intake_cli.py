from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence

from .factory import build_postgres_repository
from .intake_service import NaturalLanguageIntakeService, build_default_analyzer
from .settings import load_postgres_settings_from_env


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_builder: Callable[..., object] = build_postgres_repository,
    analyzer_builder: Callable[..., object] = build_default_analyzer,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)
    analyzer = analyzer_builder(repository)
    service = NaturalLanguageIntakeService(repository=repository, analyzer=analyzer)

    if args.command == "submit":
        intent = service.submit_intent(repo=args.repo, prompt=args.prompt)
        _print_intent(intent)
        return 0
    if args.command == "answer":
        intent = service.answer_intent(intent_id=args.intent_id, answer=args.answer)
        _print_intent(intent)
        return 0
    if args.command == "approve":
        intent = service.approve_intent(intent_id=args.intent_id, approver=args.approver)
        _print_intent(intent)
        return 0
    raise SystemExit(f"unsupported command: {args.command}")


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskplane-intake",
        description="Submit and review natural-language intake proposals.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit = subparsers.add_parser("submit")
    submit.add_argument("--repo", required=True)
    submit.add_argument("--prompt", required=True)

    answer = subparsers.add_parser("answer")
    answer.add_argument("--intent-id", required=True)
    answer.add_argument("--answer", required=True)

    approve = subparsers.add_parser("approve")
    approve.add_argument("--intent-id", required=True)
    approve.add_argument("--approver", required=True)

    return parser


def _print_intent(intent) -> None:
    print(
        json.dumps(
            {
                "intent_id": intent.id,
                "repo": intent.repo,
                "status": intent.status,
                "summary": intent.summary,
                "questions": list(intent.clarification_questions),
                "proposal": intent.proposal_json,
                "promoted_epic_issue_number": intent.promoted_epic_issue_number,
                "approved_by": intent.approved_by,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    entrypoint()
