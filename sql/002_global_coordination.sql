-- Global Coordination Schema
-- 多项目并行管理的全局协调机制
--
-- 设计原则：
-- 1. 混合 Agent 分配策略：基础配额 + 弹性池
-- 2. 跨 Repo 路径冲突避免
-- 3. 全局执行状态追踪
-- 4. Portfolio 总览查询

-- ============================================================================
-- 1. Global Execution State 表 - 追踪各 Repo 的全局执行状态
-- ============================================================================

CREATE TABLE IF NOT EXISTS global_execution_state (
    id TEXT PRIMARY KEY,
    repo TEXT NOT NULL UNIQUE,
    active_agent_count INTEGER NOT NULL DEFAULT 0,
    running_task_count INTEGER NOT NULL DEFAULT 0,
    operator_attention_required BOOLEAN NOT NULL DEFAULT FALSE,
    last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE global_execution_state IS '各 Repo 的全局执行状态追踪表';
COMMENT ON COLUMN global_execution_state.id IS '主键，格式：repo';
COMMENT ON COLUMN global_execution_state.repo IS '仓库标识符';
COMMENT ON COLUMN global_execution_state.active_agent_count IS '当前活跃的 Agent 数量';
COMMENT ON COLUMN global_execution_state.running_task_count IS '正在运行的任务数量';
COMMENT ON COLUMN global_execution_state.operator_attention_required IS '是否需要操作员注意';
COMMENT ON COLUMN global_execution_state.last_heartbeat_at IS '最后心跳时间，用于检测失联';

CREATE INDEX IF NOT EXISTS idx_global_state_by_attention
    ON global_execution_state (operator_attention_required, repo);

CREATE INDEX IF NOT EXISTS idx_global_state_last_heartbeat
    ON global_execution_state (last_heartbeat_at);

-- ============================================================================
-- 2. Global Agent Pool 表 - 全局 Agent 资源池管理
-- ============================================================================

CREATE TABLE IF NOT EXISTS global_agent_pool (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    agent_type TEXT NOT NULL CHECK (agent_type IN (
        'claude_code',
        'gemini_cli',
        'codex',
        'opencode',
        'qwen_code',
        'custom'
    )),
    assigned_repo TEXT,
    status TEXT NOT NULL CHECK (status IN ('idle', 'busy', 'offline')),
    current_work_id TEXT,
    base_quota_repo TEXT,  -- 基础配额所属的 Repo
    last_heartbeat_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE global_agent_pool IS '全局 Agent 资源池，支持基础配额 + 弹性池分配';
COMMENT ON COLUMN global_agent_pool.id IS '主键，格式：agent-{name}';
COMMENT ON COLUMN global_agent_pool.agent_name IS 'Agent 实例名称';
COMMENT ON COLUMN global_agent_pool.agent_type IS 'Agent 类型';
COMMENT ON COLUMN global_agent_pool.assigned_repo IS '当前分配的 Repo，NULL 表示未分配';
COMMENT ON COLUMN global_agent_pool.status IS 'Agent 状态：idle, busy, offline';
COMMENT ON COLUMN global_agent_pool.current_work_id IS '当前执行的任务 ID';
COMMENT ON COLUMN global_agent_pool.base_quota_repo IS '基础配额所属的 Repo，弹性池 Agent 为 NULL';
COMMENT ON COLUMN global_agent_pool.last_heartbeat_at IS '最后心跳时间';

CREATE INDEX IF NOT EXISTS idx_agent_pool_by_status
    ON global_agent_pool (status, assigned_repo);

CREATE INDEX IF NOT EXISTS idx_agent_pool_by_repo
    ON global_agent_pool (assigned_repo);

CREATE INDEX IF NOT EXISTS idx_agent_pool_by_base_quota
    ON global_agent_pool (base_quota_repo);

-- ============================================================================
-- 3. Global Path Lock 表 - 跨 Repo 路径锁定
-- ============================================================================

CREATE TABLE IF NOT EXISTS global_path_lock (
    path_hash TEXT PRIMARY KEY,
    full_path TEXT NOT NULL,
    locked_by_repo TEXT NOT NULL,
    locked_by_work_id TEXT NOT NULL,
    locked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

COMMENT ON TABLE global_path_lock IS '跨 Repo 路径锁定表，避免多 Repo 同时修改同一文件';
COMMENT ON COLUMN global_path_lock.path_hash IS '路径哈希值，主键';
COMMENT ON COLUMN global_path_lock.full_path IS '完整文件路径';
COMMENT ON COLUMN global_path_lock.locked_by_repo IS '锁定该路径的 Repo';
COMMENT ON COLUMN global_path_lock.locked_by_work_id IS '锁定该路径的工作项 ID';
COMMENT ON COLUMN global_path_lock.locked_at IS '锁定时间';
COMMENT ON COLUMN global_path_lock.expires_at IS '锁过期时间（默认 30 分钟）';

CREATE INDEX IF NOT EXISTS idx_path_lock_by_repo
    ON global_path_lock (locked_by_repo);

CREATE INDEX IF NOT EXISTS idx_path_lock_by_expires
    ON global_path_lock (expires_at);

-- ============================================================================
-- 4. Global Portfolio 总览视图
-- ============================================================================

CREATE OR REPLACE VIEW v_global_portfolio AS
SELECT
    ges.id,
    ges.repo,
    ges.active_agent_count,
    ges.running_task_count,
    ges.operator_attention_required,
    COALESCE((
        SELECT COUNT(*) FROM work_item wi WHERE wi.repo = ges.repo AND status = 'ready'
    ), 0) AS ready_task_count,
    COALESCE((
        SELECT COUNT(*) FROM work_item wi WHERE wi.repo = ges.repo AND status = 'blocked'
    ), 0) AS blocked_task_count,
    COALESCE((
        SELECT COUNT(*) FROM work_item wi WHERE wi.repo = ges.repo AND status = 'in_progress'
    ), 0) AS in_progress_task_count,
    COALESCE((
        SELECT COUNT(*) FROM work_item wi WHERE wi.repo = ges.repo AND status = 'done'
    ), 0) AS done_task_count,
    COALESCE((
        SELECT COUNT(*) FROM execution_job ej WHERE ej.repo = ges.repo AND ej.status = 'running'
    ), 0) AS running_job_count,
    COALESCE((
        SELECT MAX(updated_at) FROM work_item wi WHERE wi.repo = ges.repo
    ), ges.last_heartbeat_at) AS last_activity_at,
    COALESCE((
        SELECT COUNT(*) FROM global_agent_pool gap WHERE gap.base_quota_repo = ges.repo AND gap.status != 'offline'
    ), 0) AS base_agent_count,
    COALESCE((
        SELECT COUNT(*) FROM global_agent_pool gap WHERE gap.assigned_repo = ges.repo AND gap.base_quota_repo IS NULL
    ), 0) AS elastic_agent_count,
    ges.last_heartbeat_at,
    ges.created_at,
    ges.updated_at
FROM global_execution_state ges
ORDER BY ges.operator_attention_required DESC, ges.repo;

COMMENT ON VIEW v_global_portfolio IS '多项目 Portfolio 总览视图，包含各 Repo 的关键指标';

-- ============================================================================
-- 5. 全局 Agent 池状态视图
-- ============================================================================

CREATE OR REPLACE VIEW v_global_agent_pool_status AS
SELECT
    -- 总体统计
    (SELECT COUNT(*) FROM global_agent_pool WHERE status = 'idle') AS idle_agents,
    (SELECT COUNT(*) FROM global_agent_pool WHERE status = 'busy') AS busy_agents,
    (SELECT COUNT(*) FROM global_agent_pool WHERE status = 'offline') AS offline_agents,
    (SELECT COUNT(*) FROM global_agent_pool) AS total_agents,
    -- 按 Repo 分配统计
    (SELECT COUNT(DISTINCT assigned_repo) FROM global_agent_pool WHERE assigned_repo IS NOT NULL) AS assigned_repos,
    -- 基础配额 vs 弹性池
    (SELECT COUNT(*) FROM global_agent_pool WHERE base_quota_repo IS NOT NULL) AS base_quota_agents,
    (SELECT COUNT(*) FROM global_agent_pool WHERE base_quota_repo IS NULL) AS elastic_pool_agents;

COMMENT ON VIEW v_global_agent_pool_status IS '全局 Agent 池状态统计视图';

-- ============================================================================
-- 6. 过期锁自动清理视图
-- ============================================================================

CREATE OR REPLACE VIEW v_expired_path_locks AS
SELECT *
FROM global_path_lock
WHERE expires_at < NOW();

COMMENT ON VIEW v_expired_path_locks IS '已过期的路径锁，可清理';

-- ============================================================================
-- 7. Repo 心跳超时检测视图
-- ============================================================================

CREATE OR REPLACE VIEW v_stale_repos AS
SELECT *
FROM global_execution_state
WHERE last_heartbeat_at < NOW() - INTERVAL '5 minutes';

COMMENT ON VIEW v_stale_repos IS '心跳超时的 Repo（超过 5 分钟未更新）';

-- ============================================================================
-- 8. 初始化数据
-- ============================================================================

-- 插入默认的 Agent 池配置（示例）
INSERT INTO global_agent_pool (id, agent_name, agent_type, status, base_quota_repo)
SELECT
    'agent-' || name,
    name,
    type,
    'idle',
    NULL  -- 默认都在弹性池
FROM (VALUES
    ('claude-1', 'claude_code'),
    ('claude-2', 'claude_code'),
    ('claude-3', 'claude_code'),
    ('claude-4', 'claude_code'),
    ('opencode-1', 'opencode'),
    ('opencode-2', 'opencode'),
    ('qwen-1', 'qwen_code'),
    ('qwen-2', 'qwen_code')
) AS agents(name, type)
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- 9. 触发器：自动更新 updated_at
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 为 global_execution_state 添加触发器
DROP TRIGGER IF EXISTS update_global_execution_state_updated_at ON global_execution_state;
CREATE TRIGGER update_global_execution_state_updated_at
    BEFORE UPDATE ON global_execution_state
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 为 global_agent_pool 添加触发器
DROP TRIGGER IF EXISTS update_global_agent_pool_updated_at ON global_agent_pool;
CREATE TRIGGER update_global_agent_pool_updated_at
    BEFORE UPDATE ON global_agent_pool
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
