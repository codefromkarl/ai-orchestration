from __future__ import annotations

from pathlib import Path

from .codex_task_executor import run_controlled_codex_task


def main() -> int:
    import os

    work_id = (os.environ.get("TASKPLANE_WORK_ID") or "").strip()
    dsn = (os.environ.get("TASKPLANE_DSN") or "").strip()
    project_dir = Path(os.environ.get("TASKPLANE_PROJECT_DIR") or Path.cwd()).resolve()
    resume_context = (os.environ.get("TASKPLANE_RESUME_CONTEXT") or "").strip()
    if not work_id:
        raise SystemExit("TASKPLANE_WORK_ID is required")
    if not dsn:
        raise SystemExit("TASKPLANE_DSN is required")
    return run_controlled_claude_code_task(
        work_id=work_id,
        dsn=dsn,
        project_dir=project_dir,
        resume_context=resume_context,
    )


def run_controlled_claude_code_task(
    *,
    work_id: str,
    dsn: str,
    project_dir: Path,
    resume_context: str = "",
) -> int:
    return run_controlled_codex_task(
        work_id=work_id,
        dsn=dsn,
        project_dir=project_dir,
        resume_context=resume_context,
    )


if __name__ == "__main__":
    raise SystemExit(main())
