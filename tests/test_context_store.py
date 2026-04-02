from __future__ import annotations

from datetime import UTC, datetime

from taskplane.artifact_store import ArtifactRecord
from taskplane.context_store import (
    build_resume_context_text,
)
from taskplane.models import (
    AIConversationSummary,
    AIConversationTurn,
)


def test_build_resume_context_text_includes_summary_history_and_artifacts() -> None:
    summary = AIConversationSummary(
        work_id="task-1",
        summary="Decisions: use session runtime; Changes: normalized executor boundary",
        turn_count=12,
        last_turn_index=11,
        updated_at=datetime.now(UTC),
    )
    history = [
        AIConversationTurn(
            id="t1",
            work_id="task-1",
            role="user",
            content="先定位 session runtime 边界",
            turn_index=10,
        ),
        AIConversationTurn(
            id="t2",
            work_id="task-1",
            role="assistant",
            content="已收口为对象式 run_turn(request) 接口",
            turn_index=11,
        ),
    ]
    artifacts = [
        ArtifactRecord(
            id=1,
            work_id="task-1",
            artifact_type="task_summary",
            artifact_key="task-1/task_summary/01.json",
            storage_path="/tmp/task-1/task_summary/01.json",
            content_digest="abc123",
            content_size_bytes=120,
            mime_type="application/json",
            metadata={"summary": "记录了本轮边界收口与验证结论"},
        )
    ]

    text = build_resume_context_text(
        summary=summary,
        history=history,
        artifacts=artifacts,
        max_chars=1000,
    )

    assert "Summary:" in text
    assert "Recent turns:" in text
    assert "Artifacts:" in text
    assert "run_turn(request)" in text
    assert "task-1/task_summary/01.json" in text


def test_build_resume_context_text_respects_character_budget() -> None:
    history = [
        AIConversationTurn(
            id="t1",
            work_id="task-1",
            role="assistant",
            content="x" * 400,
            turn_index=0,
        )
    ]
    text = build_resume_context_text(
        summary=None,
        history=history,
        artifacts=[],
        max_chars=120,
    )

    assert len(text) <= 120
    assert text.endswith("...")
