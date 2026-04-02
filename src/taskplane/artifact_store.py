from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, BinaryIO

import psycopg
from psycopg.rows import dict_row

ARTIFACT_BASE_DIR = Path(
    os.environ.get("TASKPLANE_ARTIFACT_DIR", ".run-logs/artifacts")
)

ArtifactType = str


@dataclass(frozen=True)
class ArtifactRecord:
    id: int | None
    work_id: str
    artifact_type: ArtifactType
    artifact_key: str
    storage_path: str
    content_digest: str
    content_size_bytes: int
    mime_type: str
    metadata: dict[str, Any]
    run_id: int | None = None
    session_id: str | None = None
    created_at: str | None = None


@dataclass
class ArtifactStore:
    dsn: str
    base_dir: Path = field(default_factory=lambda: ARTIFACT_BASE_DIR)

    def __post_init__(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def store_and_record(
        self,
        *,
        work_id: str,
        artifact_type: ArtifactType,
        content: bytes | str,
        run_id: int | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        mime_type: str | None = None,
        sequence: int = 1,
    ) -> ArtifactRecord:
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = content

        digest = hashlib.sha256(content_bytes).hexdigest()
        ext = _guess_extension(artifact_type, mime_type)
        artifact_key = f"{work_id}/{artifact_type}/{sequence:02d}.{ext}"
        storage_path = str(self.base_dir / artifact_key)

        Path(storage_path).parent.mkdir(parents=True, exist_ok=True)
        Path(storage_path).write_bytes(content_bytes)

        record = ArtifactRecord(
            id=None,
            work_id=work_id,
            artifact_type=artifact_type,
            artifact_key=artifact_key,
            storage_path=storage_path,
            content_digest=digest,
            content_size_bytes=len(content_bytes),
            mime_type=mime_type or _guess_mime_type(artifact_type),
            metadata=metadata or {},
            run_id=run_id,
            session_id=session_id,
        )

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO artifact
                        (work_id, run_id, session_id, artifact_type, artifact_key,
                         storage_path, content_digest, content_size_bytes, mime_type, metadata)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, created_at
                    """,
                    (
                        work_id,
                        run_id,
                        session_id,
                        artifact_type,
                        artifact_key,
                        storage_path,
                        digest,
                        len(content_bytes),
                        record.mime_type,
                        record.metadata,
                    ),
                )
                row = cur.fetchone()
                record = replace(
                    record, id=row["id"], created_at=str(row["created_at"])
                )

        return record

    def record_reference(
        self,
        *,
        work_id: str,
        artifact_type: ArtifactType,
        storage_path: str,
        content_digest: str,
        content_size_bytes: int = 0,
        run_id: int | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        mime_type: str | None = None,
        sequence: int = 1,
    ) -> ArtifactRecord:
        ext = _guess_extension(artifact_type, mime_type)
        artifact_key = f"{work_id}/{artifact_type}/{sequence:02d}.{ext}"

        record = ArtifactRecord(
            id=None,
            work_id=work_id,
            artifact_type=artifact_type,
            artifact_key=artifact_key,
            storage_path=storage_path,
            content_digest=content_digest,
            content_size_bytes=content_size_bytes,
            mime_type=mime_type or _guess_mime_type(artifact_type),
            metadata=metadata or {},
            run_id=run_id,
            session_id=session_id,
        )

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO artifact
                        (work_id, run_id, session_id, artifact_type, artifact_key,
                         storage_path, content_digest, content_size_bytes, mime_type, metadata)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, created_at
                    """,
                    (
                        work_id,
                        run_id,
                        session_id,
                        artifact_type,
                        artifact_key,
                        storage_path,
                        content_digest,
                        content_size_bytes,
                        record.mime_type,
                        record.metadata,
                    ),
                )
                row = cur.fetchone()
                record = replace(
                    record, id=row["id"], created_at=str(row["created_at"])
                )

        return record

    def lookup(
        self,
        *,
        work_id: str,
        artifact_type: ArtifactType | None = None,
        limit: int = 50,
    ) -> list[ArtifactRecord]:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                if artifact_type:
                    cur.execute(
                        """
                        SELECT id, work_id, run_id, session_id, artifact_type,
                               artifact_key, storage_path, content_digest,
                               content_size_bytes, mime_type, metadata, created_at
                        FROM artifact
                        WHERE work_id = %s AND artifact_type = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (work_id, artifact_type, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, work_id, run_id, session_id, artifact_type,
                               artifact_key, storage_path, content_digest,
                               content_size_bytes, mime_type, metadata, created_at
                        FROM artifact
                        WHERE work_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (work_id, limit),
                    )
                rows = cur.fetchall()

        return [
            ArtifactRecord(
                id=row["id"],
                work_id=row["work_id"],
                artifact_type=row["artifact_type"],
                artifact_key=row["artifact_key"],
                storage_path=row["storage_path"],
                content_digest=row["content_digest"],
                content_size_bytes=row["content_size_bytes"],
                mime_type=row["mime_type"],
                metadata=row["metadata"] or {},
                run_id=row["run_id"],
                session_id=row["session_id"],
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def read_content(self, artifact_key: str) -> bytes | None:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT storage_path FROM artifact WHERE artifact_key = %s",
                    (artifact_key,),
                )
                row = cur.fetchone()

        if row is None:
            return None

        path = Path(row["storage_path"])
        if not path.exists():
            return None

        return path.read_bytes()

    def list_by_type(
        self,
        *,
        artifact_type: ArtifactType,
        work_id: str | None = None,
        limit: int = 50,
    ) -> list[ArtifactRecord]:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                if work_id:
                    cur.execute(
                        """
                        SELECT id, work_id, run_id, session_id, artifact_type,
                               artifact_key, storage_path, content_digest,
                               content_size_bytes, mime_type, metadata, created_at
                        FROM artifact
                        WHERE artifact_type = %s AND work_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (artifact_type, work_id, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, work_id, run_id, session_id, artifact_type,
                               artifact_key, storage_path, content_digest,
                               content_size_bytes, mime_type, metadata, created_at
                        FROM artifact
                        WHERE artifact_type = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (artifact_type, limit),
                    )
                rows = cur.fetchall()

        return [
            ArtifactRecord(
                id=row["id"],
                work_id=row["work_id"],
                artifact_type=row["artifact_type"],
                artifact_key=row["artifact_key"],
                storage_path=row["storage_path"],
                content_digest=row["content_digest"],
                content_size_bytes=row["content_size_bytes"],
                mime_type=row["mime_type"],
                metadata=row["metadata"] or {},
                run_id=row["run_id"],
                session_id=row["session_id"],
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def get_latest_by_key(self, artifact_key: str) -> ArtifactRecord | None:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, work_id, run_id, session_id, artifact_type,
                           artifact_key, storage_path, content_digest,
                           content_size_bytes, mime_type, metadata, created_at
                    FROM artifact
                    WHERE artifact_key = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (artifact_key,),
                )
                row = cur.fetchone()

        if row is None:
            return None

        return ArtifactRecord(
            id=row["id"],
            work_id=row["work_id"],
            artifact_type=row["artifact_type"],
            artifact_key=row["artifact_key"],
            storage_path=row["storage_path"],
            content_digest=row["content_digest"],
            content_size_bytes=row["content_size_bytes"],
            mime_type=row["mime_type"],
            metadata=row["metadata"] or {},
            run_id=row["run_id"],
            session_id=row["session_id"],
            created_at=str(row["created_at"]),
        )


def _guess_extension(artifact_type: str, mime_type: str | None) -> str:
    if mime_type:
        mapping = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/webp": "webp",
            "application/json": "json",
            "text/html": "html",
            "text/plain": "txt",
            "text/x-diff": "diff",
        }
        if mime_type in mapping:
            return mapping[mime_type]

    type_ext = {
        "screenshot": "png",
        "trace": "json",
        "patch_proposal": "diff",
        "failure_report": "json",
        "verification_result": "json",
        "html_dump": "html",
        "diff_snapshot": "diff",
        "llm_analysis": "json",
        "task_summary": "json",
        "stdout": "txt",
        "stderr": "txt",
        "custom": "bin",
    }
    return type_ext.get(artifact_type, "bin")


def _guess_mime_type(artifact_type: str) -> str:
    mapping = {
        "screenshot": "image/png",
        "trace": "application/json",
        "patch_proposal": "text/x-diff",
        "failure_report": "application/json",
        "verification_result": "application/json",
        "html_dump": "text/html",
        "diff_snapshot": "text/x-diff",
        "llm_analysis": "application/json",
        "task_summary": "application/json",
        "stdout": "text/plain",
        "stderr": "text/plain",
        "custom": "application/octet-stream",
    }
    return mapping.get(artifact_type, "application/octet-stream")


def summarize_artifacts_for_prompt(
    artifacts: list[ArtifactRecord],
    *,
    max_chars: int = 1200,
    limit: int = 5,
) -> str:
    if not artifacts or max_chars <= 0 or limit <= 0:
        return ""

    lines: list[str] = []
    for artifact in artifacts[:limit]:
        summary = str(artifact.metadata.get("summary") or "").strip()
        if len(summary) > 48:
            summary = summary[:45].rstrip() + "..."
        size_part = (
            f" ({artifact.content_size_bytes} bytes)"
            if artifact.content_size_bytes > 0
            else ""
        )
        line = f"- {artifact.artifact_key}{size_part}"
        if summary:
            line += f": {summary}"
        lines.append(line)

    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return "." * max_chars
    return text[: max_chars - 3].rstrip() + "..."
