from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence

from .operator_request_ack_cli import main as operator_request_ack_main
from .operator_request_cli import main as operator_request_list_main
from .operator_request_report_cli import main as operator_request_report_main


def main(
    argv: Sequence[str] | None = None,
    *,
    list_main: Callable[[Sequence[str] | None], int] = operator_request_list_main,
    ack_main: Callable[[Sequence[str] | None], int] = operator_request_ack_main,
    report_main: Callable[[Sequence[str] | None], int] = operator_request_report_main,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    command_argv = list(args.args)
    if args.command == "list":
        return list_main(command_argv)
    if args.command == "ack":
        return ack_main(command_argv)
    return report_main(command_argv)


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stardrifter-orchestration-operator",
        description="Dispatch operator request commands through one unified entrypoint.",
    )
    parser.add_argument("command", choices=("list", "ack", "report"))
    parser.add_argument("args", nargs=argparse.REMAINDER)
    return parser


if __name__ == "__main__":
    entrypoint()
