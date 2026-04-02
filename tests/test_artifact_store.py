from pathlib import Path
from unittest.mock import MagicMock, patch

from taskplane.artifact_store import (
    ArtifactRecord,
    ArtifactStore,
    _guess_extension,
    _guess_mime_type,
    summarize_artifacts_for_prompt,
)


def _mock_connect(mock_connect, fetchone_result=None, fetchall_result=None):
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    if fetchone_result is not None:
        mock_cursor.fetchone.return_value = fetchone_result
    if fetchall_result is not None:
        mock_cursor.fetchall.return_value = fetchall_result
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_connect.return_value = mock_conn
    return mock_conn, mock_cursor


def test_artifact_store_stores_and_records(tmp_path):
    store = ArtifactStore(
        dsn="postgresql://fake:fake@localhost/fake", base_dir=tmp_path
    )

    with patch(
        "taskplane.artifact_store.psycopg.connect"
    ) as mock_connect:
        _mock_connect(
            mock_connect, fetchone_result={"id": 1, "created_at": "2026-01-01T00:00:00"}
        )

        record = store.store_and_record(
            work_id="task-123",
            artifact_type="failure_report",
            content='{"reason": "test"}',
            run_id=42,
            sequence=1,
        )

        assert record.id == 1
        assert record.work_id == "task-123"
        assert record.artifact_type == "failure_report"
        assert record.artifact_key == "task-123/failure_report/01.json"
        assert record.content_size_bytes > 0
        assert record.mime_type == "application/json"

        stored_file = tmp_path / record.artifact_key
        assert stored_file.exists()
        assert stored_file.read_bytes() == b'{"reason": "test"}'


def test_artifact_store_record_reference(tmp_path):
    store = ArtifactStore(
        dsn="postgresql://fake:fake@localhost/fake", base_dir=tmp_path
    )

    with patch(
        "taskplane.artifact_store.psycopg.connect"
    ) as mock_connect:
        _mock_connect(
            mock_connect, fetchone_result={"id": 2, "created_at": "2026-01-01T00:00:00"}
        )

        record = store.record_reference(
            work_id="task-456",
            artifact_type="patch_proposal",
            storage_path=str(tmp_path / "patch.diff"),
            content_digest="abc123",
            content_size_bytes=1024,
            run_id=10,
            sequence=1,
        )

        assert record.artifact_key == "task-456/patch_proposal/01.diff"
        assert record.content_digest == "abc123"


def test_artifact_store_lookup(tmp_path):
    store = ArtifactStore(
        dsn="postgresql://fake:fake@localhost/fake", base_dir=tmp_path
    )

    with patch(
        "taskplane.artifact_store.psycopg.connect"
    ) as mock_connect:
        _mock_connect(
            mock_connect,
            fetchall_result=[
                {
                    "id": 1,
                    "work_id": "task-123",
                    "run_id": 42,
                    "session_id": None,
                    "artifact_type": "failure_report",
                    "artifact_key": "task-123/failure_report/01.json",
                    "storage_path": str(tmp_path / "report.json"),
                    "content_digest": "sha256",
                    "content_size_bytes": 100,
                    "mime_type": "application/json",
                    "metadata": {},
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
        )

        results = store.lookup(work_id="task-123", artifact_type="failure_report")

        assert len(results) == 1
        assert results[0].artifact_key == "task-123/failure_report/01.json"


def test_artifact_store_list_by_type(tmp_path):
    store = ArtifactStore(
        dsn="postgresql://fake:fake@localhost/fake", base_dir=tmp_path
    )

    with patch(
        "taskplane.artifact_store.psycopg.connect"
    ) as mock_connect:
        _mock_connect(
            mock_connect,
            fetchall_result=[
                {
                    "id": 1,
                    "work_id": "task-123",
                    "run_id": 42,
                    "session_id": None,
                    "artifact_type": "patch_proposal",
                    "artifact_key": "task-123/patch_proposal/01.diff",
                    "storage_path": str(tmp_path / "patch.diff"),
                    "content_digest": "sha256",
                    "content_size_bytes": 500,
                    "mime_type": "text/x-diff",
                    "metadata": {"model": "claude"},
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
        )

        results = store.list_by_type(artifact_type="patch_proposal", work_id="task-123")

        assert len(results) == 1
        assert results[0].metadata["model"] == "claude"


def test_artifact_store_read_content(tmp_path):
    store = ArtifactStore(
        dsn="postgresql://fake:fake@localhost/fake", base_dir=tmp_path
    )
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello world")

    with patch(
        "taskplane.artifact_store.psycopg.connect"
    ) as mock_connect:
        _mock_connect(mock_connect, fetchone_result={"storage_path": str(test_file)})

        content = store.read_content("task-123/custom/01.txt")
        assert content == b"hello world"


def test_artifact_store_read_content_missing_key(tmp_path):
    store = ArtifactStore(
        dsn="postgresql://fake:fake@localhost/fake", base_dir=tmp_path
    )

    with patch(
        "taskplane.artifact_store.psycopg.connect"
    ) as mock_connect:
        _mock_connect(mock_connect, fetchone_result=None)

        content = store.read_content("nonexistent/key")
        assert content is None


def test_artifact_store_get_latest_by_key(tmp_path):
    store = ArtifactStore(
        dsn="postgresql://fake:fake@localhost/fake", base_dir=tmp_path
    )

    with patch(
        "taskplane.artifact_store.psycopg.connect"
    ) as mock_connect:
        _mock_connect(
            mock_connect,
            fetchone_result={
                "id": 3,
                "work_id": "task-789",
                "run_id": 99,
                "session_id": None,
                "artifact_type": "screenshot",
                "artifact_key": "task-789/screenshot/01.png",
                "storage_path": str(tmp_path / "shot.png"),
                "content_digest": "sha256",
                "content_size_bytes": 2048,
                "mime_type": "image/png",
                "metadata": {},
                "created_at": "2026-01-01T00:00:00",
            },
        )

        record = store.get_latest_by_key("task-789/screenshot/01.png")

        assert record is not None
        assert record.artifact_type == "screenshot"
        assert record.mime_type == "image/png"


def test_artifact_store_get_latest_by_key_not_found(tmp_path):
    store = ArtifactStore(
        dsn="postgresql://fake:fake@localhost/fake", base_dir=tmp_path
    )

    with patch(
        "taskplane.artifact_store.psycopg.connect"
    ) as mock_connect:
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchone.return_value = None
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        record = store.get_latest_by_key("nonexistent")
        assert record is None


def test_guess_extension_from_mime():
    assert _guess_extension("screenshot", "image/png") == "png"


def test_summarize_artifacts_for_prompt_uses_metadata_summary_when_present():
    artifacts = [
        ArtifactRecord(
            id=1,
            work_id="task-123",
            artifact_type="task_summary",
            artifact_key="task-123/task_summary/01.json",
            storage_path="/tmp/task-123/task_summary/01.json",
            content_digest="sha256",
            content_size_bytes=256,
            mime_type="application/json",
            metadata={"summary": "边界收口与回归测试结果"},
        )
    ]

    text = summarize_artifacts_for_prompt(artifacts, max_chars=200)

    assert "task-123/task_summary/01.json" in text
    assert "边界收口与回归测试结果" in text


def test_summarize_artifacts_for_prompt_respects_limit_and_budget():
    artifacts = [
        ArtifactRecord(
            id=i,
            work_id="task-123",
            artifact_type="stdout",
            artifact_key=f"task-123/stdout/{i:02d}.txt",
            storage_path=f"/tmp/task-123/stdout/{i:02d}.txt",
            content_digest=f"sha256-{i}",
            content_size_bytes=2048,
            mime_type="text/plain",
            metadata={"summary": "x" * 120},
        )
        for i in range(1, 5)
    ]

    text = summarize_artifacts_for_prompt(artifacts, max_chars=160, limit=2)

    assert "02.txt" in text
    assert "03.txt" not in text
    assert len(text) <= 160
    assert _guess_extension("failure_report", "application/json") == "json"
    assert _guess_extension("html_dump", "text/html") == "html"


def test_guess_extension_from_type():
    assert _guess_extension("patch_proposal", None) == "diff"
    assert _guess_extension("verification_result", None) == "json"
    assert _guess_extension("diff_snapshot", None) == "diff"
    assert _guess_extension("custom", None) == "bin"


def test_guess_mime_type():
    assert _guess_mime_type("screenshot") == "image/png"
    assert _guess_mime_type("patch_proposal") == "text/x-diff"
    assert _guess_mime_type("failure_report") == "application/json"
    assert _guess_mime_type("custom") == "application/octet-stream"


def test_artifact_store_binary_content(tmp_path):
    store = ArtifactStore(
        dsn="postgresql://fake:fake@localhost/fake", base_dir=tmp_path
    )

    with patch(
        "taskplane.artifact_store.psycopg.connect"
    ) as mock_connect:
        _mock_connect(
            mock_connect, fetchone_result={"id": 5, "created_at": "2026-01-01T00:00:00"}
        )

        binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        record = store.store_and_record(
            work_id="task-123",
            artifact_type="screenshot",
            content=binary_data,
            sequence=1,
        )

        assert record.content_size_bytes == len(binary_data)
        stored_file = tmp_path / record.artifact_key
        assert stored_file.read_bytes() == binary_data
