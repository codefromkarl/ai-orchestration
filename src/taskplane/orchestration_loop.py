from __future__ import annotations

import argparse
import os
from pathlib import Path
import time
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row


DOC_RESET_SQL = """
UPDATE work_item
SET status = 'pending', updated_at = NOW()
WHERE status IN ('in_progress', 'blocked')
  AND (
    title LIKE '[%-DOC]%%'
    OR title LIKE '[PROCESS]%%'
  )
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="taskplane-loop",
        description="Run story-by-story orchestration loop using opencode.",
    )
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--repo", default="codefromkarl/stardrifter")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--poll-interval", type=int, default=60)
    parser.add_argument("--opencode-timeout-seconds", type=int, default=1200)
    parser.add_argument(
        "--allowed-wave",
        action="append",
        default=["wave-1", "wave-2", "wave-3", "wave-4", "wave-5", "unassigned"],
    )
    parser.add_argument("--worktree-root")
    parser.add_argument("--decomposer-command")
    parser.add_argument("--epic-decomposer-command")
    parser.add_argument("--log-file", required=True)
    args = parser.parse_args()

    log_path = Path(args.log_file).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    conn = psycopg.connect(args.dsn, row_factory=cast(Any, dict_row))
    cur = conn.cursor()
    cur.execute(DOC_RESET_SQL)
    conn.commit()
    conn.close()

    executor_command = (
        "export TASKPLANE_CODEX_TIMEOUT_SECONDS='{timeout_seconds}'; "
        "python3 -m taskplane.codex_task_executor"
    ).format(
        timeout_seconds=args.opencode_timeout_seconds,
    )
    verifier_command = "python3 -m taskplane.task_verifier"
    decomposer_command = args.decomposer_command or (
        "export TASKPLANE_OPENCODE_TIMEOUT_SECONDS='{timeout_seconds}'; "
        "python3 -m taskplane.opencode_story_decomposer"
    ).format(
        timeout_seconds=args.opencode_timeout_seconds,
    )
    epic_decomposer_command = args.epic_decomposer_command or (
        "export TASKPLANE_OPENCODE_TIMEOUT_SECONDS='{timeout_seconds}'; "
        "python3 -m taskplane.opencode_epic_decomposer"
    ).format(
        timeout_seconds=args.opencode_timeout_seconds,
    )
    allowed_wave_args = " ".join(f"--allowed-wave {wave}" for wave in args.allowed_wave)
    worktree_root_arg = (
        f"--worktree-root '{Path(args.worktree_root).resolve()}'"
        if args.worktree_root
        else ""
    )

    while True:
        conn = psycopg.connect(args.dsn, row_factory=cast(Any, dict_row))
        cur = conn.cursor()
        cur.execute(
            """
            SELECT epic_issue_number
            FROM v_epic_decomposition_queue
            WHERE repo = %s
            ORDER BY epic_issue_number
            """,
            (args.repo,),
        )
        decomposition_epic_issue_numbers = [
            cast(Any, row)["epic_issue_number"] for row in cur.fetchall()
        ]
        cur.execute(
            """
            SELECT story_issue_number
            FROM v_story_decomposition_queue
            WHERE repo = %s
            ORDER BY story_issue_number
            """,
            (args.repo,),
        )
        decomposition_story_issue_numbers = [
            cast(Any, row)["story_issue_number"] for row in cur.fetchall()
        ]
        cur.execute(
            """
            SELECT DISTINCT canonical_story_issue_number AS story_issue_number
            FROM v_active_task_queue
            WHERE repo = %s
              AND canonical_story_issue_number IS NOT NULL
            ORDER BY canonical_story_issue_number
            """,
            (args.repo,),
        )
        story_issue_numbers = [
            cast(Any, row)["story_issue_number"] for row in cur.fetchall()
        ]
        conn.close()

        all_complete = True
        for epic_issue_number in decomposition_epic_issue_numbers:
            command = (
                "export TASKPLANE_DSN='{dsn}'; "
                "python3 -m taskplane.epic_decomposition_cli "
                "--repo {repo} "
                "--epic-issue-number {epic} "
                "--workdir '{project_dir}' "
                '--decomposer-command "{decomposer_command}"'
            ).format(
                dsn=args.dsn,
                repo=args.repo,
                epic=epic_issue_number,
                decomposer_command=epic_decomposer_command.replace('"', '\\"'),
                project_dir=args.project_dir,
            )
            completed = subprocess_run(command)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(completed + "\n")
            all_complete = False
        for story_issue_number in decomposition_story_issue_numbers:
            command = (
                "export TASKPLANE_DSN='{dsn}'; "
                "python3 -m taskplane.story_decomposition_cli "
                "--repo {repo} "
                "--story-issue-number {story} "
                "--workdir '{project_dir}' "
                '--decomposer-command "{decomposer_command}"'
            ).format(
                dsn=args.dsn,
                repo=args.repo,
                story=story_issue_number,
                decomposer_command=decomposer_command.replace('"', '\\"'),
                project_dir=args.project_dir,
            )
            completed = subprocess_run(command)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(completed + "\n")
            all_complete = False
        for story_issue_number in story_issue_numbers:
            command = (
                "export TASKPLANE_DSN='{dsn}'; "
                "python3 -m taskplane.story_runner_cli "
                "--story-issue-number {story} "
                "--worker-name story-loop "
                "{allowed_wave_args} "
                "{worktree_root_arg} "
                '--executor-command "{executor_command}" '
                '--verifier-command "{verifier_command}" '
                "--workdir '{project_dir}'"
            ).format(
                dsn=args.dsn,
                story=story_issue_number,
                allowed_wave_args=allowed_wave_args,
                worktree_root_arg=worktree_root_arg,
                executor_command=executor_command.replace('"', '\\"'),
                verifier_command=verifier_command.replace('"', '\\"'),
                project_dir=args.project_dir,
            )
            completed = subprocess_run(command)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(completed + "\n")
            if "incomplete" in completed:
                all_complete = False

        if all_complete and story_issue_numbers:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write("all projected stories complete\n")
            return 0

        time.sleep(args.poll_interval)


def entrypoint() -> None:
    raise SystemExit(main())


def subprocess_run(command: str) -> str:
    import subprocess

    completed = subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        check=False,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    return output.strip()


if __name__ == "__main__":
    entrypoint()
