from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from .factory import build_postgres_repository
from .settings import load_postgres_settings_from_env
from .shadow_capture import ShadowCaptureResult, capture_shadow_command


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_builder: Callable[..., object] = build_postgres_repository,
    capture_runner: Callable[..., ShadowCaptureResult] = capture_shadow_command,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("shadow command is required after --")

    result = capture_runner(
        repository=repository,
        repo=args.repo,
        title=args.title,
        workdir=args.workdir,
        command=command,
        prompt=args.prompt,
        assistant_summary=args.assistant_summary,
        transcript_text=_load_transcript_text(args.transcript_file),
        transcript_path=(
            str(Path(args.transcript_file).resolve())
            if args.transcript_file
            else None
        ),
        worker_name=f"shadow-wrap:{args.executor}",
        dsn=settings.dsn,
    )
    print(f"captured {result.work_id} -> {result.status}")
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskplane-wrap",
        description="Capture an external AI command into Taskplane without changing the existing workflow.",
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--prompt")
    parser.add_argument("--assistant-summary")
    parser.add_argument("--transcript-file")
    parser.add_argument("--executor", default="external")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def _load_transcript_text(path: str | None) -> str | None:
    if not path:
        return None
    return Path(path).resolve().read_text(encoding="utf-8")


if __name__ == "__main__":
    entrypoint()
