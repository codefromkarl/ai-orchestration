from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
import shutil
from typing import Any

from .settings import TaskplaneConfig, load_taskplane_config, resolve_config_path


def main(
    argv: Sequence[str] | None = None,
    *,
    config_loader: Callable[[], TaskplaneConfig] = load_taskplane_config,
    which: Callable[[str], str | None] = shutil.which,
    connector: Callable[[str], Any] | None = None,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    failures = 0
    try:
        config = config_loader()
    except RuntimeError as exc:
        print(f"[fail] config: {exc}")
        return 1

    if config.source_path is not None:
        print(f"[ok] config: {config.source_path}")
    else:
        print("[warn] config: taskplane.toml not found, using environment/defaults")

    if config.postgres_dsn:
        print("[ok] postgres: dsn configured")
    else:
        print("[fail] postgres: missing DSN")
        failures += 1

    for binary in ("docker", "psql", "gh", "node", "npm"):
        location = which(binary)
        if location:
            print(f"[ok] command:{binary}: {location}")
        else:
            print(f"[warn] command:{binary}: not found")

    if args.repo:
        if args.repo in config.console_repo_workdirs and args.repo in config.console_repo_log_dirs:
            print(f"[ok] console repo: {args.repo}")
            workdir = resolve_config_path(
                config.console_repo_workdirs[args.repo],
                source_path=config.source_path,
            )
            log_dir = resolve_config_path(
                config.console_repo_log_dirs[args.repo],
                source_path=config.source_path,
            )
            if not workdir.exists():
                print(f"[warn] workdir: missing path {workdir}")
            if not log_dir.exists():
                print(f"[warn] log dir: missing path {log_dir}")
        else:
            print(f"[fail] console repo: missing workdir/log-dir mapping for {args.repo}")
            failures += 1

    if not args.skip_db and config.postgres_dsn:
        if _check_db_connection(config.postgres_dsn, connector=connector):
            print("[ok] db: connection succeeded")
        else:
            print("[fail] db: connection failed")
            failures += 1

    return 1 if failures else 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskplane-doctor",
        description="Inspect local Taskplane configuration and dependencies.",
    )
    parser.add_argument("--repo", help="Check console mappings for a specific repo")
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Skip live PostgreSQL connection test",
    )
    return parser


def _check_db_connection(
    dsn: str,
    *,
    connector: Callable[[str], Any] | None,
) -> bool:
    try:
        connection_factory = connector or _default_connector
        connection = connection_factory(dsn)
    except Exception:
        return False

    close = getattr(connection, "close", None)
    if callable(close):
        close()
    return True


def _default_connector(dsn: str) -> Any:
    import psycopg

    return psycopg.connect(dsn)
