from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .adapters import build_task_executor, build_task_verifier
from .cli import DEFAULT_VERIFIER_COMMAND, _default_executor
from .factory import build_postgres_repository
from .git_committer import build_git_committer, build_git_story_integrator
from .models import ExecutionGuardrailContext, VerificationEvidence, WorkItem
from .settings import load_postgres_settings_from_env
from .story_runner import load_story_work_item_ids, run_story_until_settled
from .worker import ExecutionResult
from .workspace import WorkspaceManager


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_builder: Callable[..., Any] = build_postgres_repository,
    story_loader: Callable[..., list[str]] = load_story_work_item_ids,
    story_runner: Callable[..., Any] = run_story_until_settled,
    executor_builder: Callable[
        ..., Callable[[WorkItem], ExecutionResult]
    ] = build_task_executor,
    verifier_builder: Callable[
        ..., Callable[[WorkItem], VerificationEvidence]
    ] = build_task_verifier,
    story_verifier_builder: Callable[..., object] = build_task_verifier,
    committer_builder: Callable[..., object] = build_git_committer,
    story_integrator_builder: Callable[..., object] = build_git_story_integrator,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)
    context = ExecutionGuardrailContext(
        allowed_waves=set(args.allowed_wave),
        frozen_prefixes=tuple(args.frozen_prefix) or ("docs/authority/",),
    )
    workdir = Path(args.workdir).resolve()
    workspace_manager = None
    if args.worktree_root:
        workspace_manager = WorkspaceManager(
            repo_root=workdir,
            worktree_root=Path(args.worktree_root).resolve(),
        )
    executor = _default_executor
    if args.executor_command:
        executor = executor_builder(
            command_template=args.executor_command,
            workdir=workdir,
        )
    verifier_command = args.verifier_command or DEFAULT_VERIFIER_COMMAND
    verifier = verifier_builder(
        command_template=verifier_command,
        workdir=workdir,
        check_type=args.verifier_check_type,
    )
    committer = committer_builder(workdir=workdir)
    story_verifier = None
    if args.story_verifier_command:
        story_verifier = story_verifier_builder(
            command_template=args.story_verifier_command,
            workdir=workdir,
            check_type=args.story_verifier_check_type,
        )
    story_integrator = None
    if args.worktree_root:
        ignored_dirty_path_prefixes = _relative_ignored_prefixes(
            repo_root=workdir,
            candidate_path=Path(args.worktree_root).resolve(),
        )
        promotion_repo_root = (
            Path(args.promotion_repo_root).resolve()
            if args.promotion_repo_root
            else None
        )
        story_integrator = story_integrator_builder(
            repo_root=workdir,
            ignored_dirty_path_prefixes=ignored_dirty_path_prefixes,
            promotion_repo_root=promotion_repo_root,
        )
    story_work_item_ids = story_loader(
        repository=repository,
        story_issue_number=args.story_issue_number,
    )
    result = story_runner(
        story_issue_number=args.story_issue_number,
        story_work_item_ids=story_work_item_ids,
        repository=repository,
        context=context,
        worker_name=args.worker_name,
        executor=executor,
        verifier=verifier,
        story_verifier=story_verifier,
        committer=committer,
        story_integrator=story_integrator,
        workspace_manager=workspace_manager,
    )
    if result.story_complete:
        print(f"story {args.story_issue_number} complete")
    else:
        merge_hint = (
            f" merge_blocked={result.merge_blocked_reason}"
            if result.merge_blocked_reason
            else ""
        )
        print(
            f"story {args.story_issue_number} incomplete; "
            f"blocked={len(result.blocked_work_item_ids)} "
            f"remaining={len(result.remaining_work_item_ids)}"
            f"{merge_hint}"
        )
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stardrifter-orchestration-story",
        description="Drain all projected work items under a story until completion or blockage.",
    )
    parser.add_argument("--story-issue-number", type=int, required=True)
    parser.add_argument("--worker-name", default="story-runner")
    parser.add_argument("--allowed-wave", action="append", default=[])
    parser.add_argument("--frozen-prefix", action="append", default=[])
    parser.add_argument("--workdir", default=".")
    parser.add_argument("--worktree-root")
    parser.add_argument("--promotion-repo-root")
    parser.add_argument("--executor-command")
    parser.add_argument("--verifier-command")
    parser.add_argument("--verifier-check-type", default="pytest")
    parser.add_argument("--story-verifier-command")
    parser.add_argument("--story-verifier-check-type", default="pytest")
    return parser


def _relative_ignored_prefixes(
    *, repo_root: Path, candidate_path: Path
) -> tuple[str, ...]:
    try:
        relative = candidate_path.relative_to(repo_root)
    except ValueError:
        return ()
    relative_text = str(relative).strip()
    if not relative_text:
        return ()
    return (relative_text.rstrip("/") + "/",)


if __name__ == "__main__":
    entrypoint()
