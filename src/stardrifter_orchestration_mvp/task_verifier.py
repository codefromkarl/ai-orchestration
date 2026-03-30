from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

import psycopg
from psycopg.rows import dict_row


SECTION_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
PATH_RE = re.compile(r"([A-Za-z0-9_./-]+\.(?:py|sh|md|gd|tscn))")
COMMAND_RE = re.compile(r"`([^`]+)`")


def main() -> int:
    work_id = os.environ.get("STARDRIFTER_WORK_ID", "").strip()
    dsn = os.environ.get("STARDRIFTER_ORCHESTRATION_DSN", "").strip()
    project_dir = Path(
        os.environ.get("STARDRIFTER_PROJECT_DIR") or Path.cwd()
    ).resolve()
    if not work_id:
        raise SystemExit("STARDRIFTER_WORK_ID is required")
    if not dsn:
        raise SystemExit("STARDRIFTER_ORCHESTRATION_DSN is required")

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT wi.title, gin.body
                FROM work_item wi
                LEFT JOIN github_issue_normalized gin
                  ON gin.repo = %s AND gin.issue_number = wi.source_issue_number
                WHERE wi.id = %s
                """,
                ("codefromkarl/stardrifter", work_id),
            )
            row = cur.fetchone()
    if row is None:
        raise SystemExit(f"work item not found: {work_id}")

    title = row["title"]
    body = row.get("body") or ""
    commands = _resolve_verification_commands(
        title=title,
        body=body,
        project_dir=project_dir,
    )
    if not commands:
        print("doc/process verification: noop")
        return 0

    last_returncode = 0
    env = _build_verifier_env(project_dir)
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=str(project_dir),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr)
        last_returncode = completed.returncode
        if completed.returncode != 0:
            return completed.returncode
    return last_returncode


def _resolve_verification_commands(
    *,
    title: str,
    body: str,
    project_dir: Path,
) -> list[list[str]]:
    if "-DOC]" in title or title.startswith("[PROCESS]"):
        return []
    explicit_commands = _extract_explicit_commands(body)
    if explicit_commands:
        return explicit_commands
    pytest_targets = _extract_pytest_targets(body=body, project_dir=project_dir)
    if pytest_targets:
        return [["python3", "-m", "pytest", "-q", *pytest_targets]]
    if _should_treat_as_implementation_only_with_external_test_ownership(body=body):
        return []
    if _should_treat_as_read_only_verification(body=body):
        return []
    return [["python3", "-m", "pytest", "-q"]]


def _extract_explicit_commands(body: str) -> list[list[str]]:
    section = _extract_markdown_section(body, {"验证方式"})
    if not section:
        return []
    commands: list[list[str]] = []
    for raw_command in COMMAND_RE.findall(section):
        stripped = raw_command.strip()
        if not stripped:
            continue
        if not (
            stripped.startswith("python")
            or stripped.startswith("pytest")
            or stripped.startswith("bash")
            or stripped.startswith("./")
            or stripped.startswith("scripts/")
        ):
            continue
        commands.append(stripped.split())
    return commands


def _extract_pytest_targets(*, body: str, project_dir: Path) -> list[str]:
    candidate_paths = _extract_candidate_paths(body)
    normalized: list[str] = []
    for path in candidate_paths:
        if not path.startswith("tests/"):
            continue
        if not path.endswith(".py"):
            continue
        absolute_path = project_dir / path
        if absolute_path.exists() and path not in normalized:
            normalized.append(path)
    return normalized


def _extract_candidate_paths(body: str) -> list[str]:
    sections = [
        _extract_markdown_section(body, {"修改范围"}),
        _extract_markdown_section(body, {"验证方式"}),
        _extract_markdown_section(body, {"参考"}),
    ]
    candidates: list[str] = []
    for section in sections:
        if not section:
            continue
        for path in PATH_RE.findall(section):
            normalized = path.strip().lstrip("-").strip()
            if normalized and normalized not in candidates:
                candidates.append(normalized)
    return candidates


def _build_verifier_env(project_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    src_path = project_dir / "src"
    if src_path.exists() and src_path.is_dir():
        existing = env.get("PYTHONPATH", "").strip()
        env["PYTHONPATH"] = f"{src_path}:{existing}" if existing else str(src_path)
    return env


def _should_treat_as_read_only_verification(*, body: str) -> bool:
    verification_section = _extract_markdown_section(body, {"验证方式"}).lower()
    candidate_paths = _extract_candidate_paths(body)
    if not verification_section:
        return False
    has_pytest_target = any(
        path.startswith("tests/") and path.endswith(".py") for path in candidate_paths
    )
    if has_pytest_target:
        return False
    has_python_source_scope = any(path.startswith("src/") for path in candidate_paths)
    if has_python_source_scope:
        return False
    read_only_markers = (
        "read-based",
        "contract check",
        "boundary",
        "no changes are made under",
        "confined to",
    )
    return any(marker in verification_section for marker in read_only_markers)


def _should_treat_as_implementation_only_with_external_test_ownership(
    *, body: str
) -> bool:
    verification_section = _extract_markdown_section(body, {"验证方式"}).lower()
    if not verification_section:
        return False
    ownership_markers = (
        "owned by #",
        "not this implementation task",
        "focused test coverage",
    )
    if not any(marker in verification_section for marker in ownership_markers):
        return False
    candidate_paths = _extract_candidate_paths(body)
    has_test_paths = any(
        path.startswith("tests/") and path.endswith(".py") for path in candidate_paths
    )
    has_python_source_scope = any(path.startswith("src/") for path in candidate_paths)
    if not has_python_source_scope:
        return False
    return True


def _extract_markdown_section(body: str, headings: set[str]) -> str:
    matches = list(SECTION_HEADING_RE.finditer(body or ""))
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        if heading not in headings:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        return body[start:end].strip()
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
