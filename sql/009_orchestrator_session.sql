CREATE TABLE IF NOT EXISTS orchestrator_session (
    id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    host_tool TEXT NOT NULL,
    started_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    watch_scope_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    current_phase TEXT NOT NULL DEFAULT 'observe',
    objective_summary TEXT,
    plan_summary TEXT,
    handoff_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE orchestrator_session
    ADD COLUMN IF NOT EXISTS current_phase TEXT NOT NULL DEFAULT 'observe';

ALTER TABLE orchestrator_session
    ADD COLUMN IF NOT EXISTS objective_summary TEXT;

ALTER TABLE orchestrator_session
    ADD COLUMN IF NOT EXISTS plan_summary TEXT;

ALTER TABLE orchestrator_session
    ADD COLUMN IF NOT EXISTS handoff_summary TEXT;

ALTER TABLE execution_job
    ADD COLUMN IF NOT EXISTS orchestrator_session_id TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_execution_job_orchestrator_session_id
    ON execution_job(orchestrator_session_id);
