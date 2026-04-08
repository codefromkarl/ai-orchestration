from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import shutil
import subprocess
from typing import Callable, Protocol

from .models import WorkItem


@dataclass(frozen=True)
class WorkspaceSpec:
    branch_name: str
    workspace_path: Path


class WorkspaceRepository(Protocol):
    def delete_work_claim(self, work_id: str) -> None: ...


@dataclass
class WorkspaceManager:
    repo_root: Path
    worktree_root: Path | None = None
    base_branch: str | None = None
    keep_worktrees: bool = True
    runner: Callable[[list[str]], None] | None = None
    _prewarmed_paths: set[Path] = field(default_factory=set, init=False, repr=False)

    def prewarm(
        self,
        *,
        work_items: list[WorkItem],
    ) -> list[Path]:
        warmed_paths: list[Path] = []
        seen_paths: set[Path] = set()
        for work_item in work_items:
            if work_item.canonical_story_issue_number is None:
                continue
            spec = build_workspace_spec(
                work_item=work_item,
                repo_root=self.repo_root,
                worktree_root=self.worktree_root,
            )
            if spec.workspace_path in seen_paths:
                continue
            seen_paths.add(spec.workspace_path)
            spec = ensure_workspace(
                work_item=work_item,
                repo_root=self.repo_root,
                worktree_root=self.worktree_root,
                base_branch=self.base_branch,
                runner=self.runner,
            )
            self._prewarmed_paths.add(spec.workspace_path)
            warmed_paths.append(spec.workspace_path)
        return warmed_paths

    def prepare(
        self,
        *,
        work_item: WorkItem,
        worker_name: str,
        repository: WorkspaceRepository,
    ) -> Path:
        spec = build_workspace_spec(
            work_item=work_item,
            repo_root=self.repo_root,
            worktree_root=self.worktree_root,
        )
        if (
            not spec.workspace_path.exists()
            and spec.workspace_path not in self._prewarmed_paths
        ):
            ensure_workspace(
                work_item=work_item,
                repo_root=self.repo_root,
                worktree_root=self.worktree_root,
                base_branch=self.base_branch,
                runner=self.runner,
            )
        return spec.workspace_path

    def release(
        self,
        *,
        work_item: WorkItem,
        repository: WorkspaceRepository,
    ) -> None:
        repository.delete_work_claim(work_item.id)
        if not self.keep_worktrees:
            spec = build_workspace_spec(
                work_item=work_item,
                repo_root=self.repo_root,
                worktree_root=self.worktree_root,
            )
            _run_command(
                [
                    "git",
                    "-C",
                    str(self.repo_root),
                    "worktree",
                    "remove",
                    "--force",
                    str(spec.workspace_path),
                ]
            )
            self._prewarmed_paths.discard(spec.workspace_path)


def build_workspace_spec(
    *,
    work_item: WorkItem,
    repo_root: Path,
    worktree_root: Path | None = None,
) -> WorkspaceSpec:
    root = worktree_root or repo_root.parent / "worktrees"
    if work_item.canonical_story_issue_number is not None:
        branch_name = f"story/{work_item.canonical_story_issue_number}"
        workspace_path = root / f"story-{work_item.canonical_story_issue_number}"
    else:
        issue_number = work_item.source_issue_number or _extract_issue_number(work_item.id)
        slug = _slugify_title(work_item.title)
        branch_name = f"task/{issue_number}-{slug}"
        workspace_path = root / f"task-{issue_number}-{slug}"
    return WorkspaceSpec(
        branch_name=branch_name,
        workspace_path=workspace_path,
    )


def ensure_workspace(
    *,
    work_item: WorkItem,
    repo_root: Path,
    worktree_root: Path | None = None,
    base_branch: str | None = None,
    runner=None,
    branch_exists=None,
) -> WorkspaceSpec:
    spec = build_workspace_spec(
        work_item=work_item,
        repo_root=repo_root,
        worktree_root=worktree_root,
    )
    if spec.workspace_path.exists():
        _sync_claimed_dirty_paths(
            repo_root=repo_root,
            workspace_path=spec.workspace_path,
            work_item=work_item,
        )
        _sync_support_dirty_paths(
            repo_root=repo_root,
            workspace_path=spec.workspace_path,
            work_item=work_item,
        )
        return spec
    branch_exists = branch_exists or _git_branch_exists
    resolved_base_branch = base_branch or resolve_base_branch(repo_root)
    if branch_exists(repo_root, spec.branch_name):
        command = [
            "git",
            "-C",
            str(repo_root),
            "worktree",
            "add",
            str(spec.workspace_path),
            spec.branch_name,
        ]
    else:
        command = [
            "git",
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "-b",
            spec.branch_name,
            str(spec.workspace_path),
            resolved_base_branch,
        ]
    runner = runner or _run_command
    runner(command)
    _sync_claimed_dirty_paths(
        repo_root=repo_root,
        workspace_path=spec.workspace_path,
        work_item=work_item,
    )
    _sync_support_dirty_paths(
        repo_root=repo_root,
        workspace_path=spec.workspace_path,
        work_item=work_item,
    )
    return spec


def resolve_base_branch(repo_root: Path) -> str:
    current_branch = _git_stdout(
        repo_root,
        ["git", "-C", str(repo_root), "branch", "--show-current"],
    )
    if current_branch:
        return current_branch

    remote_head = _git_stdout(
        repo_root,
        ["git", "-C", str(repo_root), "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
        check=False,
    )
    if remote_head and "/" in remote_head:
        return remote_head.rsplit("/", 1)[-1]

    for candidate in ("master", "main"):
        if _git_branch_exists(repo_root, candidate):
            return candidate
    return "main"


def _extract_issue_number(work_id: str) -> int:
    match = re.search(r"(\d+)$", work_id)
    if match is None:
        raise ValueError(f"unable to derive issue number from work id: {work_id}")
    return int(match.group(1))


def _slugify_title(title: str) -> str:
    bracket_tokens = [
        token.lower() for token in re.findall(r"\[([^\]]+)\]", title) if token.strip()
    ]
    if bracket_tokens:
        normalized = bracket_tokens[-1]
    else:
        normalized = title.lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    tokens = [token for token in normalized.split("-") if token]
    if not tokens:
        return "task"
    return "-".join(tokens[:3])


def _run_command(command: list[str]) -> None:
    subprocess.run(command, check=True)


def _git_branch_exists(repo_root: Path, branch_name: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "show-ref", "--verify", f"refs/heads/{branch_name}"],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def _git_stdout(repo_root: Path, command: list[str], *, check: bool = True) -> str:
    completed = subprocess.run(
        command,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            command,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _sync_support_dirty_paths(
    *,
    repo_root: Path,
    workspace_path: Path,
    work_item: WorkItem,
) -> None:
    for relative_path in _list_dirty_support_paths(
        repo_root=repo_root,
        excluded_paths=work_item.planned_paths,
    ):
        source = repo_root / relative_path
        target = workspace_path / relative_path
        if source.is_dir():
            continue
        if not source.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _sync_claimed_dirty_paths(
    *,
    repo_root: Path,
    workspace_path: Path,
    work_item: WorkItem,
) -> None:
    for relative_path in _list_claimed_dirty_paths(
        repo_root=repo_root,
        claimed_paths=work_item.planned_paths,
    ):
        source = repo_root / relative_path
        target = workspace_path / relative_path
        if source.is_dir():
            continue
        if not source.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _list_dirty_support_paths(
    *,
    repo_root: Path,
    excluded_paths: tuple[str, ...],
) -> list[Path]:
    dirty_paths = _git_porcelain_paths(repo_root)
    resolved: list[Path] = []
    for relative_path in dirty_paths:
        path_text = relative_path.as_posix()
        if _is_workspace_internal_path(path_text):
            continue
        if _is_excluded_dirty_path(path_text, excluded_paths):
            continue
        resolved.append(relative_path)
    return resolved


def _list_claimed_dirty_paths(
    *,
    repo_root: Path,
    claimed_paths: tuple[str, ...],
) -> list[Path]:
    dirty_paths = _git_porcelain_paths(repo_root)
    resolved: list[Path] = []
    for relative_path in dirty_paths:
        path_text = relative_path.as_posix()
        if _is_workspace_internal_path(path_text):
            continue
        if not _is_excluded_dirty_path(path_text, claimed_paths):
            continue
        resolved.append(relative_path)
    return resolved


def _git_porcelain_paths(repo_root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain", "--untracked-files=all", "-z"],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0 or not completed.stdout:
        return []

    entries = completed.stdout.split(b"\0")
    paths: list[Path] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        text = entry.decode("utf-8", errors="replace")
        if len(text) < 4:
            continue
        status = text[:2]
        path_text = text[3:]
        if status.startswith("R") or status.startswith("C"):
            if index >= len(entries):
                continue
            path_text = entries[index].decode("utf-8", errors="replace")
            index += 1
        normalized = path_text.strip()
        if not normalized:
            continue
        paths.append(Path(normalized))
    return paths


def _is_workspace_internal_path(path_text: str) -> bool:
    normalized = _normalize_relative_path(path_text)
    return normalized.startswith(".taskplane/") or normalized.startswith(".git/")


def _is_excluded_dirty_path(path_text: str, excluded_paths: tuple[str, ...]) -> bool:
    normalized = _normalize_relative_path(path_text)
    for raw_excluded in excluded_paths:
        excluded = _normalize_relative_path(str(raw_excluded or ""))
        if not excluded:
            continue
        if normalized == excluded:
            return True
        if excluded.endswith("/"):
            if normalized.startswith(excluded):
                return True
            continue
        if normalized.startswith(f"{excluded}/"):
            return True
    return False


def _normalize_relative_path(path_text: str) -> str:
    normalized = path_text.strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized
