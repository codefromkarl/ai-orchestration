from pathlib import Path

from taskplane.wrap_cli import main


def test_wrap_cli_executes_shadow_capture_and_prints_summary(monkeypatch, capsys):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}

    class FakeResult:
        work_id = "adhoc-1"
        status = "done"

    def fake_repository_builder(*, dsn: str):
        captured["dsn"] = dsn
        return object()

    def fake_capture(**kwargs):
        captured.update(kwargs)
        return FakeResult()

    exit_code = main(
        [
            "--repo",
            "codefromkarl/stardrifter",
            "--title",
            "shadow captured task",
            "--workdir",
            "/tmp/project",
            "--prompt",
            "fix bug and add tests",
            "--executor",
            "codex",
            "--",
            "codex",
            "exec",
            "fix bug",
        ],
        repository_builder=fake_repository_builder,
        capture_runner=fake_capture,
    )

    assert exit_code == 0
    assert captured["dsn"] == "postgresql://user:pass@localhost:5432/stardrifter"
    assert captured["repo"] == "codefromkarl/stardrifter"
    assert captured["title"] == "shadow captured task"
    assert captured["workdir"] == "/tmp/project"
    assert captured["prompt"] == "fix bug and add tests"
    assert captured["worker_name"] == "shadow-wrap:codex"
    assert captured["command"] == ["codex", "exec", "fix bug"]
    assert capsys.readouterr().out == "captured adhoc-1 -> done\n"


def test_wrap_cli_passes_transcript_and_assistant_summary(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(
        "TASKPLANE_DSN",
        "postgresql://user:pass@localhost:5432/stardrifter",
    )
    captured: dict[str, object] = {}
    transcript_path = tmp_path / "transcript.md"
    transcript_path.write_text("assistant transcript", encoding="utf-8")

    class FakeResult:
        work_id = "adhoc-2"
        status = "done"

    def fake_capture(**kwargs):
        captured.update(kwargs)
        return FakeResult()

    exit_code = main(
        [
            "--repo",
            "codefromkarl/stardrifter",
            "--title",
            "shadow captured task",
            "--workdir",
            "/tmp/project",
            "--assistant-summary",
            "implemented fix and tests passed",
            "--transcript-file",
            str(transcript_path),
            "--",
            "codex",
            "exec",
            "fix bug",
        ],
        repository_builder=lambda *, dsn: object(),
        capture_runner=fake_capture,
    )

    assert exit_code == 0
    assert captured["assistant_summary"] == "implemented fix and tests passed"
    assert captured["transcript_text"] == "assistant transcript"
    assert captured["transcript_path"] == str(Path(transcript_path).resolve())
    assert capsys.readouterr().out == "captured adhoc-2 -> done\n"
