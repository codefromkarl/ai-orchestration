from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
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
    base_branch: str = "main"
    keep_worktrees: bool = True
    runner: Callable[[list[str]], None] | None = None

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
        if not spec.workspace_path.exists():
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
    base_branch: str = "main",
    runner=None,
    branch_exists=None,
) -> WorkspaceSpec:
    spec = build_workspace_spec(
        work_item=work_item,
        repo_root=repo_root,
        worktree_root=worktree_root,
    )
    branch_exists = branch_exists or _git_branch_exists
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
            base_branch,
        ]
    runner = runner or _run_command
    runner(command)
    return spec


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
