from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

from .scheduling_loop import run_supervisor_iteration
from .settings import TaskplaneConfig, load_taskplane_config, resolve_config_path

CORE_MIGRATIONS = (
    "control_plane_schema.sql",
    "001_parallel_execution_extensions.sql",
    "002_global_coordination.sql",
    "003_ui_enhancements.sql",
    "004_artifact_store.sql",
    "005_dlq_and_observability.sql",
    "006_executor_routing_profiles.sql",
    "008_repo_registry.sql",
    "009_orchestrator_session.sql",
)


def main(
    argv: Sequence[str] | None = None,
    *,
    config_loader: Callable[[], TaskplaneConfig] = load_taskplane_config,
    command_runner: Callable[[list[str]], None] | None = None,
    migration_runner: Callable[..., None] | None = None,
    psql_resolver: Callable[[], str | None] | None = None,
    connection_factory: Callable[[str], Any] | None = None,
    supervisor_iteration_runner: Callable[..., int] = run_supervisor_iteration,
    project_root: Path | None = None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command not in {"up", "supervise"}:
        parser.error("a subcommand is required")

    config = config_loader()
    if not config.postgres_dsn:
        raise SystemExit(
            "TASKPLANE_DSN is required (or set [postgres].dsn in taskplane.toml)"
        )

    root = _resolve_project_root(config=config, project_root=project_root)
    runner = command_runner or _run_command
    sql_runner = migration_runner or _apply_sql_via_psycopg
    psql_lookup = psql_resolver or _resolve_psql_binary

    if args.command == "supervise":
        return _run_supervise_command(
            args=args,
            config=config,
            root=root,
            connection_factory=connection_factory or _connect_with_dict_rows,
            supervisor_iteration_runner=supervisor_iteration_runner,
        )

    if not args.skip_compose:
        compose_file = resolve_config_path(
            config.dev_compose_file,
            source_path=config.source_path,
        )
        env_file = resolve_config_path(
            config.dev_env_file,
            source_path=config.source_path,
        )
        runner(
            [
                "docker",
                "compose",
                "--env-file",
                str(env_file),
                "-f",
                str(compose_file),
                "up",
                "-d",
            ]
        )

    psql_binary = psql_lookup()
    for migration in CORE_MIGRATIONS:
        sql_file = root / "sql" / migration
        if psql_binary:
            runner(
                [
                    "psql",
                    config.postgres_dsn,
                    "-f",
                    str(sql_file),
                ]
            )
        else:
            sql_runner(dsn=config.postgres_dsn, sql_file=sql_file)

    print("taskplane dev up finished")
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskplane-dev",
        description="Bootstrap local Taskplane development services.",
    )
    subparsers = parser.add_subparsers(dest="command")
    up_parser = subparsers.add_parser(
        "up",
        help="Start local services and apply core migrations.",
    )
    up_parser.add_argument(
        "--skip-compose",
        action="store_true",
        help="Apply migrations only, without starting docker compose",
    )
    supervise_parser = subparsers.add_parser(
        "supervise",
        help="Run supervisor using repo mappings from taskplane.toml.",
    )
    supervise_parser.add_argument("--repo", required=True)
    supervise_parser.add_argument("--once", action="store_true")
    supervise_parser.add_argument("--poll-interval", type=int, default=15)
    supervise_parser.add_argument("--max-parallel-jobs", type=int, default=2)
    supervise_parser.add_argument("--epic-story-batch-size", type=int, default=1)
    supervise_parser.add_argument("--worktree-root")
    supervise_parser.add_argument("--promotion-repo-root")
    supervise_parser.add_argument("--story-executor-command")
    supervise_parser.add_argument("--story-verifier-command")
    supervise_parser.add_argument(
        "--story-force-shell-executor",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    return parser


def _resolve_project_root(
    *, config: TaskplaneConfig, project_root: Path | None
) -> Path:
    if project_root is not None:
        return project_root.resolve()
    if config.source_path is not None:
        return config.source_path.parent.resolve()
    return Path.cwd().resolve()


def _run_command(command: list[str]) -> None:
    subprocess.run(command, check=True)


def _resolve_psql_binary() -> str | None:
    return shutil.which("psql")


def _apply_sql_via_psycopg(*, dsn: str, sql_file: Path) -> None:
    import psycopg

    sql_text = sql_file.read_text(encoding="utf-8")
    with psycopg.connect(dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(cast(Any, sql_text))


def _connect_with_dict_rows(dsn: str):
    connect = cast(Any, psycopg.connect)
    return connect(dsn, row_factory=dict_row)


def _run_supervise_command(
    *,
    args: argparse.Namespace,
    config: TaskplaneConfig,
    root: Path,
    connection_factory: Callable[[str], Any],
    supervisor_iteration_runner: Callable[..., int],
) -> int:
    repo = str(args.repo).strip()
    if not repo:
        raise SystemExit("--repo is required")

    project_dir = _resolve_repo_mapping(
        mapping=config.console_repo_workdirs,
        repo=repo,
        source_path=config.source_path,
        label="console.repo_workdirs",
    )
    log_dir = _resolve_repo_mapping(
        mapping=config.console_repo_log_dirs,
        repo=repo,
        source_path=config.source_path,
        label="console.repo_log_dirs",
    )
    log_dir.mkdir(parents=True, exist_ok=True)

    worktree_root = (
        resolve_config_path(args.worktree_root, source_path=config.source_path)
        if args.worktree_root
        else (project_dir / ".taskplane" / "worktrees").resolve()
    )
    promotion_repo_root = (
        resolve_config_path(args.promotion_repo_root, source_path=config.source_path)
        if args.promotion_repo_root
        else None
    )

    while True:
        with connection_factory(config.postgres_dsn) as connection:
            launched = supervisor_iteration_runner(
                connection=connection,
                repo=repo,
                dsn=config.postgres_dsn,
                project_dir=project_dir,
                log_dir=log_dir,
                worktree_root=worktree_root,
                promotion_repo_root=promotion_repo_root,
                max_parallel_jobs=args.max_parallel_jobs,
                epic_story_batch_size=args.epic_story_batch_size,
                launcher=_launch_managed_process,
                story_executor_command=(
                    args.story_executor_command
                    or config.supervisor_repo_story_executor_commands.get(repo)
                ),
                story_verifier_command=(
                    args.story_verifier_command
                    or config.supervisor_repo_story_verifier_commands.get(repo)
                ),
                story_force_shell_executor=(
                    args.story_force_shell_executor
                    if args.story_force_shell_executor is not None
                    else config.supervisor_repo_story_force_shell_executor.get(repo)
                ),
            )
        if args.once:
            print(f"taskplane supervise launched={launched}")
            return 0
        if launched == 0:
            time.sleep(args.poll_interval)


def _resolve_repo_mapping(
    *,
    mapping: dict[str, str],
    repo: str,
    source_path: Path | None,
    label: str,
) -> Path:
    raw = str(mapping.get(repo, "")).strip()
    if not raw:
        raise SystemExit(f"{label} missing repo mapping: {repo}")
    return resolve_config_path(raw, source_path=source_path)


def _launch_managed_process(command: str, log_path: Path):
    from .process_manager import launch_managed_process

    return launch_managed_process(command, log_path)
