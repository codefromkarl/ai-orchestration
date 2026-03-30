from __future__ import annotations

import argparse
from collections.abc import Sequence
import os


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stardrifter-orchestration-ui",
        description="Start the Issue Hierarchy web UI server.",
    )
    parser.add_argument(
        "--dsn",
        default=os.getenv("STARDRIFTER_ORCHESTRATION_DSN", ""),
        help="PostgreSQL DSN (default: $STARDRIFTER_ORCHESTRATION_DSN)",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Bind port (default: 8000)"
    )
    parser.add_argument(
        "--reload", action="store_true", help="Enable auto-reload (dev mode)"
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.dsn:
        raise SystemExit("STARDRIFTER_ORCHESTRATION_DSN is required (or pass --dsn)")

    os.environ["STARDRIFTER_ORCHESTRATION_DSN"] = args.dsn

    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("uvicorn is required: pip install uvicorn[standard]") from exc

    uvicorn.run(
        "stardrifter_orchestration_mvp.hierarchy_api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
