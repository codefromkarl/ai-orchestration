from pathlib import Path

from taskplane.codex_task_executor import (
    _build_codex_exec_command,
)


def test_build_codex_exec_command_uses_gpt_5_4_mini_by_default(
    monkeypatch, tmp_path: Path
):
    monkeypatch.delenv("TASKPLANE_CODEX_MODEL", raising=False)

    command = _build_codex_exec_command(
        focus_dir=tmp_path,
        prompt="return terminal payload",
        output_last_message_path=tmp_path / "last.json",
    )

    assert command[:6] == [
        "codex",
        "exec",
        "--json",
        "--sandbox",
        "danger-full-access",
        "--skip-git-repo-check",
    ]
    assert "--model" in command
    assert "gpt-5.4-mini" in command
