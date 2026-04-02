from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class DeadLetterRecord:
    id: int | None
    work_id: str
    original_status: str
    failure_reason: str
    attempt_count: int
    last_run_id: int | None
    moved_at: str
    moved_by: str
    resolution: str | None = None
    resolved_at: str | None = None
    resolved_by: str | None = None


class DeadLetterQueue:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def move_to_dlq(
        self,
        *,
        work_id: str,
        original_status: str,
        failure_reason: str,
        attempt_count: int,
        last_run_id: int | None = None,
        moved_by: str = "system",
    ) -> DeadLetterRecord:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO dead_letter_queue
                        (work_id, original_status, failure_reason, attempt_count, last_run_id, moved_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, moved_at
                    """,
                    (
                        work_id,
                        original_status,
                        failure_reason,
                        attempt_count,
                        last_run_id,
                        moved_by,
                    ),
                )
                row = cur.fetchone()
                return DeadLetterRecord(
                    id=row["id"],
                    work_id=work_id,
                    original_status=original_status,
                    failure_reason=failure_reason,
                    attempt_count=attempt_count,
                    last_run_id=last_run_id,
                    moved_at=str(row["moved_at"]),
                    moved_by=moved_by,
                )

    def resolve(
        self,
        *,
        dlq_id: int,
        resolution: str,
        resolved_by: str,
    ) -> bool:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE dead_letter_queue
                    SET resolution = %s, resolved_by = %s, resolved_at = NOW()
                    WHERE id = %s AND resolution IS NULL
                    """,
                    (resolution, resolved_by, dlq_id),
                )
                return cur.rowcount > 0

    def list_unresolved(self, limit: int = 50) -> list[DeadLetterRecord]:
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, work_id, original_status, failure_reason,
                           attempt_count, last_run_id, moved_at, moved_by,
                           resolution, resolved_at, resolved_by
                    FROM dead_letter_queue
                    WHERE resolution IS NULL
                    ORDER BY moved_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [
                    DeadLetterRecord(
                        id=row["id"],
                        work_id=row["work_id"],
                        original_status=row["original_status"],
                        failure_reason=row["failure_reason"],
                        attempt_count=row["attempt_count"],
                        last_run_id=row["last_run_id"],
                        moved_at=str(row["moved_at"]),
                        moved_by=row["moved_by"],
                        resolution=row["resolution"],
                        resolved_at=str(row["resolved_at"])
                        if row["resolved_at"]
                        else None,
                        resolved_by=row["resolved_by"],
                    )
                    for row in cur.fetchall()
                ]
