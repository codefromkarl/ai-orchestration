-- Artifact Store Schema
-- Unified artifact management for multi-model collaboration.
--
-- Design principles:
-- 1. Every execution produces traceable artifacts
-- 2. Artifacts are named consistently and indexed for retrieval
-- 3. Downstream agents can reference upstream artifacts by key
-- 4. Artifact metadata is structured (not loose text)

-- ============================================================================
-- 1. Artifact table
-- ============================================================================

CREATE TABLE IF NOT EXISTS artifact (
    id BIGSERIAL PRIMARY KEY,
    work_id TEXT REFERENCES work_item(id) ON DELETE CASCADE,
    run_id BIGINT REFERENCES execution_run(id) ON DELETE CASCADE,
    session_id UUID REFERENCES execution_session(id) ON DELETE SET NULL,
    artifact_type TEXT NOT NULL CHECK (artifact_type IN (
        'stdout', 'stderr', 'screenshot', 'trace',
        'patch_proposal', 'failure_report', 'verification_result',
        'html_dump', 'diff_snapshot', 'llm_analysis',
        'task_summary', 'custom'
    )),
    artifact_key TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    content_size_bytes BIGINT NOT NULL DEFAULT 0,
    mime_type TEXT DEFAULT 'text/plain',
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE artifact IS 'Unified artifact store for execution evidence and intermediate outputs';
COMMENT ON COLUMN artifact.artifact_key IS 'Naming convention: {work_id}/{type}/{attempt}_{seq}.{ext}';
COMMENT ON COLUMN artifact.storage_path IS 'Local filesystem path or object storage key';
COMMENT ON COLUMN artifact.content_digest IS 'SHA256 hash of artifact content';
COMMENT ON COLUMN artifact.metadata IS 'Structured metadata (model name, resolution, format, etc.)';

CREATE INDEX IF NOT EXISTS idx_artifact_by_work ON artifact (work_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_artifact_by_run ON artifact (run_id);
CREATE INDEX IF NOT EXISTS idx_artifact_by_session ON artifact (session_id);
CREATE INDEX IF NOT EXISTS idx_artifact_by_type ON artifact (artifact_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_artifact_by_key ON artifact (artifact_key);

-- ============================================================================
-- 2. Executor Registry table
-- ============================================================================

CREATE TABLE IF NOT EXISTS executor_registry (
    id BIGSERIAL PRIMARY KEY,
    executor_name TEXT NOT NULL UNIQUE,
    executor_type TEXT NOT NULL CHECK (executor_type IN (
        'agent_cli', 'llm_native', 'shell', 'browser', 'test_runner', 'vision'
    )),
    capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    max_concurrent INT NOT NULL DEFAULT 1,
    cost_per_run_cents INT DEFAULT 0,
    avg_duration_seconds INT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE executor_registry IS 'Registry of available executors with capabilities and capacity';
COMMENT ON COLUMN executor_registry.capabilities IS 'Array: ["code_edit", "file_read", "bash", "git", "browser", ...]';

CREATE INDEX IF NOT EXISTS idx_executor_by_type ON executor_registry (executor_type, is_active);

-- ============================================================================
-- 3. Task-Executor Mapping table
-- ============================================================================

CREATE TABLE IF NOT EXISTS task_executor_mapping (
    id BIGSERIAL PRIMARY KEY,
    task_type TEXT NOT NULL,
    priority INT NOT NULL DEFAULT 100,
    preferred_executor TEXT NOT NULL REFERENCES executor_registry(executor_name),
    fallback_executor TEXT REFERENCES executor_registry(executor_name),
    conditions JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE task_executor_mapping IS 'Maps task types to preferred and fallback executors';
COMMENT ON COLUMN task_executor_mapping.priority IS 'Higher priority mappings win when multiple routes match the same task profile';
COMMENT ON COLUMN task_executor_mapping.conditions IS 'Optional routing conditions (lane, complexity, title_keywords, planned_path_prefixes, failure history, resume hints, etc.)';

CREATE INDEX IF NOT EXISTS idx_task_executor_mapping_by_task_type
    ON task_executor_mapping (task_type, priority DESC, id ASC);

-- ============================================================================
-- 4. Default seed data
-- ============================================================================

-- Register default executors
INSERT INTO executor_registry (executor_name, executor_type, capabilities, max_concurrent, metadata) VALUES
    ('claude-code', 'agent_cli', '["code_edit", "file_read", "bash", "git", "grep"]', 4,
     '{"model": "claude-sonnet-4-20250514", "cli": "claude"}'),
    ('opencode', 'agent_cli', '["code_edit", "file_read", "bash", "git", "grep"]', 4,
     '{"cli": "opencode"}'),
    ('codex', 'agent_cli', '["code_edit", "file_read", "bash", "git", "grep"]', 2,
     '{"cli": "codex"}'),
    ('gemini-cli', 'agent_cli', '["code_edit", "file_read", "bash", "git", "grep"]', 2,
     '{"cli": "gemini"}'),
    ('llm-executor', 'llm_native', '["code_edit", "file_read", "bash", "grep"]', 8,
     '{"provider": "openai", "model": "gpt-4.1-mini"}'),
    ('shell', 'shell', '["bash"]', 16,
     '{"description": "Direct shell command execution"}'),
    ('test-runner', 'test_runner', '["bash", "test_execution"]', 8,
     '{"description": "Test execution and result collection"}'),
    ('browser', 'browser', '["navigate", "screenshot", "dom_extract", "playwright"]', 2,
     '{"description": "Browser automation via Playwright"}'),
    ('vision', 'vision', '["screenshot_analysis", "ui_comparison"]', 4,
     '{"description": "Visual analysis via vision models"}')
ON CONFLICT (executor_name) DO NOTHING;

-- Default task type → executor mappings
INSERT INTO task_executor_mapping (task_type, priority, preferred_executor, fallback_executor, conditions)
SELECT 'core_path', 300, 'codex', 'opencode',
       '{"historical_failure_reasons":["timeout","git-lock-conflict","interrupted_retryable"],"min_historical_failures":2,"resume_hints":["resume_candidate"]}'::jsonb
WHERE NOT EXISTS (
    SELECT 1
    FROM task_executor_mapping
    WHERE task_type = 'core_path'
      AND priority = 300
      AND preferred_executor = 'codex'
);

INSERT INTO task_executor_mapping (task_type, priority, preferred_executor, fallback_executor, conditions)
SELECT 'core_path', 250, 'gemini-cli', 'claude-code',
       '{"planned_path_prefixes":["frontend/"],"title_keywords":["ui"],"requires_story_workspace":true}'::jsonb
WHERE NOT EXISTS (
    SELECT 1
    FROM task_executor_mapping
    WHERE task_type = 'core_path'
      AND priority = 250
      AND preferred_executor = 'gemini-cli'
);

INSERT INTO task_executor_mapping (task_type, priority, preferred_executor, fallback_executor, conditions)
SELECT 'core_path', 100, 'claude-code', 'opencode', '{}'::jsonb
WHERE NOT EXISTS (
    SELECT 1
    FROM task_executor_mapping
    WHERE task_type = 'core_path'
      AND priority = 100
      AND preferred_executor = 'claude-code'
);

INSERT INTO task_executor_mapping (task_type, priority, preferred_executor, fallback_executor, conditions)
SELECT 'documentation', 100, 'opencode', 'claude-code', '{}'::jsonb
WHERE NOT EXISTS (
    SELECT 1
    FROM task_executor_mapping
    WHERE task_type = 'documentation'
      AND priority = 100
      AND preferred_executor = 'opencode'
);

INSERT INTO task_executor_mapping (task_type, priority, preferred_executor, fallback_executor, conditions)
SELECT 'cross_cutting', 100, 'claude-code', 'codex', '{}'::jsonb
WHERE NOT EXISTS (
    SELECT 1
    FROM task_executor_mapping
    WHERE task_type = 'cross_cutting'
      AND priority = 100
      AND preferred_executor = 'claude-code'
);

INSERT INTO task_executor_mapping (task_type, priority, preferred_executor, fallback_executor, conditions)
SELECT 'ui_visual', 100, 'gemini-cli', 'claude-code', '{}'::jsonb
WHERE NOT EXISTS (
    SELECT 1
    FROM task_executor_mapping
    WHERE task_type = 'ui_visual'
      AND priority = 100
      AND preferred_executor = 'gemini-cli'
);

INSERT INTO task_executor_mapping (task_type, priority, preferred_executor, fallback_executor, conditions)
SELECT 'test_fix', 100, 'codex', 'claude-code', '{}'::jsonb
WHERE NOT EXISTS (
    SELECT 1
    FROM task_executor_mapping
    WHERE task_type = 'test_fix'
      AND priority = 100
      AND preferred_executor = 'codex'
);

-- ============================================================================
-- 5. Views
-- ============================================================================

-- Artifact index by work item
CREATE OR REPLACE VIEW v_artifact_index AS
SELECT
    a.id,
    a.work_id,
    a.run_id,
    a.session_id,
    a.artifact_type,
    a.artifact_key,
    a.storage_path,
    a.content_digest,
    a.content_size_bytes,
    a.mime_type,
    a.metadata,
    a.created_at,
    wi.repo,
    wi.title AS work_title,
    wi.status AS work_status,
    wi.canonical_story_issue_number AS story_issue_number
FROM artifact a
LEFT JOIN work_item wi ON wi.id = a.work_id
ORDER BY a.created_at DESC;

COMMENT ON VIEW v_artifact_index IS 'Artifact index with work item context for dashboard queries';

-- Executor capacity and assignment
CREATE OR REPLACE VIEW v_executor_capacity AS
SELECT
    er.executor_name,
    er.executor_type,
    er.capabilities,
    er.max_concurrent,
    er.is_active,
    COALESCE(
        (SELECT COUNT(*) FROM execution_run ej
         JOIN work_item wi ON wi.id = ej.work_id
         WHERE ej.worker_name = er.executor_name
           AND wi.status = 'in_progress'),
        0
    ) AS current_load,
    er.max_concurrent - COALESCE(
        (SELECT COUNT(*) FROM execution_run ej
         JOIN work_item wi ON wi.id = ej.work_id
         WHERE ej.worker_name = er.executor_name
           AND wi.status = 'in_progress'),
        0
    ) AS available_capacity,
    er.avg_duration_seconds,
    er.cost_per_run_cents
FROM executor_registry er
WHERE er.is_active = TRUE;

COMMENT ON VIEW v_executor_capacity IS 'Executor capacity for routing decisions';

-- Artifacts available for downstream reference (by artifact_key)
CREATE OR REPLACE VIEW v_artifact_references AS
SELECT
    a.artifact_key,
    a.work_id,
    a.artifact_type,
    a.storage_path,
    a.content_digest,
    a.metadata,
    a.created_at
FROM artifact a
WHERE a.artifact_type IN (
    'patch_proposal', 'failure_report', 'verification_result',
    'llm_analysis', 'task_summary'
)
ORDER BY a.created_at DESC;

COMMENT ON VIEW v_artifact_references IS 'Artifacts available for downstream agent reference';

-- ============================================================================
-- 6. Triggers
-- ============================================================================

CREATE OR REPLACE TRIGGER update_executor_registry_updated_at
    BEFORE UPDATE ON executor_registry
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE OR REPLACE TRIGGER update_task_executor_mapping_updated_at
    BEFORE UPDATE ON task_executor_mapping
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
