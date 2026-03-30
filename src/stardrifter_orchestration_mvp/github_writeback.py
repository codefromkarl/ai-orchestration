from __future__ import annotations

import json
import subprocess
from typing import Callable

from .protocols import StoryWritebackAdapter, TaskWritebackAdapter


def sync_issue_status_via_gh(
    *,
    repo: str,
    issue_number: int,
    status: str,
    decision_required: bool = False,
    runner: Callable[[str], str] | None = None,
) -> None:
    if runner is None:
        runner = _default_shell_runner

    labels_to_add = [f"status:{status}"]
    current_labels = _load_issue_labels(repo=repo, issue_number=issue_number, runner=runner)
    labels_to_remove = [
        label
        for label in ["status:done", "status:blocked"]
        if label != f"status:{status}" and label in current_labels
    ]
    if decision_required:
        if "decision-required" not in current_labels:
            labels_to_add.append("decision-required")
    elif "decision-required" in current_labels:
        labels_to_remove.append("decision-required")

    add_flags = " ".join(f"--add-label {label}" for label in labels_to_add)
    remove_flags = " ".join(f"--remove-label {label}" for label in labels_to_remove)
    edit_command = (
        f"unset GITHUB_TOKEN; gh issue edit {issue_number} --repo {repo} "
        f"{add_flags} {remove_flags}"
    )
    runner(edit_command)
    state_command = (
        f"unset GITHUB_TOKEN; gh issue close {issue_number} --repo {repo} --comment "
        f'"sync from control plane"'
        if status == "done"
        else f"unset GITHUB_TOKEN; gh issue reopen {issue_number} --repo {repo}"
    )
    runner(state_command)


task_github_writeback: TaskWritebackAdapter = sync_issue_status_via_gh
story_github_writeback: StoryWritebackAdapter = sync_issue_status_via_gh


def _default_shell_runner(command: str) -> str:
    completed = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout


def _load_issue_labels(*, repo: str, issue_number: int, runner: Callable[[str], str]) -> set[str]:
    output = runner(
        f"unset GITHUB_TOKEN; gh issue view {issue_number} --repo {repo} --json labels"
    )
    payload = json.loads(output or "{}")
    labels = payload.get("labels") or []
    return {str(label.get('name') or '').strip() for label in labels if isinstance(label, dict)}
