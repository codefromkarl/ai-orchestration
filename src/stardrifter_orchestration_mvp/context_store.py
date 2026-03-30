"""
AI Conversation Context Store

AI 对话上下文持久化存储模块。
支持：
- 保存对话历史
- 获取历史上下文用于 resume
- 自动压缩对话摘要（每 10 轮）
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from .models import AIConversationSummary, AIConversationTurn


@dataclass
class ContextStore:
    """AI 对话上下文存储"""

    dsn: str

    def save_turn(
        self,
        work_id: str,
        role: Literal["user", "assistant", "system"],
        content: str,
        metadata: dict | None = None,
    ) -> str:
        """
        保存一轮对话

        Args:
            work_id: 工作项 ID
            role: 角色 (user/assistant/system)
            content: 对话内容
            metadata: 元数据

        Returns:
            turn_id: 对话轮次 ID
        """
        turn_id = self._generate_turn_id(work_id, content)

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                # 获取当前最大 turn_index
                cur.execute(
                    """
                    SELECT COALESCE(MAX(turn_index), -1) as max_index
                    FROM ai_conversation_turn
                    WHERE work_id = %s
                    """,
                    (work_id,),
                )
                row = cur.fetchone()
                next_index = (row["max_index"] + 1) if row else 0

                # 插入新对话
                cur.execute(
                    """
                    INSERT INTO ai_conversation_turn (id, work_id, role, content, turn_index, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        turn_id,
                        work_id,
                        role,
                        content,
                        next_index,
                        metadata or {},
                    ),
                )

                # 检查是否需要压缩摘要
                if (next_index + 1) % 10 == 0:
                    self._compress_summary(conn, work_id, next_index)

        return turn_id

    def get_conversation_history(
        self,
        work_id: str,
        limit: int = 50,
        include_summary: bool = True,
    ) -> list[AIConversationTurn]:
        """
        获取历史对话

        Args:
            work_id: 工作项 ID
            limit: 最多返回轮次数量
            include_summary: 是否包含摘要

        Returns:
            对话轮次列表
        """
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, work_id, role, content, turn_index, metadata, created_at
                    FROM ai_conversation_turn
                    WHERE work_id = %s
                    ORDER BY turn_index DESC
                    LIMIT %s
                    """,
                    (work_id, limit),
                )
                rows = cur.fetchall()

                # 反转顺序
                rows.reverse()

                return [
                    AIConversationTurn(
                        id=row["id"],
                        work_id=row["work_id"],
                        role=row["role"],
                        content=row["content"],
                        turn_index=row["turn_index"],
                        metadata=row["metadata"] or {},
                        created_at=row["created_at"],
                    )
                    for row in rows
                ]

    def get_summary(self, work_id: str) -> AIConversationSummary | None:
        """
        获取对话摘要

        Args:
            work_id: 工作项 ID

        Returns:
            对话摘要，如果不存在则返回 None
        """
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT summary, turn_count, last_turn_index, updated_at
                    FROM ai_conversation_summary
                    WHERE work_id = %s
                    """,
                    (work_id,),
                )
                row = cur.fetchone()

                if row is None:
                    return None

                return AIConversationSummary(
                    work_id=work_id,
                    summary=row["summary"],
                    turn_count=row["turn_count"],
                    last_turn_index=row["last_turn_index"],
                    updated_at=row["updated_at"],
                )

    def get_full_context(self, work_id: str) -> tuple[list[AIConversationTurn], AIConversationSummary | None]:
        """
        获取完整上下文（摘要 + 历史）

        Args:
            work_id: 工作项 ID

        Returns:
            (对话历史，对话摘要)
        """
        history = self.get_conversation_history(work_id, limit=20)
        summary = self.get_summary(work_id)
        return history, summary

    def clear_history(self, work_id: str) -> None:
        """清除对话历史"""
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM ai_conversation_turn WHERE work_id = %s",
                    (work_id,),
                )
                cur.execute(
                    "DELETE FROM ai_conversation_summary WHERE work_id = %s",
                    (work_id,),
                )

    def _generate_turn_id(self, work_id: str, content: str) -> str:
        """生成对话 ID"""
        timestamp = datetime.utcnow().isoformat()
        raw = f"{work_id}:{timestamp}:{content[:100]}"
        return f"turn_{hashlib.sha256(raw.encode()).hexdigest()[:16]}"

    def _compress_summary(
        self,
        conn: psycopg.Connection,
        work_id: str,
        current_turn_index: int,
    ) -> None:
        """
        压缩对话摘要

        在实际使用中，这里应该调用 AI 模型来生成摘要。
        当前实现使用简单的拼接方式。
        """
        with conn.cursor() as cur:
            # 获取最近 10 轮对话
            cur.execute(
                """
                SELECT role, content
                FROM ai_conversation_turn
                WHERE work_id = %s AND turn_index > %s
                ORDER BY turn_index
                """,
                (work_id, current_turn_index - 10),
            )
            rows = cur.fetchall()

            # 简单拼接摘要（实际应该用 AI 生成）
            summary_parts = []
            for row in rows:
                summary_parts.append(f"[{row['role']}: {row['content'][:200]}...]")

            summary = "\n".join(summary_parts)

            # 更新或插入摘要
            cur.execute(
                """
                INSERT INTO ai_conversation_summary (work_id, summary, turn_count, last_turn_index)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (work_id) DO UPDATE SET
                    summary = EXCLUDED.summary,
                    turn_count = EXCLUDED.turn_count,
                    last_turn_index = EXCLUDED.last_turn_index,
                    updated_at = NOW()
                """,
                (work_id, summary, 10, current_turn_index),
            )


# =============================================================================
# Repository 集成
# =============================================================================

def save_conversation_turn(
    conn: psycopg.Connection,
    work_id: str,
    role: Literal["user", "assistant", "system"],
    content: str,
    metadata: dict | None = None,
) -> str:
    """
    保存对话轮次（repository 集成版本）

    Args:
        conn: 数据库连接
        work_id: 工作项 ID
        role: 角色
        content: 内容
        metadata: 元数据

    Returns:
        turn_id
    """
    import hashlib
    from datetime import datetime

    turn_id = f"turn_{hashlib.sha256(f'{work_id}:{datetime.utcnow().isoformat()}'.encode()).hexdigest()[:16]}"

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(MAX(turn_index), -1) as max_index
            FROM ai_conversation_turn
            WHERE work_id = %s
            """,
            (work_id,),
        )
        row = cur.fetchone()
        next_index = (row["max_index"] + 1) if row else 0

        cur.execute(
            """
            INSERT INTO ai_conversation_turn (id, work_id, role, content, turn_index, metadata)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (turn_id, work_id, role, content, next_index, metadata or {}),
        )

    return turn_id


def get_conversation_history(
    conn: psycopg.Connection,
    work_id: str,
    limit: int = 50,
) -> list[dict]:
    """获取对话历史（repository 集成版本）"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, work_id, role, content, turn_index, metadata, created_at
            FROM ai_conversation_turn
            WHERE work_id = %s
            ORDER BY turn_index DESC
            LIMIT %s
            """,
            (work_id, limit),
        )
        rows = cur.fetchall()
        rows.reverse()
        return [dict(row) for row in rows]


def get_conversation_summary(
    conn: psycopg.Connection,
    work_id: str,
) -> dict | None:
    """获取对话摘要（repository 集成版本）"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT summary, turn_count, last_turn_index, updated_at
            FROM ai_conversation_summary
            WHERE work_id = %s
            """,
            (work_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
