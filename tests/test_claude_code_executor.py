from __future__ import annotations

from pathlib import Path


def test_run_controlled_claude_code_task_delegates_to_codex(
    monkeypatch, tmp_path: Path
):
    from taskplane.claude_code_task_executor import run_controlled_claude_code_task

    captured: dict[str, object] = {}

    def fake_codex_runner(
        *, work_id: str, dsn: str, project_dir: Path, resume_context: str = ""
    ) -> int:
        captured["work_id"] = work_id
        captured["dsn"] = dsn
        captured["project_dir"] = project_dir
        captured["resume_context"] = resume_context
        return 0

    monkeypatch.setattr(
        "taskplane.claude_code_task_executor.run_controlled_codex_task",
        fake_codex_runner,
    )

    result = run_controlled_claude_code_task(
        work_id="task-1",
        dsn="postgresql://example",
        project_dir=tmp_path,
        resume_context="resume me",
    )

    assert result == 0
    assert captured == {
        "work_id": "task-1",
        "dsn": "postgresql://example",
        "project_dir": tmp_path,
        "resume_context": "resume me",
    }
