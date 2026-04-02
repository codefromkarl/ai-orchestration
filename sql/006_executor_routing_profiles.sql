-- Executor routing profiles
-- Supports multiple mappings per task_type with explicit priority ordering.

ALTER TABLE task_executor_mapping
    ADD COLUMN IF NOT EXISTS id BIGSERIAL;

ALTER TABLE task_executor_mapping
    ADD COLUMN IF NOT EXISTS priority INT NOT NULL DEFAULT 100;

UPDATE task_executor_mapping
SET priority = 100
WHERE priority IS NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'task_executor_mapping'
          AND constraint_name = 'task_executor_mapping_pkey'
    ) THEN
        ALTER TABLE task_executor_mapping
            DROP CONSTRAINT task_executor_mapping_pkey;
    END IF;
END $$;

UPDATE task_executor_mapping
SET id = nextval(pg_get_serial_sequence('task_executor_mapping', 'id'))
WHERE id IS NULL;

ALTER TABLE task_executor_mapping
    ALTER COLUMN id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'task_executor_mapping'
          AND constraint_name = 'task_executor_mapping_pkey'
    ) THEN
        ALTER TABLE task_executor_mapping
            ADD CONSTRAINT task_executor_mapping_pkey PRIMARY KEY (id);
    END IF;
END $$;

COMMENT ON COLUMN task_executor_mapping.priority IS
    'Higher priority mappings win when multiple routes match the same task profile';
COMMENT ON COLUMN task_executor_mapping.conditions IS
    'Optional routing conditions (lane, complexity, title_keywords, planned_path_prefixes, failure history, resume hints, etc.)';

CREATE INDEX IF NOT EXISTS idx_task_executor_mapping_by_task_type
    ON task_executor_mapping (task_type, priority DESC, id ASC);

CREATE OR REPLACE VIEW v_executor_routing_profiles AS
SELECT
    tem.id,
    tem.task_type,
    tem.priority,
    tem.preferred_executor,
    preferred.executor_type AS preferred_executor_type,
    tem.fallback_executor,
    fallback.executor_type AS fallback_executor_type,
    tem.conditions,
    tem.created_at,
    tem.updated_at
FROM task_executor_mapping tem
LEFT JOIN executor_registry preferred
  ON preferred.executor_name = tem.preferred_executor
LEFT JOIN executor_registry fallback
  ON fallback.executor_name = tem.fallback_executor
ORDER BY tem.task_type ASC, tem.priority DESC, tem.id ASC;

CREATE OR REPLACE VIEW v_executor_selection_events AS
SELECT
    el.id,
    el.work_id,
    wi.repo,
    wi.source_issue_number,
    wi.title AS work_title,
    el.actor,
    el.detail->>'executor_name' AS executor_name,
    el.detail->>'executor_type' AS executor_type,
    el.detail->>'task_type' AS task_type,
    el.detail->>'lane' AS lane,
    el.detail->>'wave' AS wave,
    el.created_at
FROM event_log el
LEFT JOIN work_item wi
  ON wi.id = el.work_id
WHERE el.event_type = 'executor_selected'
ORDER BY el.created_at DESC, el.id DESC;

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
