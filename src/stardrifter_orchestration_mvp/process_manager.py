"""
Process management utilities for stardrifter-orchestration-mvp.

This module handles:
- Process lifecycle management
- PID existence checking
- Process group termination
"""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Protocol

import psycopg


class ManagedProcess(Protocol):
    """Protocol for a managed subprocess."""

    pid: int

    def poll(self) -> int | None:
        """Check if the process has completed."""
        ...


def launch_managed_process(command: str, log_path: Path) -> ManagedProcess:
    """
    Launch a managed subprocess.

    Args:
        command: Shell command to execute
        log_path: Path to write stdout/stderr

    Returns:
        ManagedProcess instance
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8")

    return subprocess.Popen(
        ["bash", "-lc", command],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
        text=True,
    )


def terminate_process_group(pid: int) -> None:
    """Terminate a process group."""
    os.killpg(pid, signal.SIGTERM)


def pid_exists(pid: int) -> bool:
    """
    Check if a process exists.

    Handles zombie processes correctly.

    Args:
        pid: Process ID to check

    Returns:
        True if process exists and is not a zombie
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

    # Check if it's a zombie
    status_path = Path(f"/proc/{pid}/status")
    try:
        status_text = status_path.read_text()
    except OSError:
        return True

    for line in status_text.splitlines():
        if not line.startswith("State:"):
            continue
        if "\tZ" in line or "(zombie)" in line:
            return False
        break

    return True


def reconcile_finished_jobs(
    *,
    connection: psycopg.Connection,
    repo: str,
    running_processes: dict[int, ManagedProcess],
    pid_exists_fn=None,
    global_coordinator=None,
) -> None:
    """
    Reconcile finished jobs and update their status.

    Args:
        connection: Database connection
        repo: Repository name
        running_processes: Dictionary of running processes by PID
        pid_exists_fn: Function to check if PID exists (default: pid_exists)
        global_coordinator: Optional global coordinator for slot release
    """
    from .scheduling_loop import _load_running_jobs, _derive_terminal_state_for_job

    pid_exists_fn = pid_exists_fn or pid_exists
    jobs_finished = 0

    for row in _load_running_jobs(connection=connection, repo=repo):
        pid = row.get("pid")
        if pid is None:
            continue

        process = running_processes.get(pid)

        if process is None:
            if pid_exists_fn(pid):
                continue
            exit_code, final_status = _derive_terminal_state_for_job(
                connection=connection,
                row=row,
            )
        else:
            exit_code = process.poll()
            if exit_code is None:
                continue
            final_status = "succeeded" if exit_code == 0 else "failed"

        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE execution_job
                SET status = %s,
                    exit_code = %s,
                    finished_at = NOW()
                WHERE id = %s
                """,
                (
                    final_status,
                    exit_code,
                    row["id"],
                ),
            )
        connection.commit()
        running_processes.pop(pid, None)
        jobs_finished += 1

    # Release agent slots for finished jobs if global coordinator is enabled
    if global_coordinator is not None and jobs_finished > 0:
        for _ in range(jobs_finished):
            global_coordinator.release_agent_slot(repo)
