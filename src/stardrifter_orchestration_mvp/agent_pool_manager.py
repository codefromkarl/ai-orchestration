"""
Agent Pool Manager - Agent 资源池管理器

实现混合分配策略：基础配额 + 弹性池
- 基础配额：每个 Repo 保证最小 Agent 数量
- 弹性池：共享剩余 Agent 资源，动态分配给最需要的 Repo
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
import logging

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


@dataclass
class RepoPriority:
    """Repo 优先级信息"""
    repo: str
    priority_score: float
    operator_attention_required: bool = False
    ready_task_count: int = 0
    active_agent_count: int = 0
    last_activity_at: datetime | None = None


@dataclass
class AgentInfo:
    """Agent 信息"""
    agent_id: str
    agent_name: str
    agent_type: str
    status: str
    assigned_repo: str | None = None
    current_work_id: str | None = None
    base_quota_repo: str | None = None
    last_heartbeat: datetime | None = None


class AgentPoolManager:
    """
    Agent 池管理器

    混合分配策略:
    1. 基础配额：每个 Repo 分配固定数量的 Agent
    2. 弹性池：剩余 Agent 根据优先级动态分配

    优先级计算:
    - operator_attention_required (最高优先级)
    - ready task 队列长度
    - 公平共享
    """

    def __init__(
        self,
        dsn: str,
        base_quota_per_repo: int = 2,
        elastic_pool_size: int = 8,
        max_extra_per_repo: int = 4,
        heartbeat_timeout_seconds: int = 120,
    ):
        self.dsn = dsn
        self.base_quota_per_repo = base_quota_per_repo
        self.elastic_pool_size = elastic_pool_size
        self.max_extra_per_repo = max_extra_per_repo
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds

    def allocate_agents(self, repos: list[str]) -> dict[str, int]:
        """
        分配 Agent 槽位

        分配逻辑:
        1. 满足基础配额
        2. 弹性池分配（优先级：operator_attention > queue_length > random）

        Returns:
            {repo: allocated_count}
        """
        if not repos:
            return {}

        allocation: dict[str, int] = {}

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            # 1. 满足基础配额
            for repo in repos:
                allocation[repo] = self.base_quota_per_repo

                # 确保 Repo 状态记录存在
                conn.execute("""
                    INSERT INTO global_execution_state (id, repo, created_at, updated_at)
                    VALUES (%s, %s, NOW(), NOW())
                    ON CONFLICT (id) DO NOTHING
                """, (repo, repo))

            # 2. 获取各 Repo 的当前状态
            rows = conn.execute("""
                SELECT repo, operator_attention_required, ready_task_count, active_agent_count
                FROM global_execution_state
                WHERE repo = ANY(%s)
            """, (repos,)).fetchall()

            state_by_repo = {row["repo"]: row for row in rows}

            # 3. 计算优先级
            priorities = self._calculate_repo_priorities(state_by_repo)

            # 4. 弹性池分配
            remaining = self.elastic_pool_size
            for repo_priority in priorities:
                if remaining <= 0:
                    break

                repo = repo_priority.repo
                current_allocated = allocation.get(repo, 0)
                max_allowed = self.base_quota_per_repo + self.max_extra_per_repo

                extra = min(
                    remaining,
                    self.max_extra_per_repo,
                    max_allowed - current_allocated,
                )
                if extra > 0:
                    allocation[repo] = current_allocated + extra
                    remaining -= extra

        logger.info(f"Agent allocation complete: {allocation}")
        return allocation

    def _calculate_repo_priorities(
        self,
        state_by_repo: dict[str, dict[str, Any]],
    ) -> list[RepoPriority]:
        """
        计算 Repo 优先级

        优先级分数计算:
        - operator_attention_required: +1000
        - ready_task_count: +10 per task
        - lack_of_agents: +50 per missing agent
        """
        priorities: list[RepoPriority] = []

        for repo, state in state_by_repo.items():
            score = 0.0

            # 操作员注意（最高优先级）
            if state.get("operator_attention_required"):
                score += 1000

            # 待处理任务数量
            ready_count = state.get("ready_task_count", 0)
            score += ready_count * 10

            # 缺少 Agent（公平共享）
            current_agents = state.get("active_agent_count", 0)
            if current_agents < self.base_quota_per_repo:
                score += (self.base_quota_per_repo - current_agents) * 50

            priorities.append(RepoPriority(
                repo=repo,
                priority_score=score,
                operator_attention_required=bool(state.get("operator_attention_required")),
                ready_task_count=ready_count,
                active_agent_count=current_agents,
            ))

        # 按优先级降序排序
        priorities.sort(key=lambda p: p.priority_score, reverse=True)
        return priorities

    def register_agent(
        self,
        agent_name: str,
        agent_type: str,
        agent_id: str | None = None,
    ) -> str:
        """
        注册 Agent 到资源池

        Returns:
            agent_id
        """
        if agent_id is None:
            agent_id = f"agent-{uuid.uuid4().hex[:8]}"

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            conn.execute("""
                INSERT INTO global_agent_pool
                (id, agent_name, agent_type, status, created_at, updated_at)
                VALUES (%s, %s, %s, 'idle', NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    agent_type = EXCLUDED.agent_type,
                    status = 'idle',
                    updated_at = NOW()
            """, (agent_id, agent_name, agent_type))

        logger.info(f"Registered agent: {agent_id} ({agent_name}, {agent_type})")
        return agent_id

    def assign_agent_to_repo(self, agent_id: str, repo: str) -> bool:
        """
        分配 Agent 到指定 Repo

        Returns:
            bool: 是否成功分配
        """
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            # 检查 Agent 是否存在
            row = conn.execute("""
                SELECT status FROM global_agent_pool WHERE id = %s
            """, (agent_id,)).fetchone()

            if row is None:
                logger.warning(f"Agent {agent_id} not found")
                return False

            if row["status"] == "offline":
                logger.warning(f"Agent {agent_id} is offline")
                return False

            # 分配 Agent
            conn.execute("""
                UPDATE global_agent_pool
                SET
                    assigned_repo = %s,
                    status = 'idle',
                    current_work_id = NULL,
                    updated_at = NOW()
                WHERE id = %s
            """, (repo, agent_id))

        logger.info(f"Assigned agent {agent_id} to repo {repo}")
        return True

    def assign_agent_to_work(self, agent_id: str, work_id: str) -> bool:
        """
        分配 Agent 到具体工作任务

        Returns:
            bool: 是否成功分配
        """
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            conn.execute("""
                UPDATE global_agent_pool
                SET
                    status = 'busy',
                    current_work_id = %s,
                    last_heartbeat_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s AND status != 'offline'
            """, (work_id, agent_id))

            return conn.rowcount > 0

    def release_agent(self, agent_id: str) -> bool:
        """
        释放 Agent（返回到资源池）

        Returns:
            bool: 是否成功释放
        """
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            conn.execute("""
                UPDATE global_agent_pool
                SET
                    status = 'idle',
                    current_work_id = NULL,
                    assigned_repo = NULL,
                    last_heartbeat_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
            """, (agent_id,))

            return conn.rowcount > 0

    def health_check(self) -> dict[str, list[str]]:
        """
        健康检查

        Returns:
            {status: [agent_ids]}
        """
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            timeout_threshold = datetime.now() - timedelta(
                seconds=self.heartbeat_timeout_seconds
            )

            rows = conn.execute("""
                SELECT id, status, last_heartbeat_at
                FROM global_agent_pool
                ORDER BY status, id
            """).fetchall()

        result: dict[str, list[str]] = {
            "idle": [],
            "busy": [],
            "offline": [],
            "stale": [],
        }

        for row in rows:
            agent_id = row["id"]
            status = row["status"]
            last_heartbeat = row["last_heartbeat_at"]

            # 检查心跳超时
            if status != "offline" and (
                last_heartbeat is None or last_heartbeat < timeout_threshold
            ):
                result["stale"].append(agent_id)
                continue

            if status in result:
                result[status].append(agent_id)

        return result

    def mark_agent_offline(self, agent_id: str) -> bool:
        """标记 Agent 为离线"""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            conn.execute("""
                UPDATE global_agent_pool
                SET status = 'offline', updated_at = NOW()
                WHERE id = %s
            """, (agent_id,))
            return conn.rowcount > 0

    def mark_agent_online(self, agent_id: str) -> bool:
        """标记 Agent 为在线"""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            conn.execute("""
                UPDATE global_agent_pool
                SET
                    status = 'idle',
                    last_heartbeat_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
            """, (agent_id,))
            return conn.rowcount > 0

    def update_heartbeat(self, agent_id: str) -> bool:
        """更新 Agent 心跳"""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            conn.execute("""
                UPDATE global_agent_pool
                SET last_heartbeat_at = NOW(), updated_at = NOW()
                WHERE id = %s AND status != 'offline'
            """, (agent_id,))
            return conn.rowcount > 0

    def get_agent_status(self, agent_id: str) -> AgentInfo | None:
        """获取 Agent 状态"""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            row = conn.execute("""
                SELECT * FROM v_agent_status WHERE id = %s
            """, (agent_id,)).fetchone()

        if row is None:
            return None

        return AgentInfo(
            agent_id=row["id"],
            agent_name=row["agent_name"],
            agent_type=row["agent_type"],
            status=row["status"],
            assigned_repo=row["assigned_repo"],
            current_work_id=row["current_work_id"],
            base_quota_repo=row["base_quota_repo"],
            last_heartbeat=row["last_heartbeat_at"],
        )

    def list_available_agents(self, repo: str | None = None) -> list[AgentInfo]:
        """列出可用 Agent"""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            if repo:
                rows = conn.execute("""
                    SELECT * FROM v_agent_status
                    WHERE status = 'idle'
                      AND (assigned_repo = %s OR assigned_repo IS NULL)
                    ORDER BY agent_name
                """, (repo,)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM v_agent_status
                    WHERE status = 'idle'
                    ORDER BY agent_name
                """).fetchall()

        return [
            AgentInfo(
                agent_id=row["id"],
                agent_name=row["agent_name"],
                agent_type=row["agent_type"],
                status=row["status"],
                assigned_repo=row["assigned_repo"],
                current_work_id=row["current_work_id"],
                base_quota_repo=row["base_quota_repo"],
                last_heartbeat=row["last_heartbeat_at"],
            )
            for row in rows
        ]

    def get_allocation_stats(self) -> dict[str, Any]:
        """获取分配统计信息"""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            # 总体统计
            pool_stats = conn.execute(
                "SELECT * FROM v_global_agent_pool_status"
            ).fetchone()

            # 按 Repo 分配
            allocation_stats = conn.execute("""
                SELECT * FROM v_repo_agent_allocation
            """).fetchall()

        return {
            "pool_stats": dict(pool_stats) if pool_stats else {},
            "allocation_by_repo": [dict(row) for row in allocation_stats],
        }
