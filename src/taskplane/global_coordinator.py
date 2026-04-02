"""
Global Coordinator - 多项目并行管理的全局协调器

核心职责:
1. 管理所有 Repo 的全局执行状态
2. 协调跨 Repo 的 Agent 资源分配
3. 提供全局并行度控制
4. 处理跨 Repo 的路径冲突
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol
import logging

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


@dataclass
class GlobalExecutionState:
    """全局执行状态"""
    repo: str
    active_agent_count: int = 0
    running_task_count: int = 0
    operator_attention_required: bool = False
    last_updated: datetime = field(default_factory=datetime.now)

    # 扩展字段（从视图获取）
    ready_task_count: int = 0
    blocked_task_count: int = 0
    in_progress_task_count: int = 0
    done_task_count: int = 0
    running_job_count: int = 0
    base_agent_count: int = 0
    elastic_agent_count: int = 0
    pending_notification_count: int = 0
    recent_decision_count: int = 0
    last_activity_at: datetime | None = None


@dataclass
class AgentSlot:
    """Agent 槽位信息"""
    agent_id: str
    agent_name: str
    agent_type: str
    status: str  # 'idle', 'busy', 'offline'
    assigned_repo: str | None = None
    current_work_id: str | None = None
    base_quota_repo: str | None = None
    last_heartbeat: datetime | None = None


class PathLockManager(Protocol):
    """路径锁管理器接口"""
    def acquire_lock(self, repo: str, path: str, work_id: str, duration_minutes: int = 30) -> bool: ...
    def release_lock(self, repo: str, path: str) -> bool: ...
    def is_locked(self, path: str) -> bool: ...
    def get_lock_holder(self, path: str) -> tuple[str, str] | None: ...


class GlobalCoordinator:
    """
    多项目协调器

    核心职责:
    1. 管理所有 Repo 的全局执行状态
    2. 协调跨 Repo 的 Agent 资源分配
    3. 提供全局并行度控制
    4. 处理跨 Repo 的路径冲突
    """

    def __init__(
        self,
        dsn: str,
        max_global_parallel: int = 10,
        base_quota_per_repo: int = 2,
        elastic_pool_size: int = 8,
    ):
        self.dsn = dsn
        self.max_global_parallel = max_global_parallel
        self.base_quota_per_repo = base_quota_per_repo
        self.elastic_pool_size = elastic_pool_size
        self._local_agent_slots: dict[str, bool] = {}  # 本地槽位追踪 {slot_id: in_use}

    def get_global_status(self) -> list[GlobalExecutionState]:
        """获取所有 Repo 的全局执行状态"""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            rows = conn.execute("""
                SELECT * FROM v_global_portfolio
                ORDER BY operator_attention_required DESC, repo
            """).fetchall()

        return [
            GlobalExecutionState(
                repo=row["repo"],
                active_agent_count=row["active_agent_count"],
                running_task_count=row["running_task_count"],
                operator_attention_required=row["operator_attention_required"],
                last_updated=row["last_heartbeat_at"],
                ready_task_count=row["ready_task_count"],
                blocked_task_count=row["blocked_task_count"],
                in_progress_task_count=row["in_progress_task_count"],
                done_task_count=row["done_task_count"],
                running_job_count=row["running_job_count"],
                base_agent_count=row["base_agent_count"],
                elastic_agent_count=row["elastic_agent_count"],
                last_activity_at=row["last_activity_at"],
            )
            for row in rows
        ]

    def get_repo_status(self, repo: str) -> GlobalExecutionState | None:
        """获取单个 Repo 的执行状态"""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            row = conn.execute("""
                SELECT * FROM v_global_portfolio WHERE repo = %s
            """, (repo,)).fetchone()

        if row is None:
            return None

        return GlobalExecutionState(
            repo=row["repo"],
            active_agent_count=row["active_agent_count"],
            running_task_count=row["running_task_count"],
            operator_attention_required=row["operator_attention_required"],
            last_updated=row["last_heartbeat_at"],
            ready_task_count=row["ready_task_count"],
            blocked_task_count=row["blocked_task_count"],
            in_progress_task_count=row["in_progress_task_count"],
            done_task_count=row["done_task_count"],
            running_job_count=row["running_job_count"],
            base_agent_count=row["base_agent_count"],
            elastic_agent_count=row["elastic_agent_count"],
            last_activity_at=row["last_activity_at"],
        )

    def select_global_candidates(
        self,
        candidates_by_repo: dict[str, list[dict[str, Any]]],
        dependencies_by_repo: dict[str, dict[str, list[str]]],
    ) -> list[tuple[str, dict[str, Any]]]:
        """
        从多个 Repo 中选择可并行执行的任务

        选择策略:
        1. 优先选择 operator_attention_required=True 的 Repo
        2. 平均分配资源，避免单个 Repo 占用所有 Agent
        3. 检查跨 Repo 路径冲突
        4. 返回：[(repo, task), ...]

        Args:
            candidates_by_repo: {repo: [task_candidates]}
            dependencies_by_repo: {repo: {task_id: [dependency_ids]}}

        Returns:
            [(repo, task), ...] 可并行执行的任务列表
        """
        # 1. 获取全局状态
        global_states = self.get_global_status()
        state_by_repo = {s.repo: s for s in global_states}

        # 2. 按优先级排序 Repo（需要关注的优先）
        sorted_repos = sorted(
            candidates_by_repo.keys(),
            key=lambda r: (
                not state_by_repo.get(r, GlobalExecutionState(repo=r)).operator_attention_required,
                -state_by_repo.get(r, GlobalExecutionState(repo=r)).ready_task_count,
            )
        )

        # 3. 选择任务，考虑全局并行度
        selected: list[tuple[str, dict[str, Any]]] = []
        current_parallel = sum(
            s.running_task_count for s in global_states
        )

        for repo in sorted_repos:
            if current_parallel >= self.max_global_parallel:
                break

            repo_candidates = candidates_by_repo.get(repo, [])
            repo_deps = dependencies_by_repo.get(repo, {})

            # 简单的任务选择（实际应该更复杂，考虑依赖、路径冲突等）
            for task in repo_candidates:
                if current_parallel >= self.max_global_parallel:
                    break

                # 检查依赖（简化版）
                task_id = task.get("id") or task.get("work_id")
                if task_id and repo_deps.get(task_id):
                    continue  # 有未满足的依赖

                selected.append((repo, task))
                current_parallel += 1

        return selected

    def acquire_agent_slot(self, repo: str) -> bool:
        """
        获取 Agent 执行槽位（全局限流）

        Returns:
            bool: 是否成功获取槽位
        """
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            # 检查全局并行度
            row = conn.execute("""
                SELECT SUM(active_agent_count) as total_agents
                FROM global_execution_state
            """).fetchone()

            total_agents = row["total_agents"] or 0
            if total_agents >= self.max_global_parallel:
                logger.warning(
                    f"Global agent pool full: {total_agents}/{self.max_global_parallel}"
                )
                return False

            # 检查 Repo 配额
            state = self.get_repo_status(repo)
            if state:
                repo_agents = state.active_agent_count
                max_repo_agents = self.base_quota_per_repo + self.elastic_pool_size
                if repo_agents >= max_repo_agents:
                    logger.warning(
                        f"Repo {repo} agent quota exceeded: {repo_agents}/{max_repo_agents}"
                    )
                    return False

            # 更新状态
            conn.execute("""
                INSERT INTO global_execution_state (id, repo, active_agent_count, updated_at)
                VALUES (%s, %s, 1, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    active_agent_count = global_execution_state.active_agent_count + 1,
                    updated_at = NOW()
            """, (repo, repo))

        return True

    def release_agent_slot(self, repo: str) -> None:
        """释放 Agent 执行槽位"""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            conn.execute("""
                UPDATE global_execution_state
                SET
                    active_agent_count = GREATEST(0, active_agent_count - 1),
                    updated_at = NOW()
                WHERE repo = %s AND active_agent_count > 0
            """, (repo,))

    def acquire_path_lock(
        self,
        repo: str,
        path: str,
        work_id: str,
        duration_minutes: int = 30,
    ) -> bool:
        """
        获取路径锁（避免跨 Repo 路径冲突）

        Args:
            repo: 请求锁的 Repo
            path: 文件路径
            work_id: 工作项 ID
            duration_minutes: 锁持续时间（分钟）

        Returns:
            bool: 是否成功获取锁
        """
        path_hash = hashlib.sha256(path.encode()).hexdigest()[:16]
        expires_at = datetime.now() + timedelta(minutes=duration_minutes)

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            try:
                conn.execute("""
                    INSERT INTO global_path_lock
                    (path_hash, full_path, locked_by_repo, locked_by_work_id, expires_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (path_hash) DO UPDATE SET
                        locked_by_repo = EXCLUDED.locked_by_repo,
                        locked_by_work_id = EXCLUDED.locked_by_work_id,
                        expires_at = EXCLUDED.expires_at
                    WHERE
                        global_path_lock.expires_at < NOW()
                        OR global_path_lock.locked_by_repo = %s
                """, (path_hash, path, repo, work_id, expires_at, repo))
                return True
            except psycopg.errors.UniqueViolation:
                logger.info(f"Path {path} is locked by another repo")
                return False

    def release_path_lock(self, repo: str, path: str) -> bool:
        """释放路径锁"""
        path_hash = hashlib.sha256(path.encode()).hexdigest()[:16]

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            result = conn.execute("""
                DELETE FROM global_path_lock
                WHERE path_hash = %s AND locked_by_repo = %s
                RETURNING 1
            """, (path_hash, repo)).fetchone()

        return result is not None

    def is_path_locked(self, path: str, exclude_repo: str | None = None) -> bool:
        """检查路径是否被锁定"""
        path_hash = hashlib.sha256(path.encode()).hexdigest()[:16]

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            query = """
                SELECT 1 FROM global_path_lock
                WHERE path_hash = %s AND expires_at > NOW()
            """
            params = [path_hash]
            if exclude_repo:
                query += " AND locked_by_repo != %s"
                params.append(exclude_repo)

            return conn.execute(query, params).fetchone() is not None

    def get_path_lock_holder(self, path: str) -> tuple[str, str] | None:
        """获取路径锁持有者信息"""
        path_hash = hashlib.sha256(path.encode()).hexdigest()[:16]

        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            row = conn.execute("""
                SELECT locked_by_repo, locked_by_work_id
                FROM global_path_lock
                WHERE path_hash = %s AND expires_at > NOW()
            """, (path_hash,)).fetchone()

        if row is None:
            return None

        return (row["locked_by_repo"], row["locked_by_work_id"])

    def update_heartbeat(self, repo: str) -> None:
        """更新 Repo 心跳"""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            conn.execute("""
                INSERT INTO global_execution_state (id, repo, last_heartbeat_at, updated_at)
                VALUES (%s, %s, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    last_heartbeat_at = NOW(),
                    updated_at = NOW()
            """, (repo, repo))

    def set_operator_attention_required(self, repo: str, required: bool) -> None:
        """设置 Repo 是否需要操作员注意"""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            conn.execute("""
                INSERT INTO global_execution_state (id, repo, operator_attention_required, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    operator_attention_required = EXCLUDED.operator_attention_required,
                    updated_at = NOW()
            """, (repo, repo, required))

    def get_agent_pool_status(self) -> dict[str, Any]:
        """获取全局 Agent 池状态"""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            row = conn.execute("SELECT * FROM v_global_agent_pool_status").fetchone()
            return dict(row) if row else {}

    def list_agents(self, repo: str | None = None) -> list[AgentSlot]:
        """列出 Agent 状态"""
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            if repo:
                rows = conn.execute("""
                    SELECT * FROM v_agent_status
                    WHERE assigned_repo = %s OR base_quota_repo = %s
                    ORDER BY status, agent_name
                """, (repo, repo)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM v_agent_status
                    ORDER BY status, agent_name
                """).fetchall()

        return [
            AgentSlot(
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
