-- DLQ and Observability Extensions
-- Dead Letter Queue + Event Stream support

-- ============================================================================
-- 1. Dead Letter Queue table
-- ============================================================================

CREATE TABLE IF NOT EXISTS dead_letter_queue (
    id BIGSERIAL PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES work_item(id) ON DELETE CASCADE,
    original_status TEXT NOT NULL,
    failure_reason TEXT NOT NULL,
    attempt_count INT NOT NULL,
    last_run_id BIGINT REFERENCES execution_run(id),
    moved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    moved_by TEXT DEFAULT 'system',
    resolution TEXT,
    resolved_at TIMESTAMPTZ,
    resolved_by TEXT
);

COMMENT ON TABLE dead_letter_queue IS 'Tasks that exhausted retries and need manual intervention';
COMMENT ON COLUMN dead_letter_queue.resolution IS 'human_resolve / auto_retry / archived';

CREATE INDEX idx_dlq_by_work ON dead_letter_queue (work_id);
CREATE INDEX idx_dlq_by_resolution ON dead_letter_queue (resolution);
CREATE INDEX idx_dlq_by_moved_at ON dead_letter_queue (moved_at DESC);

-- ============================================================================
-- 2. Event Log table (for timeline / observability)
-- ============================================================================

CREATE TABLE IF NOT EXISTS event_log (
    id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'task_claimed', 'task_started', 'task_completed', 'task_failed',
        'retry_scheduled', 'dlq_moved', 'human_approval_requested',
        'artifact_created', 'session_checkpoint', 'session_resumed',
        'task_verified', 'task_blocked', 'executor_selected'
    )),
    work_id TEXT REFERENCES work_item(id) ON DELETE SET NULL,
    run_id BIGINT REFERENCES execution_run(id) ON DELETE SET NULL,
    session_id UUID REFERENCES execution_session(id) ON DELETE SET NULL,
    actor TEXT,
    detail JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE event_log IS 'Chronological event stream for observability and timeline';

CREATE INDEX idx_event_log_by_work ON event_log (work_id, created_at DESC);
CREATE INDEX idx_event_log_by_type ON event_log (event_type, created_at DESC);
CREATE INDEX idx_event_log_by_created ON event_log (created_at DESC);

-- ============================================================================
-- 3. Views
-- ============================================================================

-- DLQ items needing attention
CREATE OR REPLACE VIEW v_dlq_attention_required AS
SELECT
    dlq.id,
    dlq.work_id,
    wi.title,
    wi.repo,
    wi.attempt_count,
    dlq.failure_reason,
    dlq.moved_at,
    dlq.moved_by,
    dlq.resolution,
    er.summary AS last_run_summary,
    er.result_payload_json AS last_run_payload
FROM dead_letter_queue dlq
LEFT JOIN work_item wi ON wi.id = dlq.work_id
LEFT JOIN execution_run er ON er.id = dlq.last_run_id
WHERE dlq.resolution IS NULL
ORDER BY dlq.moved_at DESC;

COMMENT ON VIEW v_dlq_attention_required IS 'DLQ items awaiting manual resolution';

-- Recent event stream
CREATE OR REPLACE VIEW v_recent_events AS
SELECT
    el.id,
    el.event_type,
    el.work_id,
    el.actor,
    el.detail,
    el.created_at,
    wi.title AS work_title,
    wi.repo
FROM event_log el
LEFT JOIN work_item wi ON wi.id = el.work_id
ORDER BY el.created_at DESC
LIMIT 1000;

COMMENT ON VIEW v_recent_events IS 'Most recent 1000 events for dashboard';

-- Task timeline (all events for a single work item)
CREATE OR REPLACE VIEW v_task_timeline AS
SELECT
    el.event_type,
    el.work_id,
    el.actor,
    el.detail,
    el.created_at
FROM event_log el
ORDER BY el.work_id, el.created_at;

COMMENT ON VIEW v_task_timeline IS 'Full event timeline per work item';
