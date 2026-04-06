DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'work_status') THEN
CREATE TYPE work_status AS ENUM (
    'pending',
    'ready',
    'in_progress',
    'verifying',
    'awaiting_approval',
    'blocked',
    'done'
);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'work_complexity') THEN
        CREATE TYPE work_complexity AS ENUM ('low', 'medium', 'high');
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'work_target_type') THEN
        CREATE TYPE work_target_type AS ENUM ('file', 'dir', 'doc', 'test');
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'program_status') THEN
        CREATE TYPE program_status AS ENUM (
            'proposed',
            'approved',
            'completed',
            'archived'
        );
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'execution_status') THEN
        CREATE TYPE execution_status AS ENUM (
            'backlog',
            'planned',
            'decomposing',
            'active',
            'gated',
            'done',
            'blocked',
            'needs_story_refinement'
        );
    END IF;
END $$;

ALTER TYPE execution_status ADD VALUE IF NOT EXISTS 'decomposing' AFTER 'planned';
ALTER TYPE execution_status ADD VALUE IF NOT EXISTS 'needs_story_refinement' AFTER 'blocked';

CREATE TABLE IF NOT EXISTS work_item (
    id TEXT PRIMARY KEY,
    repo TEXT,
    title TEXT NOT NULL,
    lane TEXT NOT NULL,
    wave TEXT NOT NULL,
    status work_status NOT NULL DEFAULT 'pending',
    complexity work_complexity NOT NULL DEFAULT 'low',
    source_issue_number INTEGER,
    canonical_story_issue_number INTEGER,
    task_type TEXT NOT NULL DEFAULT 'core_path',
    blocking_mode TEXT NOT NULL DEFAULT 'hard',
    dod_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    allowed_branch_prefix TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_failure_reason TEXT,
    next_eligible_at TIMESTAMPTZ,
    blocked_reason TEXT,
    decision_required BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE work_item
    ADD COLUMN IF NOT EXISTS repo TEXT;

ALTER TABLE work_item
    ADD COLUMN IF NOT EXISTS blocked_reason TEXT;

ALTER TABLE work_item
    ADD COLUMN IF NOT EXISTS decision_required BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE work_item
    ADD COLUMN IF NOT EXISTS canonical_story_issue_number INTEGER;

ALTER TABLE work_item
    ADD COLUMN IF NOT EXISTS task_type TEXT NOT NULL DEFAULT 'core_path';

ALTER TABLE work_item
    ADD COLUMN IF NOT EXISTS blocking_mode TEXT NOT NULL DEFAULT 'hard';

ALTER TABLE work_item
    ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE work_item
    ADD COLUMN IF NOT EXISTS last_failure_reason TEXT;

ALTER TABLE work_item
    ADD COLUMN IF NOT EXISTS next_eligible_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS work_dependency (
    work_id TEXT NOT NULL REFERENCES work_item(id) ON DELETE CASCADE,
    depends_on_work_id TEXT NOT NULL REFERENCES work_item(id) ON DELETE CASCADE,
    PRIMARY KEY (work_id, depends_on_work_id),
    CHECK (work_id <> depends_on_work_id)
);

CREATE TABLE IF NOT EXISTS story_dependency (
    story_issue_number INTEGER NOT NULL,
    depends_on_story_issue_number INTEGER NOT NULL,
    PRIMARY KEY (story_issue_number, depends_on_story_issue_number),
    CHECK (story_issue_number <> depends_on_story_issue_number)
);

CREATE TABLE IF NOT EXISTS work_target (
    id BIGSERIAL PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES work_item(id) ON DELETE CASCADE,
    target_path TEXT NOT NULL,
    target_type work_target_type NOT NULL,
    owner_lane TEXT NOT NULL,
    is_frozen BOOLEAN NOT NULL DEFAULT FALSE,
    requires_human_approval BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS work_claim (
    work_id TEXT PRIMARY KEY REFERENCES work_item(id) ON DELETE CASCADE,
    worker_name TEXT NOT NULL,
    workspace_path TEXT NOT NULL,
    branch_name TEXT NOT NULL,
    lease_token TEXT,
    lease_expires_at TIMESTAMPTZ,
    claimed_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE work_claim
    ADD COLUMN IF NOT EXISTS lease_token TEXT;

ALTER TABLE work_claim
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS program_epic (
    issue_number INTEGER NOT NULL,
    repo TEXT NOT NULL,
    title TEXT NOT NULL,
    lane TEXT,
    program_status program_status NOT NULL DEFAULT 'approved',
    execution_status execution_status NOT NULL DEFAULT 'backlog',
    active_wave TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (repo, issue_number),
    CHECK (
        NOT (
            program_status <> 'approved'
            AND execution_status IN ('planned', 'decomposing', 'active')
        )
    )
);

CREATE TABLE IF NOT EXISTS program_story (
    issue_number INTEGER NOT NULL,
    repo TEXT NOT NULL,
    epic_issue_number INTEGER,
    title TEXT NOT NULL,
    lane TEXT,
    complexity TEXT,
    program_status program_status NOT NULL DEFAULT 'approved',
    execution_status execution_status NOT NULL DEFAULT 'backlog',
    active_wave TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (repo, issue_number),
    FOREIGN KEY (repo, epic_issue_number) REFERENCES program_epic(repo, issue_number) ON DELETE SET NULL,
    CHECK (
        NOT (
            program_status <> 'approved'
            AND execution_status IN ('planned', 'decomposing', 'active')
        )
    )
);

CREATE TABLE IF NOT EXISTS program_epic_dependency (
    repo TEXT NOT NULL,
    epic_issue_number INTEGER NOT NULL,
    depends_on_epic_issue_number INTEGER NOT NULL,
    PRIMARY KEY (repo, epic_issue_number, depends_on_epic_issue_number),
    FOREIGN KEY (repo, epic_issue_number) REFERENCES program_epic(repo, issue_number) ON DELETE CASCADE,
    FOREIGN KEY (repo, depends_on_epic_issue_number) REFERENCES program_epic(repo, issue_number) ON DELETE CASCADE,
    CHECK (epic_issue_number <> depends_on_epic_issue_number)
);

CREATE TABLE IF NOT EXISTS program_story_dependency (
    repo TEXT NOT NULL,
    story_issue_number INTEGER NOT NULL,
    depends_on_story_issue_number INTEGER NOT NULL,
    PRIMARY KEY (repo, story_issue_number, depends_on_story_issue_number),
    FOREIGN KEY (repo, story_issue_number) REFERENCES program_story(repo, issue_number) ON DELETE CASCADE,
    FOREIGN KEY (repo, depends_on_story_issue_number) REFERENCES program_story(repo, issue_number) ON DELETE CASCADE,
    CHECK (story_issue_number <> depends_on_story_issue_number)
);

CREATE TABLE IF NOT EXISTS execution_run (
    id BIGSERIAL PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES work_item(id) ON DELETE CASCADE,
    worker_name TEXT NOT NULL,
    status work_status NOT NULL,
    branch_name TEXT,
    command_digest TEXT,
    summary TEXT,
    exit_code INTEGER,
    elapsed_ms INTEGER,
    stdout_digest TEXT NOT NULL DEFAULT '',
    stderr_digest TEXT NOT NULL DEFAULT '',
    result_payload_json JSONB,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

ALTER TABLE execution_run
    ADD COLUMN IF NOT EXISTS result_payload_json JSONB;

CREATE TABLE IF NOT EXISTS verification_evidence (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES execution_run(id) ON DELETE CASCADE,
    work_id TEXT NOT NULL REFERENCES work_item(id) ON DELETE CASCADE,
    check_type TEXT NOT NULL,
    command TEXT NOT NULL,
    passed BOOLEAN NOT NULL,
    output_digest TEXT NOT NULL,
    exit_code INTEGER,
    elapsed_ms INTEGER,
    stdout_digest TEXT NOT NULL DEFAULT '',
    stderr_digest TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE verification_evidence
    ADD COLUMN IF NOT EXISTS work_id TEXT REFERENCES work_item(id) ON DELETE CASCADE;

CREATE TABLE IF NOT EXISTS pull_request_link (
    id BIGSERIAL PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES work_item(id) ON DELETE CASCADE,
    repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    pr_url TEXT NOT NULL,
    review_state TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS story_integration_run (
    id BIGSERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    story_issue_number INTEGER NOT NULL,
    merged BOOLEAN NOT NULL,
    promoted BOOLEAN NOT NULL DEFAULT FALSE,
    merge_commit_sha TEXT,
    promotion_commit_sha TEXT,
    blocked_reason TEXT,
    summary TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS story_verification_run (
    id BIGSERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    story_issue_number INTEGER NOT NULL,
    check_type TEXT NOT NULL,
    command TEXT NOT NULL,
    passed BOOLEAN NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    output_digest TEXT NOT NULL DEFAULT '',
    exit_code INTEGER,
    elapsed_ms INTEGER,
    stdout_digest TEXT NOT NULL DEFAULT '',
    stderr_digest TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS epic_execution_state (
    repo TEXT NOT NULL,
    epic_issue_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    completed_story_issue_numbers_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    blocked_story_issue_numbers_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    remaining_story_issue_numbers_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    blocked_reason_code TEXT,
    operator_attention_required BOOLEAN NOT NULL DEFAULT FALSE,
    last_progress_at TIMESTAMPTZ,
    stalled_since TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (repo, epic_issue_number),
    FOREIGN KEY (repo, epic_issue_number) REFERENCES program_epic(repo, issue_number) ON DELETE CASCADE
);

ALTER TABLE epic_execution_state
    ADD COLUMN IF NOT EXISTS last_progress_at TIMESTAMPTZ;

ALTER TABLE epic_execution_state
    ADD COLUMN IF NOT EXISTS stalled_since TIMESTAMPTZ;

ALTER TABLE epic_execution_state
    ADD COLUMN IF NOT EXISTS last_operator_action_at TIMESTAMPTZ;

ALTER TABLE epic_execution_state
    ADD COLUMN IF NOT EXISTS last_operator_action_reason TEXT;

ALTER TABLE epic_execution_state
    ADD COLUMN IF NOT EXISTS verification_status TEXT;

ALTER TABLE epic_execution_state
    ADD COLUMN IF NOT EXISTS verification_reason_code TEXT;

ALTER TABLE epic_execution_state
    ADD COLUMN IF NOT EXISTS last_verification_at TIMESTAMPTZ;

ALTER TABLE epic_execution_state
    ADD COLUMN IF NOT EXISTS verification_summary TEXT;

CREATE TABLE IF NOT EXISTS story_task_draft (
    id BIGSERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    story_issue_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    complexity TEXT NOT NULL,
    goal TEXT NOT NULL,
    allowed_paths_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    dod_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    verification_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    references_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'proposed',
    source_reason_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS story_pull_request_link (
    id BIGSERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    story_issue_number INTEGER NOT NULL,
    pull_number INTEGER NOT NULL,
    pull_url TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (repo, story_issue_number)
);

CREATE TABLE IF NOT EXISTS approval_event (
    id BIGSERIAL PRIMARY KEY,
    work_id TEXT NOT NULL REFERENCES work_item(id) ON DELETE CASCADE,
    approver TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS operator_request (
    id BIGSERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    epic_issue_number INTEGER NOT NULL,
    reason_code TEXT NOT NULL,
    summary TEXT NOT NULL,
    remaining_story_issue_numbers_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    blocked_story_issue_numbers_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'open',
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    closed_reason TEXT,
    FOREIGN KEY (repo, epic_issue_number) REFERENCES program_epic(repo, issue_number) ON DELETE CASCADE
);

ALTER TABLE operator_request
    ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ;

ALTER TABLE operator_request
    ADD COLUMN IF NOT EXISTS closed_reason TEXT;

CREATE TABLE IF NOT EXISTS natural_language_intent (
    id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    prompt TEXT NOT NULL,
    status TEXT NOT NULL,
    conversation_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    summary TEXT NOT NULL DEFAULT '',
    clarification_questions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    proposal_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    analysis_model TEXT,
    promoted_epic_issue_number INTEGER,
    approved_at TIMESTAMPTZ,
    approved_by TEXT,
    reviewed_at TIMESTAMPTZ,
    reviewed_by TEXT,
    review_action TEXT,
    review_feedback TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE natural_language_intent
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;

ALTER TABLE natural_language_intent
    ADD COLUMN IF NOT EXISTS approved_by TEXT;

ALTER TABLE natural_language_intent
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;

ALTER TABLE natural_language_intent
    ADD COLUMN IF NOT EXISTS reviewed_by TEXT;

ALTER TABLE natural_language_intent
    ADD COLUMN IF NOT EXISTS review_action TEXT;

ALTER TABLE natural_language_intent
    ADD COLUMN IF NOT EXISTS review_feedback TEXT;

CREATE TABLE IF NOT EXISTS execution_job (
    id BIGSERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    job_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    story_issue_number INTEGER,
    parent_epic_issue_number INTEGER,
    launch_backend TEXT,
    work_id TEXT,
    worker_name TEXT NOT NULL,
    pid INTEGER,
    command TEXT NOT NULL,
    log_path TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    exit_code INTEGER
);

ALTER TABLE execution_job
    ADD COLUMN IF NOT EXISTS parent_epic_issue_number INTEGER;

ALTER TABLE execution_job
    ADD COLUMN IF NOT EXISTS launch_backend TEXT;

CREATE TABLE IF NOT EXISTS work_commit_link (
    work_id TEXT PRIMARY KEY REFERENCES work_item(id) ON DELETE CASCADE,
    repo TEXT NOT NULL,
    issue_number INTEGER NOT NULL,
    commit_sha TEXT NOT NULL,
    commit_message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ========================================================================
-- Autonomous execution session layer (Phase A)
-- Supports long-running, checkpointable, resumable execution sessions.
-- ========================================================================

CREATE TABLE IF NOT EXISTS execution_session (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    work_id TEXT NOT NULL REFERENCES work_item(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active',
    attempt_index INT NOT NULL DEFAULT 1,
    parent_session_id UUID REFERENCES execution_session(id),
    current_phase TEXT NOT NULL,
    strategy_name TEXT,
    resume_token TEXT,
    waiting_reason TEXT,
    wake_after TIMESTAMPTZ,
    wake_condition_json JSONB,
    context_summary TEXT,
    last_checkpoint_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_heartbeat_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_execution_session_work_id
    ON execution_session (work_id);

CREATE INDEX IF NOT EXISTS idx_execution_session_status
    ON execution_session (status);

CREATE TABLE IF NOT EXISTS execution_checkpoint (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES execution_session(id) ON DELETE CASCADE,
    phase TEXT NOT NULL,
    phase_index INT NOT NULL DEFAULT 1,
    summary TEXT NOT NULL,
    artifacts_json JSONB,
    tool_state_json JSONB,
    subtasks_json JSONB,
    failure_context_json JSONB,
    next_action_hint TEXT,
    next_action_params_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_execution_checkpoint_session
    ON execution_checkpoint (session_id);

CREATE INDEX IF NOT EXISTS idx_execution_checkpoint_phase
    ON execution_checkpoint (session_id, phase, phase_index);

CREATE TABLE IF NOT EXISTS execution_wakeup (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES execution_session(id) ON DELETE CASCADE,
    work_id TEXT NOT NULL REFERENCES work_item(id),
    wake_type TEXT NOT NULL,
    wake_condition_json JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    scheduled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fired_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_execution_wakeup_scheduled
    ON execution_wakeup (status, scheduled_at);

CREATE INDEX IF NOT EXISTS idx_execution_wakeup_session
    ON execution_wakeup (session_id);

CREATE TABLE IF NOT EXISTS policy_resolution (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES execution_session(id),
    work_id TEXT NOT NULL REFERENCES work_item(id),
    risk_level TEXT NOT NULL,
    trigger_reason TEXT NOT NULL,
    evidence_json JSONB,
    resolution TEXT NOT NULL,
    resolution_detail_json JSONB,
    applied BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_policy_resolution_session
    ON policy_resolution (session_id);

CREATE INDEX IF NOT EXISTS idx_policy_resolution_unapplied
    ON policy_resolution (applied) WHERE applied = FALSE;

CREATE TABLE IF NOT EXISTS github_issue_import_batch (
    id BIGSERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS github_issue_snapshot (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT NOT NULL REFERENCES github_issue_import_batch(id) ON DELETE CASCADE,
    repo TEXT NOT NULL,
    issue_number INTEGER NOT NULL,
    raw_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS github_issue_normalized (
    repo TEXT NOT NULL,
    issue_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    url TEXT NOT NULL,
    github_state TEXT NOT NULL,
    import_state TEXT NOT NULL,
    issue_kind TEXT,
    lane TEXT,
    complexity TEXT,
    status_label TEXT,
    explicit_parent_issue_numbers JSONB NOT NULL DEFAULT '[]'::jsonb,
    explicit_story_dependency_issue_numbers JSONB NOT NULL DEFAULT '[]'::jsonb,
    explicit_task_dependency_issue_numbers JSONB NOT NULL DEFAULT '[]'::jsonb,
    anomaly_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_snapshot_id BIGINT NOT NULL REFERENCES github_issue_snapshot(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (repo, issue_number)
);

ALTER TABLE github_issue_normalized
    ADD COLUMN IF NOT EXISTS explicit_story_dependency_issue_numbers JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE github_issue_normalized
    ADD COLUMN IF NOT EXISTS explicit_task_dependency_issue_numbers JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS github_issue_relation (
    id BIGSERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    source_issue_number INTEGER NOT NULL,
    target_issue_number INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    confidence NUMERIC(4,3) NOT NULL,
    evidence_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS github_issue_completion_audit (
    repo TEXT NOT NULL,
    issue_number INTEGER NOT NULL,
    derived_complete BOOLEAN NOT NULL,
    reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (repo, issue_number)
);

DROP VIEW IF EXISTS v_active_task_queue;
DROP VIEW IF EXISTS v_story_decomposition_queue;
DROP VIEW IF EXISTS v_epic_decomposition_queue;
DROP VIEW IF EXISTS v_program_tree;

CREATE VIEW v_program_tree AS
SELECT
    e.repo,
    e.issue_number AS epic_issue_number,
    e.title AS epic_title,
    e.lane AS epic_lane,
    e.program_status AS epic_program_status,
    e.execution_status AS epic_execution_status,
    s.issue_number AS story_issue_number,
    s.title AS story_title,
    s.lane AS story_lane,
    s.program_status AS story_program_status,
    s.execution_status AS story_execution_status
FROM program_epic e
LEFT JOIN program_story s
  ON s.repo = e.repo AND s.epic_issue_number = e.issue_number;

CREATE VIEW v_active_task_queue AS
SELECT wi.*
FROM work_item wi
JOIN program_story s
  ON s.repo = wi.repo
 AND s.issue_number = wi.canonical_story_issue_number
JOIN program_epic e
  ON e.repo = s.repo
 AND e.issue_number = s.epic_issue_number
WHERE e.program_status = 'approved'
  AND s.program_status = 'approved'
  AND e.execution_status = 'active'
  AND s.execution_status = 'active'
  AND NOT EXISTS (
      SELECT 1
      FROM program_epic_dependency ped
      JOIN program_epic dep
        ON dep.repo = ped.repo
       AND dep.issue_number = ped.depends_on_epic_issue_number
      WHERE ped.repo = e.repo
        AND ped.epic_issue_number = e.issue_number
        AND dep.execution_status NOT IN ('active', 'done')
  )
  AND NOT EXISTS (
      SELECT 1
      FROM program_story_dependency psd
      JOIN program_story dep
        ON dep.repo = psd.repo
       AND dep.issue_number = psd.depends_on_story_issue_number
       WHERE psd.repo = s.repo
         AND psd.story_issue_number = s.issue_number
         AND dep.execution_status NOT IN ('active', 'done')
   );

CREATE VIEW v_story_decomposition_queue AS
SELECT
    s.repo,
    e.issue_number AS epic_issue_number,
    e.title AS epic_title,
    s.issue_number AS story_issue_number,
    s.title AS story_title,
    s.execution_status,
    COUNT(wi.id) AS story_task_count
FROM program_story s
JOIN program_epic e
  ON e.repo = s.repo
 AND e.issue_number = s.epic_issue_number
LEFT JOIN work_item wi
  ON wi.repo = s.repo
 AND wi.canonical_story_issue_number = s.issue_number
WHERE e.program_status = 'approved'
  AND s.program_status = 'approved'
  AND e.execution_status = 'active'
  AND s.execution_status = 'decomposing'
GROUP BY
    s.repo,
    e.issue_number,
    e.title,
    s.issue_number,
    s.title,
    s.execution_status;

CREATE VIEW v_epic_decomposition_queue AS
SELECT
    e.repo,
    e.issue_number AS epic_issue_number,
    e.title AS epic_title,
    e.execution_status,
    COUNT(s.issue_number) AS epic_story_count
FROM program_epic e
LEFT JOIN program_story s
  ON s.repo = e.repo
 AND s.epic_issue_number = e.issue_number
WHERE e.program_status = 'approved'
  AND e.execution_status = 'decomposing'
GROUP BY
    e.repo,
    e.issue_number,
    e.title,
    e.execution_status;

CREATE INDEX IF NOT EXISTS idx_work_item_repo
    ON work_item (repo);

CREATE INDEX IF NOT EXISTS idx_work_item_status_wave
    ON work_item (status, wave);

CREATE INDEX IF NOT EXISTS idx_work_item_canonical_story_issue_number
    ON work_item (canonical_story_issue_number);
