-- UI Enhancements Schema
-- UI 增强功能所需的数据库视图
--
-- 提供以下查询视图：
-- 1. AI 决策历史查询视图
-- 2. 通知状态查询视图
-- 3. Agent 执行历史视图

-- ============================================================================
-- 1. AI 决策历史查询视图
-- ============================================================================

CREATE OR REPLACE VIEW v_ai_decision_history AS
SELECT
    dl.id,
    dl.work_id,
    dl.decision_type,
    dl.original_reason_code,
    dl.ai_reasoning,
    dl.context_summary,
    dl.outcome,
    dl.created_at,
    wi.repo,
    wi.title AS work_title,
    wi.status AS work_status,
    wi.canonical_story_issue_number AS story_issue_number,
    pe.issue_number AS epic_issue_number,
    pe.title AS epic_title
FROM ai_decision_log dl
LEFT JOIN work_item wi ON wi.id = dl.work_id
LEFT JOIN program_story ps
    ON ps.repo = wi.repo
    AND ps.issue_number = wi.canonical_story_issue_number
LEFT JOIN program_epic pe
    ON pe.repo = ps.repo
    AND pe.issue_number = ps.epic_issue_number
ORDER BY dl.created_at DESC;

COMMENT ON VIEW v_ai_decision_history IS 'AI 决策历史查询视图，包含关联的 Work、Story、Epic 信息';

-- 按 Repo 查询的 AI 决策历史
CREATE OR REPLACE VIEW v_ai_decision_history_by_repo AS
SELECT
    repo,
    decision_type,
    DATE_TRUNC('day', created_at) AS decision_date,
    COUNT(*) AS decision_count,
    COUNT(*) FILTER (WHERE outcome = 'success') AS successful_outcomes,
    COUNT(*) FILTER (WHERE outcome = 'failed') AS failed_outcomes
FROM v_ai_decision_history
GROUP BY repo, decision_type, DATE_TRUNC('day', created_at)
ORDER BY decision_date DESC, repo, decision_type;

COMMENT ON VIEW v_ai_decision_history_by_repo IS '按 Repo 和决策类型分组的统计视图';

-- ============================================================================
-- 2. 通知状态查询视图
-- ============================================================================

CREATE OR REPLACE VIEW v_notification_status AS
SELECT
    nq.id,
    nq.notification_type,
    nq.channel,
    nq.status,
    nq.recipient,
    nq.subject,
    nq.message,
    nq.error_message,
    nq.sent_at,
    nq.created_at,
    wi.repo,
    wi.title AS work_title,
    wi.canonical_story_issue_number AS story_issue_number,
    CASE
        WHEN nq.status = 'pending' THEN EXTRACT(EPOCH FROM (NOW() - nq.created_at))::INTEGER
        WHEN nq.status = 'sent' THEN EXTRACT(EPOCH FROM (nq.sent_at - nq.created_at))::INTEGER
        ELSE NULL
    END AS processing_delay_seconds
FROM notification_queue nq
LEFT JOIN work_item wi ON wi.id = nq.work_id
ORDER BY nq.created_at DESC;

COMMENT ON VIEW v_notification_status IS '通知状态查询视图，包含处理延迟统计';

-- 待发送通知视图
CREATE OR REPLACE VIEW v_pending_notifications_detailed AS
SELECT
    nq.id,
    nq.notification_type,
    nq.channel,
    nq.recipient,
    nq.subject,
    nq.message,
    nq.metadata,
    nq.created_at,
    EXTRACT(EPOCH FROM (NOW() - nq.created_at))::INTEGER AS pending_seconds,
    wi.repo,
    wi.title AS work_title,
    wi.status AS work_status
FROM notification_queue nq
LEFT JOIN work_item wi ON wi.id = nq.work_id
WHERE nq.status = 'pending'
ORDER BY nq.created_at;

COMMENT ON VIEW v_pending_notifications_detailed IS '待发送通知详细视图';

-- 失败通知视图（用于重发）
CREATE OR REPLACE VIEW v_failed_notifications AS
SELECT
    nq.id,
    nq.notification_type,
    nq.channel,
    nq.recipient,
    nq.subject,
    nq.message,
    nq.error_message,
    nq.metadata,
    nq.created_at,
    nq.sent_at AS last_attempt_at,
    wi.repo,
    wi.title AS work_title
FROM notification_queue nq
LEFT JOIN work_item wi ON wi.id = nq.work_id
WHERE nq.status = 'failed'
ORDER BY nq.sent_at DESC;

COMMENT ON VIEW v_failed_notifications IS '失败通知视图，用于手动重发';

-- 通知统计视图
CREATE OR REPLACE VIEW v_notification_stats AS
SELECT
    channel,
    status,
    notification_type,
    COUNT(*) AS notification_count,
    MIN(created_at) AS oldest_notification,
    MAX(created_at) AS newest_notification
FROM notification_queue
GROUP BY channel, status, notification_type
ORDER BY channel, status, notification_type;

COMMENT ON VIEW v_notification_stats IS '通知统计视图，按渠道、状态、类型分组';

-- ============================================================================
-- 3. Agent 执行状态视图
-- ============================================================================

CREATE OR REPLACE VIEW v_agent_status AS
SELECT
    gap.id,
    gap.agent_name,
    gap.agent_type,
    gap.assigned_repo,
    gap.status,
    gap.current_work_id,
    gap.base_quota_repo,
    gap.last_heartbeat_at,
    gap.created_at,
    gap.updated_at,
    wi.title AS current_work_title,
    wi.status AS current_work_status,
    EXTRACT(EPOCH FROM (NOW() - gap.last_heartbeat_at))::INTEGER AS seconds_since_heartbeat,
    CASE
        WHEN gap.last_heartbeat_at IS NULL THEN 'unknown'
        WHEN gap.last_heartbeat_at < NOW() - INTERVAL '2 minutes' THEN 'stale'
        ELSE 'healthy'
    END AS health_status,
    CASE
        WHEN gap.status = 'idle' THEN NULL
        ELSE EXTRACT(EPOCH FROM (NOW() - gap.last_heartbeat_at))::INTEGER
    END AS elapsed_seconds
FROM global_agent_pool gap
LEFT JOIN work_item wi ON wi.id = gap.current_work_id
ORDER BY gap.status, gap.agent_name;

COMMENT ON VIEW v_agent_status IS 'Agent 实时执行状态视图，包含健康检查';

-- Agent 执行历史详细视图
CREATE OR REPLACE VIEW v_agent_execution_history_detailed AS
SELECT
    aeh.id,
    aeh.agent_name,
    ap.agent_type,
    aeh.work_id,
    aeh.started_at,
    aeh.finished_at,
    aeh.exit_code,
    aeh.duration_ms,
    aeh.metadata,
    wi.repo,
    wi.title AS work_title,
    wi.task_type,
    wi.canonical_story_issue_number AS story_issue_number,
    CASE
        WHEN aeh.exit_code = 0 THEN 'success'
        WHEN aeh.exit_code IS NOT NULL THEN 'failed'
        ELSE 'interrupted'
    END AS execution_result
FROM agent_execution_history aeh
LEFT JOIN work_item wi ON wi.id = aeh.work_id
LEFT JOIN agent_pool ap ON ap.agent_name = aeh.agent_name
ORDER BY aeh.started_at DESC;

COMMENT ON VIEW v_agent_execution_history_detailed IS 'Agent 执行历史详细视图';

-- Agent 效率统计视图
CREATE OR REPLACE VIEW v_agent_efficiency_stats AS
SELECT
    aeh.agent_name,
    ap.agent_type,
    COUNT(*) AS total_executions,
    COUNT(*) FILTER (WHERE aeh.exit_code = 0) AS successful_executions,
    COUNT(*) FILTER (WHERE aeh.exit_code != 0) AS failed_executions,
    ROUND(
        COUNT(*) FILTER (WHERE aeh.exit_code = 0) * 100.0 / NULLIF(COUNT(*), 0),
        2
    ) AS success_rate_percent,
    ROUND(AVG(aeh.duration_ms) FILTER (WHERE aeh.duration_ms IS NOT NULL), 0) AS avg_duration_ms,
    MIN(aeh.started_at) AS first_execution_at,
    MAX(aeh.started_at) AS last_execution_at
FROM agent_execution_history aeh
LEFT JOIN agent_pool ap ON ap.agent_name = aeh.agent_name
GROUP BY aeh.agent_name, ap.agent_type
ORDER BY total_executions DESC;

COMMENT ON VIEW v_agent_efficiency_stats IS 'Agent 效率统计视图，包含成功率和平局耗时';

-- Repo Agent 分配统计视图
CREATE OR REPLACE VIEW v_repo_agent_allocation AS
SELECT
    COALESCE(base_quota_repo, assigned_repo) AS repo,
    COUNT(*) FILTER (WHERE base_quota_repo IS NOT NULL) AS base_quota_count,
    COUNT(*) FILTER (WHERE base_quota_repo IS NULL AND assigned_repo IS NOT NULL) AS elastic_assigned_count,
    COUNT(*) FILTER (WHERE status = 'idle') AS idle_count,
    COUNT(*) FILTER (WHERE status = 'busy') AS busy_count,
    COUNT(*) FILTER (WHERE status = 'offline') AS offline_count,
    COUNT(*) AS total_agents
FROM global_agent_pool
WHERE base_quota_repo IS NOT NULL OR assigned_repo IS NOT NULL
GROUP BY COALESCE(base_quota_repo, assigned_repo)
ORDER BY repo;

COMMENT ON VIEW v_repo_agent_allocation IS 'Repo Agent 分配统计视图';

-- ============================================================================
-- 4. Portfolio 汇总视图（整合所有信息）
-- ============================================================================

CREATE OR REPLACE VIEW v_portfolio_summary AS
SELECT
    ges.repo,
    ges.active_agent_count,
    ges.running_task_count,
    ges.operator_attention_required,
    COALESCE(epic_counts.epic_count, 0) AS epic_count,
    COALESCE(story_counts.story_count, 0) AS story_count,
    COALESCE(task_counts.task_count, 0) AS task_count,
    COALESCE(task_counts.ready_task_count, 0) AS ready_task_count,
    COALESCE(task_counts.blocked_task_count, 0) AS blocked_task_count,
    COALESCE(task_counts.in_progress_task_count, 0) AS in_progress_task_count,
    COALESCE(task_counts.done_task_count, 0) AS done_task_count,
    COALESCE(job_counts.running_job_count, 0) AS running_job_count,
    COALESCE(agent_counts.base_agent_count, 0) AS base_agent_count,
    COALESCE(agent_counts.elastic_agent_count, 0) AS elastic_agent_count,
    COALESCE(notification_counts.pending_notification_count, 0) AS pending_notification_count,
    COALESCE(decision_counts.recent_decision_count, 0) AS recent_decision_count,
    ges.last_heartbeat_at,
    ges.updated_at
FROM global_execution_state ges
LEFT JOIN (
    SELECT repo, COUNT(*) AS epic_count
    FROM program_epic GROUP BY repo
) epic_counts ON epic_counts.repo = ges.repo
LEFT JOIN (
    SELECT repo, COUNT(*) AS story_count
    FROM program_story GROUP BY repo
) story_counts ON story_counts.repo = ges.repo
LEFT JOIN (
    SELECT
        repo,
        COUNT(*) AS task_count,
        COUNT(*) FILTER (WHERE status = 'ready') AS ready_task_count,
        COUNT(*) FILTER (WHERE status = 'blocked') AS blocked_task_count,
        COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress_task_count,
        COUNT(*) FILTER (WHERE status = 'done') AS done_task_count
    FROM work_item GROUP BY repo
) task_counts ON task_counts.repo = ges.repo
LEFT JOIN (
    SELECT repo, COUNT(*) AS running_job_count
    FROM execution_job WHERE status = 'running' GROUP BY repo
) job_counts ON job_counts.repo = ges.repo
LEFT JOIN (
    SELECT
        base_quota_repo AS repo,
        COUNT(*) FILTER (WHERE status != 'offline') AS base_agent_count,
        COUNT(*) FILTER (WHERE base_quota_repo IS NULL AND status != 'offline') AS elastic_agent_count
    FROM global_agent_pool
    GROUP BY base_quota_repo
) agent_counts ON agent_counts.repo = ges.repo
LEFT JOIN (
    SELECT wi.repo, COUNT(*) FILTER (WHERE nq.status = 'pending') AS pending_notification_count
    FROM notification_queue nq
    LEFT JOIN work_item wi ON wi.id = nq.work_id
    WHERE nq.status = 'pending'
    GROUP BY wi.repo
) notification_counts ON notification_counts.repo = ges.repo
LEFT JOIN (
    SELECT wi.repo, COUNT(*) AS recent_decision_count
    FROM ai_decision_log dl
    LEFT JOIN work_item wi ON wi.id = dl.work_id
    WHERE dl.created_at > NOW() - INTERVAL '24 hours'
    GROUP BY wi.repo
) decision_counts ON decision_counts.repo = ges.repo
ORDER BY ges.operator_attention_required DESC, ges.repo;

COMMENT ON VIEW v_portfolio_summary IS '完整的 Portfolio 汇总视图，整合所有项目指标';
