DROP VIEW IF EXISTS nocodb_verification_and_pr;
DROP VIEW IF EXISTS nocodb_blocked_queue;
DROP VIEW IF EXISTS nocodb_task_board;
DROP VIEW IF EXISTS nocodb_epic_hierarchy;

CREATE OR REPLACE VIEW nocodb_task_board AS
SELECT
    wi.id,
    wi.title,
    wi.lane,
    wi.wave,
    wi.status,
    wi.complexity,
    wi.blocked_reason,
    wi.decision_required,
    wi.source_issue_number,
    wi.allowed_branch_prefix,
    wi.created_at,
    wi.updated_at
FROM work_item wi;

CREATE OR REPLACE VIEW nocodb_blocked_queue AS
SELECT
    wi.id,
    wi.title,
    wi.lane,
    wi.wave,
    wi.status,
    wi.blocked_reason,
    wi.decision_required,
    wt.target_path,
    wt.owner_lane,
    wt.is_frozen,
    wt.requires_human_approval
FROM work_item wi
JOIN work_target wt ON wt.work_id = wi.id
WHERE wi.status = 'blocked';

CREATE OR REPLACE VIEW nocodb_verification_and_pr AS
SELECT
    wi.id AS work_id,
    wi.title,
    er.worker_name,
    er.status AS run_status,
    er.command_digest,
    er.summary,
    er.exit_code AS run_exit_code,
    er.elapsed_ms AS run_elapsed_ms,
    er.stdout_digest AS run_stdout_digest,
    er.stderr_digest AS run_stderr_digest,
    er.result_payload_json,
    ve.check_type,
    ve.command AS verification_command,
    ve.passed,
    ve.output_digest,
    ve.exit_code AS verification_exit_code,
    ve.elapsed_ms AS verification_elapsed_ms,
    ve.stdout_digest AS verification_stdout_digest,
    ve.stderr_digest AS verification_stderr_digest,
    pr.repo,
    pr.pr_number,
    pr.pr_url,
    pr.review_state
FROM work_item wi
LEFT JOIN LATERAL (
    SELECT *
    FROM execution_run er1
    WHERE er1.work_id = wi.id
    ORDER BY er1.id DESC
    LIMIT 1
) er ON TRUE
LEFT JOIN LATERAL (
    SELECT *
    FROM verification_evidence ve1
    WHERE ve1.run_id = er.id
    ORDER BY ve1.id DESC
    LIMIT 1
) ve ON TRUE
LEFT JOIN LATERAL (
    SELECT *
    FROM pull_request_link pr1
    WHERE pr1.work_id = wi.id
    ORDER BY pr1.id DESC
    LIMIT 1
) pr ON TRUE;

CREATE OR REPLACE VIEW nocodb_epic_hierarchy AS
WITH epics AS (
    SELECT repo, issue_number, title, github_state, status_label, url
    FROM github_issue_normalized
    WHERE issue_kind = 'epic'
),
stories AS (
    SELECT
        s.repo,
        s.issue_number       AS story_number,
        s.title              AS story_title,
        s.github_state       AS story_state,
        s.status_label       AS story_status_label,
        s.url                AS story_url,
        parent_ref.epic_number
    FROM github_issue_normalized s
    CROSS JOIN LATERAL (
        SELECT elem::int AS epic_number
        FROM jsonb_array_elements_text(s.explicit_parent_issue_numbers) AS elem
        LIMIT 1
    ) parent_ref
    WHERE s.issue_kind = 'story'
),
tasks AS (
    SELECT
        t.repo,
        t.issue_number       AS task_number,
        t.title              AS task_title,
        t.github_state       AS task_state,
        t.status_label       AS task_status_label,
        t.lane               AS task_lane,
        t.complexity         AS task_complexity,
        t.url                AS task_url,
        parent_ref.story_number
    FROM github_issue_normalized t
    CROSS JOIN LATERAL (
        SELECT elem::int AS story_number
        FROM jsonb_array_elements_text(t.explicit_parent_issue_numbers) AS elem
        LIMIT 1
    ) parent_ref
    WHERE t.issue_kind = 'task'
)
SELECT
    e.repo,
    e.issue_number          AS epic_number,
    e.title                 AS epic_title,
    e.github_state          AS epic_state,
    e.status_label          AS epic_status_label,
    s.story_number,
    s.story_title,
    s.story_state,
    s.story_status_label,
    t.task_number,
    t.task_title,
    t.task_state,
    t.task_status_label,
    t.task_lane,
    t.task_complexity
FROM epics e
LEFT JOIN stories s ON s.repo = e.repo AND s.epic_number = e.issue_number
LEFT JOIN tasks  t ON t.repo = s.repo  AND t.story_number = s.story_number
ORDER BY e.issue_number, s.story_number NULLS LAST, t.task_number NULLS LAST;
