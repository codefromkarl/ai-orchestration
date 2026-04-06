import json

from pathlib import Path

from taskplane.opencode_epic_decomposer import (
    _build_prompt,
    _extract_result_payload,
    main,
)


def test_extract_result_payload_prefers_marker_payload_over_trailing_step_json():
    output = "\n".join(
        [
            '{"type":"step_start"}',
            'TASKPLANE_DECOMPOSITION_RESULT_JSON={"outcome":"blocked","summary":"awaiting repository context","reason_code":"awaiting_repository_context"}',
            '{"type":"step_finish","reason":"stop"}',
        ]
    )

    payload = _extract_result_payload(output)

    assert payload == {
        "outcome": "blocked",
        "summary": "awaiting repository context",
        "reason_code": "awaiting_repository_context",
    }


def test_extract_result_payload_reads_json_embedded_in_text_event():
    embedded = json.dumps(
        {
            "outcome": "blocked",
            "summary": "awaiting repository context",
            "reason_code": "awaiting_repository_context",
        },
        ensure_ascii=False,
    )
    output = "\n".join(
        [
            '{"type":"step_start"}',
            json.dumps(
                {"type": "text", "part": {"text": embedded}}, ensure_ascii=False
            ),
            '{"type":"step_finish","reason":"stop"}',
        ]
    )

    payload = _extract_result_payload(output)

    assert payload == {
        "outcome": "blocked",
        "summary": "awaiting repository context",
        "reason_code": "awaiting_repository_context",
    }


def test_extract_result_payload_maps_deferred_text_to_blocked_reason():
    output = "Waiting on repository document discovery before I can continue."

    payload = _extract_result_payload(output)

    assert payload == {
        "outcome": "blocked",
        "summary": "decomposer attempted deferred/background-only reasoning instead of returning a final result",
        "reason_code": "deferred-result-not-allowed",
    }


def test_build_prompt_forbids_deferred_answers():
    prompt = _build_prompt(
        repo="codefromkarl/stardrifter",
        row={
            "issue_number": 64,
            "title": "[Epic][Lane 09] Unified Bridge API 统一桥接层",
            "epic_story_count": 0,
            "body": "epic body",
        },
        project_dir=Path("/tmp/project"),
    )

    assert "你必须在本次回答中直接给出最终 JSON 结果" in prompt
    assert "禁止回答‘我先去查文档/等待后台结果/稍后继续’" in prompt


def test_main_blocks_when_contextatlas_index_fails(monkeypatch, capsys, tmp_path):
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *args, **kwargs):
            return None

        def fetchone(self):
            return {
                "issue_number": 64,
                "title": "Epic",
                "lane": "lane:09",
                "body": "epic body",
                "epic_story_count": 0,
            }

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "taskplane.opencode_epic_decomposer.psycopg.connect",
        lambda *args, **kwargs: FakeConnection(),
    )
    monkeypatch.setattr(
        "taskplane.opencode_epic_decomposer.ensure_contextatlas_index_for_checkout",
        lambda project_dir, explicit_repo=None: "index failed",
    )
    monkeypatch.setenv("TASKPLANE_EPIC_ISSUE_NUMBER", "64")
    monkeypatch.setenv("TASKPLANE_EPIC_REPO", "codefromkarl/stardrifter")
    monkeypatch.setenv("TASKPLANE_DSN", "postgresql://example")
    monkeypatch.setenv("TASKPLANE_PROJECT_DIR", str(tmp_path))

    result = main()

    assert result == 1
    output = capsys.readouterr().out.strip()
    assert output.startswith("TASKPLANE_DECOMPOSITION_RESULT_JSON=")
    payload = json.loads(output.split("=", 1)[1])
    assert payload == {
        "outcome": "blocked",
        "summary": "contextatlas index failed: index failed",
        "reason_code": "contextatlas-index-failed",
    }
