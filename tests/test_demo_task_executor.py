from __future__ import annotations

import json
import os
from pathlib import Path


def test_demo_task_executor_writes_file_and_emits_changed_paths(tmp_path, monkeypatch, capsys):
    from taskplane.demo_task_executor import main
    from taskplane.execution_protocol import EXECUTION_RESULT_MARKER

    monkeypatch.setenv("TASKPLANE_WORK_ID", "issue-900")
    monkeypatch.setenv("TASKPLANE_WORK_TITLE", "Frontend demo")
    monkeypatch.setenv("TASKPLANE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv(
        "TASKPLANE_EXECUTION_CONTEXT_JSON",
        json.dumps(
            {
                "planned_paths": ["frontend/src/"],
            }
        ),
    )

    exit_code = main()

    assert exit_code == 0
    output = capsys.readouterr().out.strip()
    assert output.startswith(EXECUTION_RESULT_MARKER)
    payload = json.loads(output[len(EXECUTION_RESULT_MARKER) :])
    changed_path = payload["changed_paths"][0]
    assert changed_path.startswith("frontend/src/")
    assert (tmp_path / changed_path).exists()
    assert payload["outcome"] == "done"


def test_demo_task_executor_falls_back_to_examples_directory(tmp_path, monkeypatch, capsys):
    from taskplane.demo_task_executor import main
    from taskplane.execution_protocol import EXECUTION_RESULT_MARKER

    monkeypatch.setenv("TASKPLANE_WORK_ID", "issue-901")
    monkeypatch.setenv("TASKPLANE_WORK_TITLE", "Generic demo")
    monkeypatch.setenv("TASKPLANE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("TASKPLANE_EXECUTION_CONTEXT_JSON", raising=False)

    exit_code = main()

    assert exit_code == 0
    output = capsys.readouterr().out.strip()
    payload = json.loads(output[len(EXECUTION_RESULT_MARKER) :])
    assert payload["changed_paths"] == ["examples/taskplane-demo/issue-901.md"]
    assert (tmp_path / "examples" / "taskplane-demo" / "issue-901.md").exists()
