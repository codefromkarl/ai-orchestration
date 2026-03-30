from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .epic_scheduler import select_story_batch
from .models import (
    EpicExecutionState,
    EpicRunResult,
    EpicRuntimeStatus,
    OperatorRequest,
    ProgramStory,
    StoryRunResult,
)
from .repository import ControlPlaneRepository


HARD_BLOCKER_REASON_CODES = frozenset(
    {"all_remaining_stories_blocked", "progress_timeout"}
)


def run_epic_iteration(
    *,
    repo: str,
    epic_issue_number: int,
    repository: ControlPlaneRepository,
    story_runner: Callable[[ProgramStory], StoryRunResult],
    epic_verifier: Callable[..., dict[str, Any]] | None = None,
    story_batch_selector: Callable[..., list[ProgramStory]] = select_story_batch,
    max_parallel_stories: int = 1,
    now: datetime | None = None,
    progress_timeout: timedelta | None = None,
) -> EpicRunResult:
    effective_now = now or datetime.now(timezone.utc)
    previous_state = repository.get_epic_execution_state(
        repo=repo,
        epic_issue_number=epic_issue_number,
    )
    stories = repository.list_program_stories_for_epic(
        repo=repo,
        epic_issue_number=epic_issue_number,
    )
    if not stories:
        return _persist_epic_result(
            repository=repository,
            repo=repo,
            epic_issue_number=epic_issue_number,
            status="backlog",
            completed_story_issue_numbers=[],
            blocked_story_issue_numbers=[],
            remaining_story_issue_numbers=[],
            reason_code="epic_has_no_stories",
            operator_attention_required=False,
            previous_state=previous_state,
        )

    completed_story_issue_numbers: list[int] = []
    blocked_story_issue_numbers: list[int] = []
    remaining_story_issue_numbers: list[int] = []
    pending_stories: list[ProgramStory] = []

    for story in stories:
        if story.execution_status == "done":
            completed_story_issue_numbers.append(story.issue_number)
        elif story.execution_status == "blocked":
            blocked_story_issue_numbers.append(story.issue_number)
        else:
            pending_stories.append(story)

    if not pending_stories:
        verification_failure = _verify_epic_completion(
            repo=repo,
            epic_issue_number=epic_issue_number,
            completed_story_issue_numbers=completed_story_issue_numbers,
            effective_now=effective_now,
            epic_verifier=epic_verifier,
        )
        if verification_failure is not None:
            if hasattr(
                repository, "set_program_epic_execution_status_with_propagation"
            ):
                repository.set_program_epic_execution_status_with_propagation(
                    repo=repo,
                    issue_number=epic_issue_number,
                    execution_status="gated",
                )
            return _persist_epic_result(
                repository=repository,
                repo=repo,
                epic_issue_number=epic_issue_number,
                status="awaiting_operator",
                completed_story_issue_numbers=completed_story_issue_numbers,
                blocked_story_issue_numbers=blocked_story_issue_numbers,
                remaining_story_issue_numbers=[],
                reason_code=verification_failure["reason_code"],
                operator_attention_required=True,
                previous_state=previous_state,
                last_progress_at=effective_now,
                stalled_since=None,
                verification_status=verification_failure["verification_status"],
                verification_reason_code=verification_failure["reason_code"],
                last_verification_at=effective_now,
                verification_summary=verification_failure["summary"],
            )
        return _persist_epic_result(
            repository=repository,
            repo=repo,
            epic_issue_number=epic_issue_number,
            status="done",
            completed_story_issue_numbers=completed_story_issue_numbers,
            blocked_story_issue_numbers=blocked_story_issue_numbers,
            remaining_story_issue_numbers=[],
            reason_code="epic_complete",
            operator_attention_required=False,
            previous_state=previous_state,
            last_progress_at=effective_now,
            stalled_since=None,
            verification_status="passed",
            verification_reason_code=None,
            last_verification_at=effective_now,
            verification_summary="epic verification passed",
        )

    # Use story batch selector for all cases (including max_parallel_stories=1)
    selected_stories = story_batch_selector(
        stories=pending_stories,
        repository=repository,
        max_batch_size=max_parallel_stories,
    )
    if not selected_stories:
        degraded_batch_stories = story_batch_selector(
            stories=pending_stories,
            repository=repository,
            max_batch_size=1,
        )
        if degraded_batch_stories:
            selected_stories = degraded_batch_stories

    if not selected_stories:
        remaining_story_issue_numbers = sorted(
            story.issue_number for story in pending_stories
        )
        has_explicitly_blocked_stories = len(blocked_story_issue_numbers) > 0
        reason_code = (
            "all_remaining_stories_blocked"
            if has_explicitly_blocked_stories
            else "no_batch_safe_stories_available"
        )
        if not _is_hard_blocker_reason(reason_code):
            return _persist_epic_result(
                repository=repository,
                repo=repo,
                epic_issue_number=epic_issue_number,
                status="awaiting_operator",
                completed_story_issue_numbers=completed_story_issue_numbers,
                blocked_story_issue_numbers=blocked_story_issue_numbers,
                remaining_story_issue_numbers=remaining_story_issue_numbers,
                reason_code=reason_code,
                operator_attention_required=True,
                previous_state=previous_state,
                operator_request_opened_at=effective_now,
            )
        return _persist_epic_result(
            repository=repository,
            repo=repo,
            epic_issue_number=epic_issue_number,
            status="awaiting_operator",
            completed_story_issue_numbers=completed_story_issue_numbers,
            blocked_story_issue_numbers=blocked_story_issue_numbers,
            remaining_story_issue_numbers=remaining_story_issue_numbers,
            reason_code=reason_code,
            operator_attention_required=True,
            previous_state=previous_state,
            operator_request_opened_at=effective_now,
        )

    selected_story_issue_numbers = {story.issue_number for story in selected_stories}
    for story in selected_stories:
        result = story_runner(story)
        if result.story_complete:
            completed_story_issue_numbers.append(story.issue_number)
            continue
        blocked_story_issue_numbers.append(story.issue_number)
        remaining_story_issue_numbers.extend(
            pending_story.issue_number
            for pending_story in pending_stories
            if pending_story.issue_number not in completed_story_issue_numbers
            and pending_story.issue_number not in blocked_story_issue_numbers
        )
        return _persist_epic_result(
            repository=repository,
            repo=repo,
            epic_issue_number=epic_issue_number,
            status="awaiting_operator",
            completed_story_issue_numbers=completed_story_issue_numbers,
            blocked_story_issue_numbers=blocked_story_issue_numbers,
            remaining_story_issue_numbers=remaining_story_issue_numbers,
            reason_code="all_remaining_stories_blocked",
            operator_attention_required=True,
            previous_state=previous_state,
            operator_request_opened_at=effective_now,
        )

    remaining_story_issue_numbers = sorted(
        story.issue_number
        for story in pending_stories
        if story.issue_number not in selected_story_issue_numbers
    )
    if remaining_story_issue_numbers:
        last_progress_at, stalled_since = _derive_progress_timestamps(
            previous_state=previous_state,
            completed_story_issue_numbers=completed_story_issue_numbers,
            effective_now=effective_now,
        )
        if _is_progress_timed_out(
            stalled_since=stalled_since,
            progress_timeout=progress_timeout,
            effective_now=effective_now,
        ):
            return _persist_epic_result(
                repository=repository,
                repo=repo,
                epic_issue_number=epic_issue_number,
                status="awaiting_operator",
                completed_story_issue_numbers=completed_story_issue_numbers,
                blocked_story_issue_numbers=blocked_story_issue_numbers,
                remaining_story_issue_numbers=remaining_story_issue_numbers,
                reason_code="progress_timeout",
                operator_attention_required=True,
                last_progress_at=last_progress_at,
                stalled_since=stalled_since,
                operator_request_opened_at=effective_now,
            )
        return _persist_epic_result(
            repository=repository,
            repo=repo,
            epic_issue_number=epic_issue_number,
            status="active",
            completed_story_issue_numbers=completed_story_issue_numbers,
            blocked_story_issue_numbers=blocked_story_issue_numbers,
            remaining_story_issue_numbers=remaining_story_issue_numbers,
            reason_code="epic_incomplete",
            operator_attention_required=False,
            last_progress_at=last_progress_at,
            stalled_since=stalled_since,
        )

    verification_failure = _verify_epic_completion(
        repo=repo,
        epic_issue_number=epic_issue_number,
        completed_story_issue_numbers=completed_story_issue_numbers,
        effective_now=effective_now,
        epic_verifier=epic_verifier,
    )
    if verification_failure is not None:
        return _persist_epic_result(
            repository=repository,
            repo=repo,
            epic_issue_number=epic_issue_number,
            status="awaiting_operator",
            completed_story_issue_numbers=completed_story_issue_numbers,
            blocked_story_issue_numbers=blocked_story_issue_numbers,
            remaining_story_issue_numbers=remaining_story_issue_numbers,
            reason_code=verification_failure["reason_code"],
            operator_attention_required=True,
            last_progress_at=effective_now,
            stalled_since=None,
            verification_status=verification_failure["verification_status"],
            verification_reason_code=verification_failure["reason_code"],
            last_verification_at=effective_now,
            verification_summary=verification_failure["summary"],
        )

    return _persist_epic_result(
        repository=repository,
        repo=repo,
        epic_issue_number=epic_issue_number,
        status="done",
        completed_story_issue_numbers=completed_story_issue_numbers,
        blocked_story_issue_numbers=blocked_story_issue_numbers,
        remaining_story_issue_numbers=remaining_story_issue_numbers,
        reason_code="epic_complete",
        operator_attention_required=False,
        last_progress_at=effective_now,
        stalled_since=None,
        verification_status="passed",
        verification_reason_code=None,
        last_verification_at=effective_now,
        verification_summary="epic verification passed",
    )


def run_epic_until_settled(
    *,
    repo: str,
    epic_issue_number: int,
    repository: ControlPlaneRepository,
    story_runner: Callable[[ProgramStory], StoryRunResult],
    epic_verifier: Callable[..., dict[str, Any]] | None = None,
    story_batch_selector: Callable[..., list[ProgramStory]] = select_story_batch,
    max_parallel_stories: int = 1,
    now: datetime | None = None,
    progress_timeout: timedelta | None = None,
) -> EpicRunResult:
    return run_epic_iteration(
        repo=repo,
        epic_issue_number=epic_issue_number,
        repository=repository,
        story_runner=story_runner,
        epic_verifier=epic_verifier,
        story_batch_selector=story_batch_selector,
        max_parallel_stories=max_parallel_stories,
        now=now,
        progress_timeout=progress_timeout,
    )


def _persist_epic_result(
    *,
    repository: ControlPlaneRepository,
    repo: str,
    epic_issue_number: int,
    status: EpicRuntimeStatus,
    completed_story_issue_numbers: list[int],
    blocked_story_issue_numbers: list[int],
    remaining_story_issue_numbers: list[int],
    reason_code: str,
    operator_attention_required: bool,
    previous_state: EpicExecutionState | None = None,
    last_progress_at: datetime | None = None,
    stalled_since: datetime | None = None,
    operator_request_opened_at: datetime | None = None,
    verification_status: str | None = None,
    verification_reason_code: str | None = None,
    last_verification_at: datetime | None = None,
    verification_summary: str | None = None,
) -> EpicRunResult:
    sorted_completed_story_issue_numbers = sorted(completed_story_issue_numbers)
    sorted_blocked_story_issue_numbers = sorted(blocked_story_issue_numbers)
    sorted_remaining_story_issue_numbers = sorted(remaining_story_issue_numbers)
    if last_progress_at is None:
        last_progress_at = (
            previous_state.last_progress_at if previous_state is not None else None
        )
    if stalled_since is None:
        stalled_since = (
            previous_state.stalled_since if previous_state is not None else None
        )

    repository.upsert_epic_execution_state(
        EpicExecutionState(
            repo=repo,
            epic_issue_number=epic_issue_number,
            status=status,
            completed_story_issue_numbers=tuple(sorted_completed_story_issue_numbers),
            blocked_story_issue_numbers=tuple(sorted_blocked_story_issue_numbers),
            remaining_story_issue_numbers=tuple(sorted_remaining_story_issue_numbers),
            blocked_reason_code=reason_code,
            operator_attention_required=operator_attention_required,
            last_progress_at=last_progress_at,
            stalled_since=stalled_since,
            verification_status=verification_status,
            verification_reason_code=verification_reason_code,
            last_verification_at=last_verification_at,
            verification_summary=verification_summary,
        )
    )
    if operator_request_opened_at is not None:
        _record_operator_request(
            repository=repository,
            repo=repo,
            epic_issue_number=epic_issue_number,
            reason_code=reason_code,
            remaining_story_issue_numbers=sorted_remaining_story_issue_numbers,
            blocked_story_issue_numbers=sorted_blocked_story_issue_numbers,
            opened_at=operator_request_opened_at,
        )
    return EpicRunResult(
        epic_issue_number=epic_issue_number,
        completed_story_issue_numbers=sorted_completed_story_issue_numbers,
        blocked_story_issue_numbers=sorted_blocked_story_issue_numbers,
        remaining_story_issue_numbers=sorted_remaining_story_issue_numbers,
        epic_complete=(
            status == "done"
            and len(sorted_blocked_story_issue_numbers) == 0
            and len(sorted_remaining_story_issue_numbers) == 0
        ),
        reason_code=reason_code,
    )


def _verify_epic_completion(
    *,
    repo: str,
    epic_issue_number: int,
    completed_story_issue_numbers: list[int],
    effective_now: datetime,
    epic_verifier: Callable[..., dict[str, Any]] | None,
) -> dict[str, str] | None:
    if epic_verifier is None:
        return None
    result = epic_verifier(
        repo=repo,
        epic_issue_number=epic_issue_number,
        completed_story_issue_numbers=tuple(sorted(completed_story_issue_numbers)),
        now=effective_now,
    )
    if result.get("passed"):
        return None
    return {
        "verification_status": "failed",
        "reason_code": str(result.get("reason_code") or "epic_verification_failed"),
        "summary": str(result.get("summary") or "epic verification failed"),
    }


def _derive_progress_timestamps(
    *,
    previous_state: EpicExecutionState | None,
    completed_story_issue_numbers: list[int],
    effective_now: datetime,
) -> tuple[datetime | None, datetime | None]:
    previous_completed_count = (
        len(previous_state.completed_story_issue_numbers)
        if previous_state is not None
        else 0
    )
    current_completed_count = len(completed_story_issue_numbers)
    if current_completed_count > previous_completed_count:
        return effective_now, None
    if previous_state is None:
        return None, effective_now
    return (
        previous_state.last_progress_at,
        previous_state.stalled_since or effective_now,
    )


def _is_progress_timed_out(
    *,
    stalled_since: datetime | None,
    progress_timeout: timedelta | None,
    effective_now: datetime,
) -> bool:
    if progress_timeout is None or stalled_since is None:
        return False
    return effective_now - stalled_since > progress_timeout


def _record_operator_request(
    *,
    repository: ControlPlaneRepository,
    repo: str,
    epic_issue_number: int,
    reason_code: str,
    remaining_story_issue_numbers: list[int],
    blocked_story_issue_numbers: list[int],
    opened_at: datetime,
) -> None:
    repository.record_operator_request(
        OperatorRequest(
            repo=repo,
            epic_issue_number=epic_issue_number,
            reason_code=reason_code,
            summary=_build_operator_request_summary(
                epic_issue_number=epic_issue_number,
                reason_code=reason_code,
                remaining_story_issue_numbers=remaining_story_issue_numbers,
                blocked_story_issue_numbers=blocked_story_issue_numbers,
            ),
            remaining_story_issue_numbers=tuple(remaining_story_issue_numbers),
            blocked_story_issue_numbers=tuple(blocked_story_issue_numbers),
            status="open",
            opened_at=opened_at,
        )
    )


def _is_hard_blocker_reason(reason_code: str) -> bool:
    return reason_code in HARD_BLOCKER_REASON_CODES


def _build_operator_request_summary(
    *,
    epic_issue_number: int,
    reason_code: str,
    remaining_story_issue_numbers: list[int],
    blocked_story_issue_numbers: list[int],
) -> str:
    remaining_count = len(remaining_story_issue_numbers)
    blocked_count = len(blocked_story_issue_numbers)
    prefix = f"Epic #{epic_issue_number} needs operator attention:"
    if reason_code == "all_remaining_stories_blocked":
        blocked_verb = "is" if blocked_count == 1 else "are"
        return (
            f"{prefix} {blocked_count} blocked {_pluralize('story', blocked_count)} "
            f"{blocked_verb} preventing the remaining {remaining_count} {_pluralize('story', remaining_count)} from safely running."
        )
    if reason_code == "no_batch_safe_stories_available":
        return (
            f"{prefix} no safe story batch is available while {remaining_count} "
            f"{_pluralize('story', remaining_count)} remain pending."
        )
    if reason_code == "progress_timeout":
        return (
            f"{prefix} progress timed out with {remaining_count} "
            f"remaining {_pluralize('story', remaining_count)}."
        )
    return f"{prefix} {reason_code}."


def _pluralize(noun: str, count: int) -> str:
    if count == 1:
        return noun
    if noun.endswith("y"):
        return f"{noun[:-1]}ies"
    return f"{noun}s"
