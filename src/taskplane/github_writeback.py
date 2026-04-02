from __future__ import annotations

import json
import shlex
import subprocess
import time
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

    external_status = _map_control_plane_status_to_github_label(status)
    labels_to_add = [f"status:{external_status}"]
    current_labels = _load_issue_labels(repo=repo, issue_number=issue_number, runner=runner)
    labels_to_remove = [
        label
        for label in current_labels
        if label.startswith("status:") and label != f"status:{external_status}"
    ]
    if decision_required:
        if "decision-required" not in current_labels:
            labels_to_add.append("decision-required")
    elif "decision-required" in current_labels:
        labels_to_remove.append("decision-required")

    final_labels = sorted(
        {
            label
            for label in current_labels
            if label and label not in labels_to_remove
        }.union({label for label in labels_to_add if label})
    )
    label_flags = " ".join(
        f"-f labels[]={shlex.quote(label)}" for label in final_labels
    )
    state_value = "closed" if external_status == "done" else "open"
    label_command = (
        f"unset GITHUB_TOKEN; gh api repos/{repo}/issues/{issue_number}/labels "
        f"--method PUT {label_flags}"
    )
    runner(label_command)
    state_command = (
        f"unset GITHUB_TOKEN; gh api repos/{repo}/issues/{issue_number} "
        f"--method PATCH -f state={state_value}"
    )
    runner(state_command)


task_github_writeback: TaskWritebackAdapter = sync_issue_status_via_gh
story_github_writeback: StoryWritebackAdapter = sync_issue_status_via_gh


def _default_shell_runner(command: str) -> str:
    attempts = 3
    last_error = ""
    for attempt in range(1, attempts + 1):
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            return completed.stdout
        last_error = completed.stderr.strip() or completed.stdout.strip()
        if (
            "TLS handshake timeout" not in last_error
            and "EOF" not in last_error
            and "connection reset by peer" not in last_error.lower()
        ):
            break
        if attempt < attempts:
            time.sleep(2 * attempt)
    raise RuntimeError(last_error)


def _load_issue_labels(*, repo: str, issue_number: int, runner: Callable[[str], str]) -> set[str]:
    output = runner(
        f"unset GITHUB_TOKEN; gh issue view {issue_number} --repo {repo} --json labels"
    )
    payload = json.loads(output or "{}")
    labels = payload.get("labels") or []
    return {str(label.get('name') or '').strip() for label in labels if isinstance(label, dict)}


def _map_control_plane_status_to_github_label(status: str) -> str:
    if status == "done":
        return "done"
    if status in {"blocked", "awaiting_approval"}:
        return "blocked"
    if status in {"in_progress", "verifying"}:
        return "in-progress"
    return "pending"
