from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

import psycopg
from psycopg.rows import dict_row
from typing import Any, cast


SECTION_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
PATH_RE = re.compile(r"([A-Za-z0-9_./-]+\.(?:py|sh|md|gd|tscn|dart))")
COMMAND_RE = re.compile(r"`([^`]+)`")
PYTHON_SYMBOL_RE = re.compile(
    r"^(?:class|def)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE
)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")
GENERIC_KEYWORDS = {
    "campaign",
    "test",
    "tests",
    "src",
    "python",
    "pytest",
    "service",
    "services",
    "state",
    "runtime",
    "engine",
    "model",
    "models",
    "impl",
    "task",
    "unit",
    "integration",
    "writeback",
}


def main() -> int:
    work_id = os.environ.get("TASKPLANE_WORK_ID", "").strip()
    dsn = os.environ.get("TASKPLANE_DSN", "").strip()
    project_dir = Path(os.environ.get("TASKPLANE_PROJECT_DIR") or Path.cwd()).resolve()
    if not work_id:
        raise SystemExit("TASKPLANE_WORK_ID is required")
    if not dsn:
        raise SystemExit("TASKPLANE_DSN is required")

    with psycopg.connect(dsn, row_factory=cast(Any, dict_row)) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT wi.title, wi.dod_json, gin.body
                FROM work_item wi
                LEFT JOIN github_issue_normalized gin
                  ON gin.repo = wi.repo AND gin.issue_number = wi.source_issue_number
                WHERE wi.id = %s
                """,
                (work_id,),
            )
            row = cur.fetchone()
    if row is None:
        raise SystemExit(f"work item not found: {work_id}")

    title = str(cast(Any, row)["title"])
    body = str(cast(Any, row).get("body") or "")
    commands = _resolve_verification_commands(
        title=title,
        body=body,
        project_dir=project_dir,
        metadata=cast(Any, row).get("dod_json") or {},
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
    metadata: dict | None = None,
) -> list[list[str]]:
    metadata = metadata or {}
    if "-DOC]" in title or title.startswith("[PROCESS]"):
        return []
    if _should_treat_as_expected_red_test_task(title=title, body=body):
        return []

    explicit_metadata_commands = _extract_verification_spec_commands(
        metadata=metadata,
        project_dir=project_dir,
    )
    if explicit_metadata_commands:
        return explicit_metadata_commands

    # Try dynamic test inference first (highest priority)
    changed_path_targets = _extract_pytest_targets_from_changed_paths(
        project_dir=project_dir
    )
    if changed_path_targets:
        return [["python3", "-m", "pytest", "-q", *changed_path_targets]]
    changed_dart_targets = _extract_dart_test_targets_from_changed_paths(
        project_dir=project_dir
    )
    if changed_dart_targets:
        return [_build_dart_test_command(project_dir=project_dir, targets=changed_dart_targets)]

    # Try explicit commands, but skip directory-level pytest commands
    # (e.g., `pytest tests/unit/`) which are too broad
    explicit_commands = _extract_explicit_commands(body)
    if explicit_commands:
        # Filter out directory-level pytest commands (those ending with /)
        file_level_commands = [
            cmd for cmd in explicit_commands if not _is_directory_level_pytest(cmd)
        ]
        if file_level_commands:
            return file_level_commands
        directory_level_targets = _infer_pytest_targets_from_directory_commands(
            commands=explicit_commands,
            title=title,
            body=body,
            project_dir=project_dir,
        )
        if directory_level_targets:
            return [["python3", "-m", "pytest", "-q", *directory_level_targets]]

    pytest_targets = _extract_pytest_targets(body=body, project_dir=project_dir)
    if pytest_targets:
        return [["python3", "-m", "pytest", "-q", *pytest_targets]]
    dart_targets = _extract_dart_test_targets(body=body, project_dir=project_dir)
    if dart_targets:
        return [_build_dart_test_command(project_dir=project_dir, targets=dart_targets)]
    inferred_targets = _infer_pytest_targets_from_source_scope(
        title=title,
        body=body,
        project_dir=project_dir,
    )
    if inferred_targets:
        return [["python3", "-m", "pytest", "-q", *inferred_targets]]
    inferred_dart_targets = _infer_dart_test_targets_from_source_scope(
        title=title,
        body=body,
        project_dir=project_dir,
    )
    if inferred_dart_targets:
        return [
            _build_dart_test_command(
                project_dir=project_dir,
                targets=inferred_dart_targets,
            )
        ]
    if _should_treat_as_implementation_only_with_external_test_ownership(body=body):
        return []
    if _should_skip_verification_for_docs_only_changed_paths():
        return []
    if _should_treat_as_read_only_verification(body=body):
        return []
    return [["python3", "-m", "pytest", "-q"]]


def _extract_verification_spec_commands(
    *, metadata: dict, project_dir: Path
) -> list[list[str]]:
    verification_spec = metadata.get("verification_spec")
    if not isinstance(verification_spec, dict):
        return []
    commands = verification_spec.get("commands")
    if not isinstance(commands, list):
        return []
    normalized: list[list[str]] = []
    for raw_command in commands:
        text = str(raw_command or "").strip()
        if not text:
            continue
        tokens = text.split()
        if not tokens:
            continue
        candidate = project_dir / tokens[-1]
        if tokens[-1].startswith("tests/") and not candidate.exists():
            continue
        normalized.append(tokens)
    return normalized


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


def _is_directory_level_pytest(command: list[str]) -> bool:
    """Check if a pytest command targets a directory (e.g., tests/unit/) rather than specific files."""
    for token in command:
        if token == "pytest" or token.startswith("-"):
            continue
        if token.endswith("/") and ("tests/" in token or "test_" in token):
            return True
    return False


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


def _infer_pytest_targets_from_directory_commands(
    *,
    commands: list[list[str]],
    title: str,
    body: str,
    project_dir: Path,
) -> list[str]:
    query_keywords = _extract_query_keywords(title)
    if not query_keywords:
        return []

    scoped_dirs: list[Path] = []
    for command in commands:
        if not _is_directory_level_pytest(command):
            continue
        for token in command:
            stripped = token.strip()
            if not stripped or stripped.startswith("-"):
                continue
            if stripped in {"python", "python3", "pytest"}:
                continue
            if stripped.endswith("/") and stripped.startswith("tests/"):
                candidate = (project_dir / stripped.rstrip("/")).resolve()
                if (
                    candidate.exists()
                    and candidate.is_dir()
                    and candidate not in scoped_dirs
                ):
                    scoped_dirs.append(candidate)

    if not scoped_dirs:
        return []

    scored_targets: list[tuple[int, str]] = []
    for scoped_dir in scoped_dirs:
        for test_path in sorted(scoped_dir.rglob("test_*.py")):
            relative_path = test_path.relative_to(project_dir).as_posix()
            content = test_path.read_text(encoding="utf-8")
            score = _score_test_path_against_query_keywords(
                test_content=content,
                test_path=relative_path,
                query_keywords=query_keywords,
            )
            if score <= 0:
                continue
            scored_targets.append((score, relative_path))

    scored_targets.sort(key=lambda item: (-item[0], item[1]))
    best_score = scored_targets[0][0]
    return [path for score, path in scored_targets if score == best_score][:4]


def _extract_pytest_targets_from_changed_paths(*, project_dir: Path) -> list[str]:
    raw = os.environ.get("TASKPLANE_EXECUTION_CHANGED_PATHS_JSON", "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    targets: list[str] = []
    for item in parsed:
        if not isinstance(item, str):
            continue
        path = item.strip()
        if not path:
            continue
        if path.startswith("tests/") and path.endswith(".py"):
            candidate = project_dir / path
            if candidate.exists() and path not in targets:
                targets.append(path)
            continue
        if path.startswith("src/") and path.endswith(".py"):
            stem = Path(path).stem
            inferred = [
                f"tests/unit/test_{stem}.py",
                f"tests/integration/test_{stem}.py",
            ]
            for target in inferred:
                if target in targets:
                    continue
                candidate = project_dir / target
                if candidate.exists():
                    targets.append(target)
            continue
        if path.startswith("godot/test_runners/") and path.endswith("_runner.gd"):
            stem = Path(path).stem.removesuffix("_runner")
            inferred = [
                f"tests/integration/godot_runtime/test_{stem}_runtime.py",
            ]
            for target in inferred:
                if target in targets:
                    continue
                candidate = project_dir / target
                if candidate.exists():
                    targets.append(target)
    return targets


def _extract_dart_test_targets_from_changed_paths(*, project_dir: Path) -> list[str]:
    raw = os.environ.get("TASKPLANE_EXECUTION_CHANGED_PATHS_JSON", "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    direct_targets: list[str] = []
    source_paths: list[str] = []
    for item in parsed:
        if not isinstance(item, str):
            continue
        path = item.strip()
        if not path:
            continue
        if path.startswith("test/") and path.endswith(".dart"):
            candidate = project_dir / path
            if candidate.exists() and path not in direct_targets:
                direct_targets.append(path)
            continue
        if path.startswith("lib/") and path.endswith(".dart") and path not in source_paths:
            source_paths.append(path)

    if direct_targets:
        return direct_targets
    return _infer_dart_test_targets_from_source_paths(
        source_paths=source_paths,
        project_dir=project_dir,
    )


def _should_skip_verification_for_docs_only_changed_paths() -> bool:
    raw = os.environ.get("TASKPLANE_EXECUTION_CHANGED_PATHS_JSON", "").strip()
    if not raw:
        return False
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, list) or not parsed:
        return False

    normalized_paths: list[str] = []
    for item in parsed:
        if not isinstance(item, str):
            return False
        path = item.strip()
        if not path:
            continue
        normalized_paths.append(path)

    if not normalized_paths:
        return False
    return all(_is_docs_only_path(path) for path in normalized_paths)


def _is_docs_only_path(path: str) -> bool:
    normalized = path.strip().lstrip("./")
    lower = normalized.lower()
    if lower.endswith(".md"):
        return True
    if lower in {"readme", "readme.md", "readme.txt"}:
        return True
    return lower.startswith("docs/")


def _infer_pytest_targets_from_source_scope(
    *,
    title: str,
    body: str,
    project_dir: Path,
) -> list[str]:
    candidate_paths = _extract_candidate_paths(body)
    source_paths = [
        path
        for path in candidate_paths
        if path.startswith("src/") and path.endswith(".py")
    ]
    if not source_paths:
        return []

    direct_targets = _infer_pytest_targets_from_source_paths(
        source_paths=source_paths,
        project_dir=project_dir,
    )
    if direct_targets:
        return direct_targets

    test_root = project_dir / "tests"
    if not test_root.exists():
        return []

    query_text = f"{title}\n{body}"
    query_keywords = _extract_query_keywords(query_text)
    scored_targets: list[tuple[int, str]] = []
    for test_path in sorted(test_root.rglob("test_*.py")):
        relative_path = test_path.relative_to(project_dir).as_posix()
        content = test_path.read_text(encoding="utf-8")
        score = _score_test_path_against_source_scope(
            test_content=content,
            test_path=relative_path,
            source_paths=source_paths,
            query_keywords=query_keywords,
            project_dir=project_dir,
        )
        if score <= 0:
            continue
        scored_targets.append((score, relative_path))

    scored_targets.sort(key=lambda item: (-item[0], item[1]))
    return [path for _, path in scored_targets[:4]]


def _extract_dart_test_targets(*, body: str, project_dir: Path) -> list[str]:
    candidate_paths = _extract_candidate_paths(body)
    normalized: list[str] = []
    for path in candidate_paths:
        if not path.startswith("test/") or not path.endswith(".dart"):
            continue
        absolute_path = project_dir / path
        if absolute_path.exists() and path not in normalized:
            normalized.append(path)
    return normalized


def _infer_dart_test_targets_from_source_scope(
    *,
    title: str,
    body: str,
    project_dir: Path,
) -> list[str]:
    candidate_paths = _extract_candidate_paths(body)
    source_paths = [
        path
        for path in candidate_paths
        if path.startswith("lib/") and path.endswith(".dart")
    ]
    if not source_paths:
        return []
    return _infer_dart_test_targets_from_source_paths(
        source_paths=source_paths,
        project_dir=project_dir,
    )


def _infer_dart_test_targets_from_source_paths(
    *,
    source_paths: list[str],
    project_dir: Path,
) -> list[str]:
    if not source_paths:
        return []
    test_root = project_dir / "test"
    if not test_root.exists():
        return []

    direct_targets: list[str] = []
    scored_targets: list[tuple[int, str]] = []
    for source_path in source_paths:
        direct_targets.extend(
            _direct_dart_test_candidates_for_source_path(
                source_path=source_path,
                project_dir=project_dir,
            )
        )
        for test_path in sorted(test_root.rglob("*_test.dart")):
            relative_path = test_path.relative_to(project_dir).as_posix()
            content = test_path.read_text(encoding="utf-8")
            score = _score_dart_test_path_against_source_scope(
                test_content=content,
                test_path=relative_path,
                source_path=source_path,
            )
            if score <= 0:
                continue
            scored_targets.append((score, relative_path))

    merged: list[str] = []
    for path in direct_targets:
        if path not in merged:
            merged.append(path)

    scored_targets.sort(key=lambda item: (-item[0], item[1]))
    for _, path in scored_targets:
        if path not in merged:
            merged.append(path)
        if len(merged) >= 6:
            break
    return merged[:6]


def _direct_dart_test_candidates_for_source_path(
    *,
    source_path: str,
    project_dir: Path,
) -> list[str]:
    stem = Path(source_path).stem
    candidates = [
        f"test/{stem}_test.dart",
        f"test/{stem}_widget_test.dart",
        f"test/{stem}_page_test.dart",
        f"test/{stem}_controller_test.dart",
    ]
    resolved: list[str] = []
    for path in candidates:
        if path in resolved:
            continue
        if (project_dir / path).exists():
            resolved.append(path)
    return resolved


def _score_dart_test_path_against_source_scope(
    *,
    test_content: str,
    test_path: str,
    source_path: str,
) -> int:
    source = Path(source_path)
    test = Path(test_path)
    score = 0
    source_tokens = set(_tokenize_words(source.stem))
    filename_tokens = set(_tokenize_words(test.stem))
    content_tokens = set(_tokenize_words(test_content))
    package_relative = source_path.split("lib/", 1)[1] if source_path.startswith("lib/") else source_path

    if package_relative and package_relative in test_content:
        score += 8
    if source.stem in test.stem:
        score += 5
    score += 2 * sum(1 for token in source_tokens if token in filename_tokens)
    score += sum(1 for token in source_tokens if token in content_tokens)
    return score


def _build_dart_test_command(*, project_dir: Path, targets: list[str]) -> list[str]:
    flutterw = project_dir / "scripts" / "flutterw"
    if flutterw.exists():
        return [str(flutterw), "test", *targets]
    if (project_dir / "pubspec.yaml").exists():
        return ["flutter", "test", *targets]
    return ["dart", "test", *targets]


def _infer_pytest_targets_from_source_paths(
    *, source_paths: list[str], project_dir: Path
) -> list[str]:
    targets: list[str] = []
    for path in source_paths:
        stem = Path(path).stem
        inferred = [
            f"tests/unit/test_{stem}.py",
            f"tests/integration/test_{stem}.py",
        ]
        for target in inferred:
            if target in targets:
                continue
            candidate = project_dir / target
            if candidate.exists():
                targets.append(target)
    return targets


def _score_test_path_against_source_scope(
    *,
    test_content: str,
    test_path: str,
    source_paths: list[str],
    query_keywords: set[str],
    project_dir: Path,
) -> int:
    score = 0
    matched_scope = False
    filename_tokens = set(_tokenize_words(Path(test_path).stem))
    lowered_content = test_content.lower()
    for source_path in source_paths:
        module_path = _module_import_path_for_source(source_path)
        if module_path and module_path in lowered_content:
            score += 5
            matched_scope = True
        absolute_source = project_dir / source_path
        source_symbols = _extract_python_symbols(absolute_source)
        for symbol in source_symbols:
            if symbol.lower() in lowered_content:
                score += 2
                matched_scope = True
    if not matched_scope:
        return 0
    score += sum(1 for keyword in query_keywords if keyword in filename_tokens)
    return score


def _score_test_path_against_query_keywords(
    *,
    test_content: str,
    test_path: str,
    query_keywords: set[str],
) -> int:
    filename_tokens = set(_tokenize_words(Path(test_path).stem))
    content_tokens = set(_tokenize_words(test_content))
    filename_matches = {
        keyword for keyword in query_keywords if keyword in filename_tokens
    }
    if not filename_matches:
        return 0
    score = 3 * len(filename_matches)
    score += sum(1 for keyword in query_keywords if keyword in content_tokens)
    return score


def _module_import_path_for_source(source_path: str) -> str | None:
    path = Path(source_path)
    if not path.parts or path.parts[0] != "src" or path.suffix != ".py":
        return None
    relative = path.with_suffix("").parts[1:]
    if not relative:
        return None
    return ".".join(relative).lower()


def _extract_python_symbols(path: Path) -> set[str]:
    if not path.exists():
        return set()
    content = path.read_text(encoding="utf-8")
    return {match.group(1) for match in PYTHON_SYMBOL_RE.finditer(content)}


def _extract_query_keywords(text: str) -> set[str]:
    return {
        token
        for token in _tokenize_words(text)
        if len(token) >= 3 and token not in GENERIC_KEYWORDS
    }


def _tokenize_words(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in WORD_RE.findall(text.lower()):
        parts = [part for part in raw.split("_") if part]
        tokens.extend(parts or [raw])
    return tokens


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
        (path.startswith("tests/") and path.endswith(".py"))
        or (path.startswith("test/") and path.endswith(".dart"))
        for path in candidate_paths
    )
    if has_pytest_target:
        return False
    has_source_scope = any(
        path.startswith("src/") or (path.startswith("lib/") and path.endswith(".dart"))
        for path in candidate_paths
    )
    if has_source_scope:
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
        (path.startswith("tests/") and path.endswith(".py"))
        or (path.startswith("test/") and path.endswith(".dart"))
        for path in candidate_paths
    )
    has_source_scope = any(
        path.startswith("src/") or (path.startswith("lib/") and path.endswith(".dart"))
        for path in candidate_paths
    )
    if not has_source_scope:
        return False
    return True


def _should_treat_as_expected_red_test_task(*, title: str, body: str) -> bool:
    normalized_title = title.lower()
    normalized_body = body.lower()
    if (
        "write failing test" not in normalized_title
        and "失败测试" not in normalized_body
    ):
        return False

    red_test_markers = (
        "测试运行时失败",
        "证明行为缺失",
        "should fail",
        "behavior is not yet implemented",
        "prove reclaim-on-release behavior is not yet implemented",
    )
    return any(
        marker in body or marker in normalized_body for marker in red_test_markers
    )


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
