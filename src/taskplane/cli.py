from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
import shutil

from .adapters import build_task_executor, build_task_verifier
from .factory import build_postgres_repository
from .git_committer import build_git_committer
from .models import ExecutionGuardrailContext, VerificationEvidence, WorkItem
from .protocols import ExecutorAdapter, VerifierAdapter
from .settings import load_postgres_settings_from_env
from .worker import ExecutionResult, WorkerCycleResult, run_worker_cycle
from .workspace import WorkspaceManager

DEFAULT_VERIFIER_COMMAND = "python3 -m taskplane.task_verifier"


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_builder: Callable[..., object] = build_postgres_repository,
    cycle_runner: Callable[..., WorkerCycleResult] = run_worker_cycle,
    executor_builder: Callable[..., ExecutorAdapter] = build_task_executor,
    verifier_builder: Callable[..., VerifierAdapter] = build_task_verifier,
    committer_builder: Callable[..., object] = build_git_committer,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    frozen_prefixes = tuple(args.frozen_prefix) or ("docs/authority/",)
    workdir = Path(args.workdir).resolve()
    verifier_command = args.verifier_command or DEFAULT_VERIFIER_COMMAND
    _run_cli_preflight(
        workdir=workdir,
        executor_command=args.executor_command,
        verifier_command=verifier_command,
        worktree_root=Path(args.worktree_root).resolve()
        if args.worktree_root
        else None,
    )
    repository = repository_builder(dsn=settings.dsn)
    context = ExecutionGuardrailContext(
        allowed_waves=set(args.allowed_wave),
        frozen_prefixes=frozen_prefixes,
    )
    executor = _default_executor
    if args.executor_command:
        executor = executor_builder(
            command_template=args.executor_command,
            workdir=workdir,
            dsn=settings.dsn,
        )
    verifier = verifier_builder(
        command_template=verifier_command,
        workdir=workdir,
        check_type=args.verifier_check_type,
    )
    committer = committer_builder(workdir=workdir)
    workspace_manager = None
    if args.worktree_root:
        workspace_manager = WorkspaceManager(
            repo_root=workdir,
            worktree_root=Path(args.worktree_root).resolve(),
        )

    result = cycle_runner(
        repository=repository,
        context=context,
        worker_name=args.worker_name,
        executor=executor,
        verifier=verifier,
        committer=committer,
        work_item_ids=args.work_item_id or None,
        workspace_manager=workspace_manager,
        dsn=settings.dsn,
    )
    if result.claimed_work_id is None:
        print("no runnable task")
        return 0

    print(f"claimed {result.claimed_work_id}")
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskplane-worker",
        description="Run one orchestration worker cycle against the PostgreSQL control plane.",
    )
    parser.add_argument("--worker-name", default="cli-worker")
    parser.add_argument("--allowed-wave", action="append", default=[])
    parser.add_argument("--frozen-prefix", action="append", default=[])
    parser.add_argument("--workdir", default=".")
    parser.add_argument("--worktree-root")
    parser.add_argument("--work-item-id", action="append", default=[])
    parser.add_argument("--executor-command")
    parser.add_argument("--verifier-command")
    parser.add_argument("--verifier-check-type", default="pytest")
    return parser


def _default_executor(work_item: WorkItem, workspace_path=None) -> ExecutionResult:
    return ExecutionResult(
        success=True,
        summary=f"noop executor for {work_item.id}",
        command_digest="noop-executor",
    )


def _default_verifier(work_item: WorkItem, workspace_path=None) -> VerificationEvidence:
    return VerificationEvidence(
        work_id=work_item.id,
        check_type="noop",
        command="noop-verify",
        passed=True,
        output_digest=f"verification skipped for {work_item.id}",
        exit_code=0,
        elapsed_ms=0,
        stdout_digest="",
        stderr_digest="",
    )


def _run_cli_preflight(
    *,
    workdir: Path,
    executor_command: str | None,
    verifier_command: str | None,
    worktree_root: Path | None,
) -> None:
    if not workdir.exists() or not workdir.is_dir():
        raise SystemExit(f"workdir does not exist: {workdir}")
    if executor_command is not None and not _is_virtual_llm_command(executor_command):
        _require_command_binary(executor_command, label="executor")
    if verifier_command is not None and not _is_virtual_llm_command(verifier_command):
        _require_command_binary(verifier_command, label="verifier")
    if worktree_root is not None:
        _validate_worktree_root(worktree_root)


def _require_command_binary(command: str, *, label: str) -> None:
    binary = command.strip().split(maxsplit=1)[0]
    if not binary or shutil.which(binary) is None:
        raise SystemExit(f"{label} command not found: {binary or command}")


def _validate_worktree_root(worktree_root: Path) -> None:
    for parent in [worktree_root, *worktree_root.parents]:
        if parent.exists():
            if not parent.is_dir():
                raise SystemExit(
                    f"worktree root is not under a writable directory tree: {worktree_root}"
                )
            return


def _is_virtual_llm_command(command: str) -> bool:
    return command.strip().lower().startswith("llm://")


if __name__ == "__main__":
    entrypoint()
