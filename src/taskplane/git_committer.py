from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, Callable

from .models import WorkItem
from .workspace import build_workspace_spec, resolve_base_branch

if TYPE_CHECKING:
    from .worker import ExecutionResult


@dataclass(frozen=True)
class CommitResult:
    committed: bool
    commit_sha: str | None = None
    blocked_reason: str | None = None
    summary: str = ""
    commit_message: str | None = None


@dataclass(frozen=True)
class StoryIntegrationResult:
    merged: bool
    merge_commit_sha: str | None = None
    promoted: bool = False
    promotion_commit_sha: str | None = None
    pull_number: int | None = None
    pull_url: str | None = None
    blocked_reason: str | None = None
    summary: str = ""


def build_git_committer(
    *, workdir: Path
) -> Callable[[WorkItem, ExecutionResult, Path | None], CommitResult]:
    repo_root = Path(workdir).resolve()

    def _committer(
        work_item: WorkItem,
        execution_result: ExecutionResult,
        workspace_path: Path | None = None,
    ) -> CommitResult:
        payload = execution_result.result_payload_json or {}
        changed_paths = list(payload.get("changed_paths") or [])
        if not changed_paths:
            return CommitResult(
                committed=False,
                summary="no changed paths to commit",
            )

        preexisting_dirty_paths = set(payload.get("preexisting_dirty_paths") or [])
        unsafe_paths = [
            path for path in changed_paths if path in preexisting_dirty_paths
        ]
        if unsafe_paths:
            return CommitResult(
                committed=False,
                blocked_reason="unsafe_auto_commit_dirty_paths",
                summary="cannot safely auto-commit paths that were already dirty before task execution",
            )

        issue_number = (
            work_item.source_issue_number
            or work_item.canonical_story_issue_number
            or _parse_issue_number(work_item.id)
        )
        commit_scope = _infer_commit_scope(changed_paths)
        commit_message = (
            f"chore({commit_scope}): complete task #{issue_number}\n\n"
            f"refs #{issue_number}"
        )
        target_repo_root = (
            Path(workspace_path).resolve() if workspace_path is not None else repo_root
        )

        try:
            subprocess.run(
                ["git", "add", "--", *changed_paths],
                cwd=target_repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            return CommitResult(
                committed=False,
                blocked_reason="git_add_failed",
                summary=f"git add failed: {_summarize_git_error(exc)}",
                commit_message=commit_message,
            )

        try:
            subprocess.run(
                ["git", "commit", "--only", "-m", commit_message, "--", *changed_paths],
                cwd=target_repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            return CommitResult(
                committed=False,
                blocked_reason="git_commit_failed",
                summary=f"git commit failed: {_summarize_git_error(exc)}",
                commit_message=commit_message,
            )
        commit_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=target_repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return CommitResult(
            committed=True,
            commit_sha=commit_sha,
            summary="auto-committed task changes",
            commit_message=commit_message,
        )

    return _committer


def build_git_story_integrator(
    *,
    repo_root: Path,
    base_branch: str | None = None,
    ignored_dirty_path_prefixes: tuple[str, ...] = (),
    promotion_repo_root: Path | None = None,
    promotion_base_branch: str | None = None,
    promotion_ignored_dirty_path_prefixes: tuple[str, ...] = (),
) -> Callable[..., StoryIntegrationResult]:
    resolved_repo_root = Path(repo_root).resolve()
    resolved_promotion_repo_root = (
        Path(promotion_repo_root).resolve() if promotion_repo_root is not None else None
    )

    def _integrator(
        *,
        story_issue_number: int,
        story_work_items: list[WorkItem],
    ) -> StoryIntegrationResult:
        resolved_base_branch = base_branch or resolve_base_branch(resolved_repo_root)
        resolved_promotion_base_branch = (
            promotion_base_branch
            or (
                resolve_base_branch(resolved_promotion_repo_root)
                if resolved_promotion_repo_root is not None
                else resolved_base_branch
            )
        )
        representative = _select_story_representative(
            story_issue_number=story_issue_number,
            story_work_items=story_work_items,
        )
        if representative is None:
            return StoryIntegrationResult(
                merged=False,
                blocked_reason="missing_story_work_items",
                summary="cannot integrate story without projected work items",
            )

        branch_name = build_workspace_spec(
            work_item=representative,
            repo_root=resolved_repo_root,
        ).branch_name
        current_branch = _run_git_stdout(
            resolved_repo_root,
            ["git", "branch", "--show-current"],
        )
        if current_branch != resolved_base_branch:
            return StoryIntegrationResult(
                merged=False,
                blocked_reason="base_branch_not_checked_out",
                summary=(
                    f"refusing to merge {branch_name} because "
                    f"{resolved_repo_root} is on {current_branch or '<detached>'}"
                ),
            )
        if _has_dirty_worktree(
            resolved_repo_root,
            ignored_path_prefixes=ignored_dirty_path_prefixes,
        ):
            return StoryIntegrationResult(
                merged=False,
                blocked_reason="dirty_base_branch",
                summary=f"refusing to merge {branch_name} into dirty {resolved_base_branch}",
            )
        if _is_branch_merged(
            repo_root=resolved_repo_root,
            branch_name=branch_name,
            base_branch=resolved_base_branch,
        ):
            promotion_result = _promote_base_branch(
                source_repo_root=resolved_repo_root,
                source_branch=resolved_base_branch,
                target_repo_root=resolved_promotion_repo_root,
                target_base_branch=resolved_promotion_base_branch,
                ignored_dirty_path_prefixes=promotion_ignored_dirty_path_prefixes,
            )
            if promotion_result.blocked_reason is not None:
                return StoryIntegrationResult(
                    merged=True,
                    merge_commit_sha=_run_git_stdout(
                        resolved_repo_root,
                        ["git", "rev-parse", "HEAD"],
                    ),
                    promoted=False,
                    promotion_commit_sha=promotion_result.promotion_commit_sha,
                    blocked_reason=promotion_result.blocked_reason,
                    summary=promotion_result.summary,
                )
            return StoryIntegrationResult(
                merged=True,
                merge_commit_sha=_run_git_stdout(
                    resolved_repo_root,
                    ["git", "rev-parse", "HEAD"],
                ),
                promoted=promotion_result.promoted,
                promotion_commit_sha=promotion_result.promotion_commit_sha,
                summary=promotion_result.summary
                or f"{branch_name} already merged into {resolved_base_branch}",
            )

        if not _branch_exists(repo_root=resolved_repo_root, branch_name=branch_name):
            return StoryIntegrationResult(
                merged=False,
                blocked_reason="missing_story_branch",
                summary=f"required story branch {branch_name} does not exist",
            )

        try:
            subprocess.run(
                ["git", "merge", "--no-ff", "--no-edit", branch_name],
                cwd=resolved_repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError:
            _abort_merge_if_needed(resolved_repo_root)
            return StoryIntegrationResult(
                merged=False,
                blocked_reason="story_merge_conflict",
                summary=f"failed to merge {branch_name} into {resolved_base_branch}",
            )

        merge_commit_sha = _run_git_stdout(
            resolved_repo_root,
            ["git", "rev-parse", "HEAD"],
        )
        promotion_result = _promote_base_branch(
            source_repo_root=resolved_repo_root,
            source_branch=resolved_base_branch,
            target_repo_root=resolved_promotion_repo_root,
            target_base_branch=resolved_promotion_base_branch,
            ignored_dirty_path_prefixes=promotion_ignored_dirty_path_prefixes,
        )
        if promotion_result.blocked_reason is not None:
            return StoryIntegrationResult(
                merged=True,
                merge_commit_sha=merge_commit_sha,
                promoted=False,
                promotion_commit_sha=promotion_result.promotion_commit_sha,
                blocked_reason=promotion_result.blocked_reason,
                summary=promotion_result.summary,
            )
        return StoryIntegrationResult(
            merged=True,
            merge_commit_sha=merge_commit_sha,
            promoted=promotion_result.promoted,
            promotion_commit_sha=promotion_result.promotion_commit_sha,
            summary=promotion_result.summary
            or f"merged {branch_name} into {resolved_base_branch}",
        )

    return _integrator


def _parse_issue_number(work_id: str) -> int:
    if work_id.startswith("issue-"):
        return int(work_id.split("-", 1)[1])
    raise ValueError(f"cannot infer issue number from work_id: {work_id}")


def _infer_commit_scope(changed_paths: list[str]) -> str:
    normalized_paths = [path.strip() for path in changed_paths if path.strip()]
    if not normalized_paths:
        return "core"
    if all(path.startswith("docs/") for path in normalized_paths):
        return "docs"
    if all(path.startswith("tests/") for path in normalized_paths):
        return "test"
    if any(path.startswith("src/stardrifter_engine/world") for path in normalized_paths):
        return "world"
    if any(path.startswith("src/stardrifter_engine/economy") for path in normalized_paths):
        return "economy"
    if any(path.startswith("src/stardrifter_engine/agent") for path in normalized_paths):
        return "agent"
    if any(path.startswith("godot/ui/") for path in normalized_paths):
        return "ui"
    if any(path.startswith("requirements") or path.endswith("poetry.lock") for path in normalized_paths):
        return "deps"
    return "core"


def _summarize_git_error(error: subprocess.CalledProcessError) -> str:
    stdout = (error.stdout or "").strip()
    stderr = (error.stderr or "").strip()
    if stderr:
        return stderr.splitlines()[-1]
    if stdout:
        return stdout.splitlines()[-1]
    return f"exit {error.returncode}"


def _select_story_representative(
    *,
    story_issue_number: int,
    story_work_items: list[WorkItem],
) -> WorkItem | None:
    for work_item in story_work_items:
        if work_item.canonical_story_issue_number == story_issue_number:
            return work_item
    if story_work_items:
        return story_work_items[0]
    return None


def _run_git_stdout(repo_root: Path, command: list[str]) -> str:
    return subprocess.run(
        command,
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _branch_exists(*, repo_root: Path, branch_name: str) -> bool:
    completed = subprocess.run(
        ["git", "show-ref", "--verify", f"refs/heads/{branch_name}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def _has_dirty_worktree(
    repo_root: Path,
    *,
    ignored_path_prefixes: tuple[str, ...] = (),
) -> bool:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    normalized_prefixes = tuple(
        prefix.rstrip("/") + "/" for prefix in ignored_path_prefixes if prefix.strip()
    )
    for line in (completed.stdout or "").splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        normalized_path = path.rstrip("/") + ("/" if path.endswith("/") else "")
        if any(
            normalized_path.startswith(prefix) or path.startswith(prefix)
            for prefix in normalized_prefixes
        ):
            continue
        return True
    return False


def _is_branch_merged(*, repo_root: Path, branch_name: str, base_branch: str) -> bool:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", branch_name, base_branch],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def _abort_merge_if_needed(repo_root: Path) -> None:
    merge_head = repo_root / ".git" / "MERGE_HEAD"
    if not merge_head.exists():
        return
    subprocess.run(
        ["git", "merge", "--abort"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )


@dataclass(frozen=True)
class PromotionResult:
    promoted: bool
    promotion_commit_sha: str | None = None
    blocked_reason: str | None = None
    summary: str = ""


def _promote_base_branch(
    *,
    source_repo_root: Path,
    source_branch: str,
    target_repo_root: Path | None,
    target_base_branch: str,
    ignored_dirty_path_prefixes: tuple[str, ...] = (),
) -> PromotionResult:
    if (
        target_repo_root is None
        or target_repo_root.resolve() == source_repo_root.resolve()
    ):
        return PromotionResult(
            promoted=False,
            summary=f"merged {source_branch} in execution repository",
        )
    current_branch = _run_git_stdout(
        target_repo_root,
        ["git", "branch", "--show-current"],
    )
    if current_branch != target_base_branch:
        return PromotionResult(
            promoted=False,
            blocked_reason="promotion_base_branch_not_checked_out",
            summary=(
                f"refusing to promote into {target_repo_root} because "
                f"{current_branch or '<detached>'} is checked out instead of {target_base_branch}"
            ),
        )
    if _has_dirty_worktree(
        target_repo_root,
        ignored_path_prefixes=ignored_dirty_path_prefixes,
    ):
        return PromotionResult(
            promoted=False,
            blocked_reason="dirty_promotion_branch",
            summary=f"refusing to promote into dirty {target_base_branch}",
        )

    subprocess.run(
        ["git", "fetch", str(source_repo_root), source_branch],
        cwd=target_repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    if _is_fetch_head_merged(target_repo_root, target_base_branch):
        return PromotionResult(
            promoted=False,
            summary=f"{target_base_branch} already contains promoted {source_branch}",
        )
    try:
        subprocess.run(
            ["git", "merge", "--no-ff", "--no-edit", "FETCH_HEAD"],
            cwd=target_repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        _abort_merge_if_needed(target_repo_root)
        return PromotionResult(
            promoted=False,
            blocked_reason="promotion_merge_conflict",
            summary=f"failed to promote {source_branch} into {target_base_branch}",
        )
    return PromotionResult(
        promoted=True,
        promotion_commit_sha=_run_git_stdout(
            target_repo_root,
            ["git", "rev-parse", "HEAD"],
        ),
        summary=f"merged {source_branch} into execution repo and promoted to target {target_base_branch}",
    )


def _is_fetch_head_merged(repo_root: Path, base_branch: str) -> bool:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", "FETCH_HEAD", base_branch],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0
