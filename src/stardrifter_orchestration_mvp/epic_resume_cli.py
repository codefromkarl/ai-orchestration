from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .factory import build_postgres_repository
from .models import EpicExecutionState, ProgramStory
from .settings import load_postgres_settings_from_env


@dataclass(frozen=True)
class EpicRefreshResult:
    state: EpicExecutionState
    open_request_count: int
    continue_ready: bool


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_builder: Callable[..., Any] = build_postgres_repository,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)
    mode = "dry-run" if args.dry_run else "apply"
    refresh_result = preview_epic_execution_state(
        repository=repository,
        repo=args.repo,
        epic_issue_number=args.epic_issue_number,
    )
    if args.dry_run:
        refresh_result = EpicRefreshResult(
            state=refresh_result.state,
            open_request_count=refresh_result.open_request_count,
            continue_ready=False,
        )
    if not args.dry_run:
        repository.upsert_epic_execution_state(refresh_result.state)
    print(_format_refresh_result(mode=mode, result=refresh_result))
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def refresh_epic_execution_state(
    *,
    repository: Any,
    repo: str,
    epic_issue_number: int,
) -> EpicRefreshResult:
    refresh_result = preview_epic_execution_state(
        repository=repository,
        repo=repo,
        epic_issue_number=epic_issue_number,
    )
    repository.upsert_epic_execution_state(refresh_result.state)
    return refresh_result


def preview_epic_execution_state(
    *,
    repository: Any,
    repo: str,
    epic_issue_number: int,
) -> EpicRefreshResult:
    previous_state = repository.get_epic_execution_state(
        repo=repo,
        epic_issue_number=epic_issue_number,
    )
    stories = repository.list_program_stories_for_epic(
        repo=repo,
        epic_issue_number=epic_issue_number,
    )
    open_request_count = len(
        repository.list_operator_requests(
            repo=repo,
            epic_issue_number=epic_issue_number,
        )
    )
    refreshed_state = _build_refreshed_state(
        repo=repo,
        epic_issue_number=epic_issue_number,
        stories=stories,
        previous_state=previous_state,
        has_open_requests=open_request_count > 0,
    )
    return EpicRefreshResult(
        state=refreshed_state,
        open_request_count=open_request_count,
        continue_ready=_is_continue_ready(
            previous_state=previous_state,
            refreshed_state=refreshed_state,
            open_request_count=open_request_count,
        ),
    )


def _build_refreshed_state(
    *,
    repo: str,
    epic_issue_number: int,
    stories: list[ProgramStory],
    previous_state: EpicExecutionState | None,
    has_open_requests: bool,
) -> EpicExecutionState:
    (
        completed_story_issue_numbers,
        blocked_story_issue_numbers,
        remaining_story_issue_numbers,
    ) = _classify_story_issue_numbers(stories)
    if not stories:
        return EpicExecutionState(
            repo=repo,
            epic_issue_number=epic_issue_number,
            status="backlog",
            completed_story_issue_numbers=completed_story_issue_numbers,
            blocked_story_issue_numbers=blocked_story_issue_numbers,
            remaining_story_issue_numbers=remaining_story_issue_numbers,
            blocked_reason_code="epic_has_no_stories",
            operator_attention_required=has_open_requests,
            last_operator_action_at=(
                previous_state.last_operator_action_at
                if previous_state is not None
                else None
            ),
            last_operator_action_reason=(
                previous_state.last_operator_action_reason
                if previous_state is not None
                else None
            ),
            last_progress_at=(
                previous_state.last_progress_at if previous_state is not None else None
            ),
            stalled_since=(
                previous_state.stalled_since if previous_state is not None else None
            ),
            verification_status=(
                previous_state.verification_status
                if previous_state is not None
                else None
            ),
            verification_reason_code=(
                previous_state.verification_reason_code
                if previous_state is not None
                else None
            ),
            last_verification_at=(
                previous_state.last_verification_at
                if previous_state is not None
                else None
            ),
            verification_summary=(
                previous_state.verification_summary
                if previous_state is not None
                else None
            ),
        )

    if all(story.execution_status == "done" for story in stories):
        verification_passed = (
            previous_state is not None
            and previous_state.verification_status == "passed"
        )
        return EpicExecutionState(
            repo=repo,
            epic_issue_number=epic_issue_number,
            status="done" if verification_passed else "awaiting_operator",
            completed_story_issue_numbers=completed_story_issue_numbers,
            blocked_story_issue_numbers=blocked_story_issue_numbers,
            remaining_story_issue_numbers=remaining_story_issue_numbers,
            blocked_reason_code=(
                "epic_complete" if verification_passed else "epic_verification_pending"
            ),
            operator_attention_required=has_open_requests,
            last_operator_action_at=(
                previous_state.last_operator_action_at
                if previous_state is not None
                else None
            ),
            last_operator_action_reason=(
                previous_state.last_operator_action_reason
                if previous_state is not None
                else None
            ),
            last_progress_at=(
                previous_state.last_progress_at if previous_state is not None else None
            ),
            stalled_since=(
                previous_state.stalled_since if previous_state is not None else None
            ),
            verification_status=(
                previous_state.verification_status
                if previous_state is not None
                else None
            ),
            verification_reason_code=(
                previous_state.verification_reason_code
                if previous_state is not None
                else None
            ),
            last_verification_at=(
                previous_state.last_verification_at
                if previous_state is not None
                else None
            ),
            verification_summary=(
                previous_state.verification_summary
                if previous_state is not None
                else None
            ),
        )

    if any(
        story.execution_status in {"active", "planned", "decomposing"}
        for story in stories
    ):
        return EpicExecutionState(
            repo=repo,
            epic_issue_number=epic_issue_number,
            status="active",
            completed_story_issue_numbers=completed_story_issue_numbers,
            blocked_story_issue_numbers=blocked_story_issue_numbers,
            remaining_story_issue_numbers=remaining_story_issue_numbers,
            blocked_reason_code="epic_incomplete",
            operator_attention_required=has_open_requests,
            last_operator_action_at=(
                previous_state.last_operator_action_at
                if previous_state is not None
                else None
            ),
            last_operator_action_reason=(
                previous_state.last_operator_action_reason
                if previous_state is not None
                else None
            ),
            last_progress_at=(
                previous_state.last_progress_at if previous_state is not None else None
            ),
            stalled_since=(
                previous_state.stalled_since if previous_state is not None else None
            ),
            verification_status=(
                previous_state.verification_status
                if previous_state is not None
                else None
            ),
            verification_reason_code=(
                previous_state.verification_reason_code
                if previous_state is not None
                else None
            ),
            last_verification_at=(
                previous_state.last_verification_at
                if previous_state is not None
                else None
            ),
            verification_summary=(
                previous_state.verification_summary
                if previous_state is not None
                else None
            ),
        )

    if any(story.execution_status in {"blocked", "gated"} for story in stories):
        return EpicExecutionState(
            repo=repo,
            epic_issue_number=epic_issue_number,
            status="awaiting_operator",
            completed_story_issue_numbers=completed_story_issue_numbers,
            blocked_story_issue_numbers=blocked_story_issue_numbers,
            remaining_story_issue_numbers=remaining_story_issue_numbers,
            blocked_reason_code=(
                "epic_verification_failed"
                if any(story.execution_status == "gated" for story in stories)
                else "all_remaining_stories_blocked"
            ),
            operator_attention_required=has_open_requests,
            last_operator_action_at=(
                previous_state.last_operator_action_at
                if previous_state is not None
                else None
            ),
            last_operator_action_reason=(
                previous_state.last_operator_action_reason
                if previous_state is not None
                else None
            ),
            last_progress_at=(
                previous_state.last_progress_at if previous_state is not None else None
            ),
            stalled_since=(
                previous_state.stalled_since if previous_state is not None else None
            ),
            verification_status=(
                previous_state.verification_status
                if previous_state is not None
                else None
            ),
            verification_reason_code=(
                previous_state.verification_reason_code
                if previous_state is not None
                else None
            ),
            last_verification_at=(
                previous_state.last_verification_at
                if previous_state is not None
                else None
            ),
            verification_summary=(
                previous_state.verification_summary
                if previous_state is not None
                else None
            ),
        )

    return EpicExecutionState(
        repo=repo,
        epic_issue_number=epic_issue_number,
        status="backlog",
        completed_story_issue_numbers=completed_story_issue_numbers,
        blocked_story_issue_numbers=blocked_story_issue_numbers,
        remaining_story_issue_numbers=remaining_story_issue_numbers,
        blocked_reason_code="epic_has_no_active_stories",
        operator_attention_required=has_open_requests,
        last_operator_action_at=(
            previous_state.last_operator_action_at
            if previous_state is not None
            else None
        ),
        last_operator_action_reason=(
            previous_state.last_operator_action_reason
            if previous_state is not None
            else None
        ),
        last_progress_at=(
            previous_state.last_progress_at if previous_state is not None else None
        ),
        stalled_since=(
            previous_state.stalled_since if previous_state is not None else None
        ),
        verification_status=(
            previous_state.verification_status if previous_state is not None else None
        ),
        verification_reason_code=(
            previous_state.verification_reason_code
            if previous_state is not None
            else None
        ),
        last_verification_at=(
            previous_state.last_verification_at if previous_state is not None else None
        ),
        verification_summary=(
            previous_state.verification_summary if previous_state is not None else None
        ),
    )


def _classify_story_issue_numbers(
    stories: list[ProgramStory],
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    completed_story_issue_numbers: list[int] = []
    blocked_story_issue_numbers: list[int] = []
    remaining_story_issue_numbers: list[int] = []
    for story in stories:
        if story.execution_status == "done":
            completed_story_issue_numbers.append(story.issue_number)
        elif story.execution_status == "blocked":
            blocked_story_issue_numbers.append(story.issue_number)
        else:
            remaining_story_issue_numbers.append(story.issue_number)
    return (
        tuple(sorted(completed_story_issue_numbers)),
        tuple(sorted(blocked_story_issue_numbers)),
        tuple(sorted(remaining_story_issue_numbers)),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stardrifter-orchestration-epic-resume",
        description="Refresh epic execution state from current runtime and operator request data.",
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--epic-issue-number", required=True, type=int)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _format_bool(value: bool) -> str:
    return "true" if value else "false"


def _is_continue_ready(
    *,
    previous_state: EpicExecutionState | None,
    refreshed_state: EpicExecutionState,
    open_request_count: int,
) -> bool:
    del previous_state, refreshed_state, open_request_count
    return False


def _format_refresh_result(*, mode: str, result: EpicRefreshResult) -> str:
    return (
        f"mode={mode} epic={result.state.epic_issue_number} status={result.state.status} "
        f"operator_attention={_format_bool(result.state.operator_attention_required)} "
        f"open_requests={result.open_request_count} "
        f"continue_ready={_format_bool(result.continue_ready)}"
    )


if __name__ == "__main__":
    entrypoint()
