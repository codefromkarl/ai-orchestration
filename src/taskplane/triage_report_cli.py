from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from typing import Any

from .factory import build_postgres_repository
from .models import TriageReport
from .projection_sync import (
    _load_completion_audit,
    _load_normalized_issues,
    _load_relation_candidates,
    load_projection_from_staging,
)
from .settings import load_postgres_settings_from_env
from .triage_report import build_triage_report


def main(
    argv: Sequence[str] | None = None,
    *,
    repository_builder: Callable[..., Any] = build_postgres_repository,
    staging_loader: Callable[..., dict[str, Any]] | None = None,
    report_builder: Callable[..., TriageReport] = build_triage_report,
) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    settings = load_postgres_settings_from_env()
    repository = repository_builder(dsn=settings.dsn)
    connection = getattr(repository, "_connection", repository)

    if staging_loader is None:
        staging_payload = _load_staging_payload(connection=connection, repo=args.repo)
    else:
        staging_payload = staging_loader(connection=connection, repo=args.repo)

    report = report_builder(
        issues=staging_payload["issues"],
        relations=staging_payload["relations"],
        completion_audit=staging_payload["completion_audit"],
        projection=staging_payload["projection"],
    )
    print(
        f"repo={args.repo} "
        f"unprojected_tasks={len(report.unprojected_task_issue_numbers)} "
        f"stories_without_projected_tasks={len(report.storys_without_projected_tasks)}"
    )
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskplane-triage",
        description="Report why imported issues did not project cleanly into executable work items.",
    )
    parser.add_argument("--repo", required=True)
    return parser


def _load_staging_payload(*, connection: Any, repo: str) -> dict[str, Any]:
    issues = _load_normalized_issues(connection=connection, repo=repo)
    relations = _load_relation_candidates(connection=connection, repo=repo)
    completion_audit = _load_completion_audit(connection=connection, repo=repo)
    projection = load_projection_from_staging(connection=connection, repo=repo)
    return {
        "issues": issues,
        "relations": relations,
        "completion_audit": completion_audit,
        "projection": projection,
    }


if __name__ == "__main__":
    entrypoint()
