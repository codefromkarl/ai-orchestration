#!/usr/bin/env python
"""
Web UI Server for Taskplane Console

Usage:
    python -m taskplane.web_ui_server \
        --dsn postgresql://user:pass@localhost/db \
        --host 0.0.0.0 \
        --port 8000
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import uvicorn

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from taskplane.hierarchy_api import app


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Taskplane Web UI Server"
    )
    parser.add_argument(
        "--dsn",
        type=str,
        default=os.getenv("TASKPLANE_DSN", ""),
        help="PostgreSQL DSN (default: $TASKPLANE_DSN)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to (default: 8000)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )

    args = parser.parse_args()

    if not args.dsn:
        print("Error: --dsn is required or set TASKPLANE_DSN")
        sys.exit(1)

    # Set environment variable for the app
    os.environ["TASKPLANE_DSN"] = args.dsn

    print(f"Starting Taskplane Web UI")
    print(f"  DSN: {args.dsn[:20]}...")
    print(f"  Host: {args.host}")
    print(f"  Port: {args.port}")
    print()
    print(f"Access the console at: http://{args.host}:{args.port}/console")
    print()

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
