-- Parallel Execution Extensions Schema
-- 支持长时间无监督工作的数据库扩展

-- ============================================================================
-- 1. AI Conversation Turn 表 - 持久化 AI 对话历史
-- ============================================================================

CREATE TABLE IF NOT EXISTS ai_conversation_turn (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES work_item(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversation_turns_by_work
    ON ai_conversation_turn (work_id, turn_index);

CREATE INDEX IF NOT EXISTS idx_conversation_turns_created
    ON ai_conversation_turn (created_at DESC);

-- 对话摘要表（每 10 轮自动压缩）
CREATE TABLE IF NOT EXISTS ai_conversation_summary (
    work_id TEXT PRIMARY KEY REFERENCES work_item(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    turn_count INTEGER NOT NULL,
    last_turn_index INTEGER NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- 2. AI Decision Log 表 - 记录自主决策历史
-- ============================================================================

CREATE TABLE IF NOT EXISTS ai_decision_log (
    id BIGSERIAL PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES work_item(id) ON DELETE CASCADE,
    decision_type TEXT NOT NULL CHECK (decision_type IN (
        'auto_resolvable',
        'requires_human',
        'retry_with_context',
        'escalate_to_operator'
    )),
    original_reason_code TEXT,
    ai_reasoning TEXT NOT NULL,
    context_summary TEXT,
    outcome TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_decision_log_by_work
    ON ai_decision_log (work_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_decision_log_by_type
    ON ai_decision_log (decision_type, created_at DESC);

-- ============================================================================
-- 3. Notification Queue 表 - 异步通知队列
-- ============================================================================

CREATE TABLE IF NOT EXISTS notification_queue (
    id BIGSERIAL PRIMARY KEY,
    notification_type TEXT NOT NULL CHECK (notification_type IN (
        'human_decision_required',
        'retry_resolved',
        'story_complete',
        'epic_blocked',
        'milestone_reached'
    )),
    work_id TEXT REFERENCES work_item(id) ON DELETE SET NULL,
    story_issue_number INTEGER,
    epic_issue_number INTEGER,
    channel TEXT NOT NULL CHECK (channel IN ('discord', 'slack', 'telegram', 'email')),
    recipient TEXT,
    subject TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
    sent_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notification_queue_by_status
    ON notification_queue (status, created_at);

CREATE INDEX IF NOT EXISTS idx_notification_queue_by_work
    ON notification_queue (work_id, created_at DESC);

-- ============================================================================
-- 4. Agent Pool 表 - 管理多 Agent 实例
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_pool (
    id BIGSERIAL PRIMARY KEY,
    agent_name TEXT NOT NULL UNIQUE,
    agent_type TEXT NOT NULL CHECK (agent_type IN (
        'claude_code',
        'gemini_cli',
        'codex',
        'opencode',
        'qwen_code'
    )),
    command_template TEXT NOT NULL,
    max_parallel INTEGER NOT NULL DEFAULT 1,
    current_parallel INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_pool_by_type
    ON agent_pool (agent_type, is_active);

-- Agent 执行历史
CREATE TABLE IF NOT EXISTS agent_execution_history (
    id BIGSERIAL PRIMARY KEY,
    agent_name TEXT NOT NULL REFERENCES agent_pool(agent_name) ON DELETE CASCADE,
    work_id TEXT NOT NULL REFERENCES work_item(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    exit_code INTEGER,
    duration_ms INTEGER,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_agent_execution_history_by_agent
    ON agent_execution_history (agent_name, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_execution_history_by_work
    ON agent_execution_history (work_id, started_at DESC);

-- ============================================================================
-- 5. Retry Policy 表 - 配置重试策略
-- ============================================================================

CREATE TABLE IF NOT EXISTS retry_policy (
    id BIGSERIAL PRIMARY KEY,
    failure_reason_pattern TEXT NOT NULL,
    max_retries INTEGER NOT NULL DEFAULT 3,
    base_backoff_minutes INTEGER NOT NULL DEFAULT 5,
    max_backoff_minutes INTEGER NOT NULL DEFAULT 240,
    backoff_multiplier NUMERIC(3,1) NOT NULL DEFAULT 2.0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_retry_policy_active
    ON retry_policy (is_active);

-- 插入默认重试策略
INSERT INTO retry_policy (failure_reason_pattern, max_retries, base_backoff_minutes, max_backoff_minutes, backoff_multiplier) VALUES
    ('timeout', 3, 5, 120, 2.0),
    ('interrupted_retryable', 5, 2, 60, 2.0),
    ('contextatlas-index-failed', 3, 1, 30, 2.0),
    ('git-lock-conflict', 3, 1, 15, 3.0),
    ('resource_temporarily_unavailable', 5, 1, 30, 2.0)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- 6. 扩展 work_item 表字段
-- ============================================================================

ALTER TABLE work_item
    ADD COLUMN IF NOT EXISTS story_issue_numbers JSONB DEFAULT '[]'::jsonb;

ALTER TABLE work_item
    ADD COLUMN IF NOT EXISTS related_story_issue_numbers JSONB DEFAULT '[]'::jsonb;

-- 用于 resume 的上下文字段
ALTER TABLE work_item
    ADD COLUMN IF NOT EXISTS context_summary TEXT;

-- ============================================================================
-- 7. 视图：待处理的通知
-- ============================================================================

CREATE OR REPLACE VIEW v_pending_notifications AS
SELECT
    nq.*,
    wi.title AS work_title,
    wi.status AS work_status
FROM notification_queue nq
LEFT JOIN work_item wi ON wi.id = nq.work_id
WHERE nq.status = 'pending'
ORDER BY nq.created_at;

-- ============================================================================
-- 8. 视图：活跃 Agent 状态
-- ============================================================================

CREATE OR REPLACE VIEW v_active_agents AS
SELECT
    agent_name,
    agent_type,
    max_parallel,
    current_parallel,
    is_active,
    CASE
        WHEN current_parallel < max_parallel THEN 'available'
        WHEN current_parallel = max_parallel THEN 'busy'
        ELSE 'overloaded'
    END AS capacity_status
FROM agent_pool
WHERE is_active = TRUE;

-- ============================================================================
-- 9. 视图：可自动恢复的阻塞任务
-- ============================================================================

CREATE OR REPLACE VIEW v_auto_resolvable_blocked AS
SELECT
    wi.id,
    wi.title,
    wi.status,
    wi.blocked_reason,
    wi.last_failure_reason,
    wi.attempt_count,
    wi.next_eligible_at,
    rp.max_retries,
    rp.base_backoff_minutes
FROM work_item wi
LEFT JOIN retry_policy rp
    ON wi.last_failure_reason LIKE '%' || rp.failure_reason_pattern || '%'
WHERE wi.status IN ('blocked', 'pending')
  AND rp.is_active = TRUE
  AND wi.attempt_count < rp.max_retries;
