from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .eval_ci_thresholds import build_default_ci_threshold_profile
from .eval_smoke_suites import build_default_smoke_suite_manifest


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    if args.kind == "smoke-suite":
        payload = build_default_smoke_suite_manifest()
    else:
        payload = build_default_ci_threshold_profile()
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskplane-eval-contract",
        description="Export built-in smoke suite and threshold contracts as JSON.",
    )
    parser.add_argument(
        "--kind",
        required=True,
        choices=("smoke-suite", "threshold-profile"),
    )
    return parser


if __name__ == "__main__":
    entrypoint()
