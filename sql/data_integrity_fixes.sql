-- ============================================================================
-- Data Integrity Views and Constraints for Stardrifter Orchestration
-- ============================================================================
-- Purpose: Add database-level checks for work_item data integrity
-- Date: 2026-03-23
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Work Item Integrity Check View
-- Identifies work items with missing or inconsistent data
-- ----------------------------------------------------------------------------

DROP VIEW IF EXISTS v_work_item_integrity_check;

CREATE VIEW v_work_item_integrity_check AS
SELECT
    wi.id,
    wi.title,
    wi.lane,
    wi.wave,
    wi.status,
    wi.repo,
    wi.canonical_story_issue_number,
    wi.source_issue_number,
    CASE
        WHEN wi.repo IS NULL AND wi.canonical_story_issue_number IS NOT NULL
            THEN 'missing_repo'
        WHEN wi.canonical_story_issue_number IS NULL AND wi.source_issue_number IS NOT NULL
            THEN 'missing_canonical_story_link'
        WHEN wi.wave IS NULL
            THEN 'missing_wave'
        ELSE NULL
    END as issue_type,
    ps.epic_issue_number,
    pe.active_wave as epic_active_wave,
    ps.active_wave as story_active_wave
FROM work_item wi
LEFT JOIN program_story ps
    ON ps.issue_number = wi.canonical_story_issue_number
    AND ps.repo = wi.repo
LEFT JOIN program_epic pe
    ON pe.issue_number = ps.epic_issue_number
    AND pe.repo = ps.repo
WHERE wi.status IN ('pending', 'ready', 'blocked')
  AND (
      wi.repo IS NULL
      OR wi.canonical_story_issue_number IS NULL
      OR wi.wave IS NULL
  );

-- ----------------------------------------------------------------------------
-- 2. Wave Consistency Check View
-- Identifies work items where wave doesn't match parent Epic/Story
-- ----------------------------------------------------------------------------

DROP VIEW IF EXISTS v_wave_consistency_check;

CREATE VIEW v_wave_consistency_check AS
SELECT
    wi.id as work_item_id,
    wi.title as work_item_title,
    wi.wave as work_item_wave,
    ps.issue_number as story_issue_number,
    ps.active_wave as story_active_wave,
    pe.issue_number as epic_issue_number,
    pe.active_wave as epic_active_wave,
    CASE
        WHEN pe.active_wave IS NOT NULL AND wi.wave != pe.active_wave
            THEN 'epic_wave_mismatch'
        WHEN ps.active_wave IS NOT NULL AND wi.wave != ps.active_wave
            THEN 'story_wave_mismatch'
        ELSE NULL
    END as issue_type
FROM work_item wi
JOIN program_story ps
    ON ps.issue_number = wi.canonical_story_issue_number
    AND ps.repo = wi.repo
JOIN program_epic pe
    ON pe.issue_number = ps.epic_issue_number
    AND pe.repo = ps.repo
WHERE wi.status IN ('pending', 'ready', 'in_progress')
  AND wi.wave IS NOT NULL
  AND (
      (pe.active_wave IS NOT NULL AND wi.wave != pe.active_wave)
      OR (ps.active_wave IS NOT NULL AND wi.wave != ps.active_wave)
  );

-- ----------------------------------------------------------------------------
-- 3. Orphan Work Items View
-- Identifies work items that cannot be executed due to missing associations
-- ----------------------------------------------------------------------------

DROP VIEW IF EXISTS v_orphan_work_items;

CREATE VIEW v_orphan_work_items AS
SELECT
    wi.id,
    wi.title,
    wi.status,
    wi.lane,
    wi.wave,
    wi.repo,
    wi.canonical_story_issue_number,
    wi.source_issue_number,
    'no_canonical_story' as orphan_reason
FROM work_item wi
WHERE wi.canonical_story_issue_number IS NULL
  AND wi.source_issue_number IS NOT NULL
  AND wi.status IN ('pending', 'ready')
UNION ALL
SELECT
    wi.id,
    wi.title,
    wi.status,
    wi.lane,
    wi.wave,
    wi.repo,
    wi.canonical_story_issue_number,
    wi.source_issue_number,
    'repo_mismatch' as orphan_reason
FROM work_item wi
LEFT JOIN program_story ps
    ON ps.issue_number = wi.canonical_story_issue_number
    AND ps.repo = wi.repo
WHERE wi.canonical_story_issue_number IS NOT NULL
  AND ps.issue_number IS NULL
  AND wi.status IN ('pending', 'ready');

-- ----------------------------------------------------------------------------
-- 4. Function to validate work_item before status change to 'ready'
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION validate_work_item_ready()
RETURNS TRIGGER AS $$
DECLARE
    v_epic_wave TEXT;
    v_story_wave TEXT;
    v_epic_status TEXT;
    v_story_status TEXT;
BEGIN
    -- Only validate when transitioning to 'ready' or 'pending'
    IF NEW.status IN ('ready', 'pending') THEN
        -- Check repo is set for story-linked work items
        IF NEW.canonical_story_issue_number IS NOT NULL AND NEW.repo IS NULL THEN
            RAISE EXCEPTION 'work_item with canonical_story must have repo set (work_id: %)', NEW.id;
        END IF;

        -- Check wave is set
        IF NEW.wave IS NULL THEN
            RAISE EXCEPTION 'work_item must have wave set (work_id: %)', NEW.id;
        END IF;

        -- Check Epic and Story exist and are active
        IF NEW.canonical_story_issue_number IS NOT NULL AND NEW.repo IS NOT NULL THEN
            SELECT pe.active_wave, pe.execution_status, ps.active_wave, ps.execution_status
            INTO v_epic_wave, v_epic_status, v_story_wave, v_story_status
            FROM program_story ps
            JOIN program_epic pe ON pe.issue_number = ps.epic_issue_number AND pe.repo = ps.repo
            WHERE ps.issue_number = NEW.canonical_story_issue_number
              AND ps.repo = NEW.repo;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'work_item references non-existent story (work_id: %, story: %)',
                    NEW.id, NEW.canonical_story_issue_number;
            END IF;

            -- Check Epic is active
            IF v_epic_status NOT IN ('active', 'decomposing') THEN
                RAISE NOTICE 'work_item Epic is not active (work_id: %, epic_status: %)',
                    NEW.id, v_epic_status;
            END IF;

            -- Check Story is active
            IF v_story_status NOT IN ('active', 'decomposing') THEN
                RAISE NOTICE 'work_item Story is not active (work_id: %, story_status: %)',
                    NEW.id, v_story_status;
            END IF;

            -- Wave consistency check (warning only, not blocking)
            IF v_epic_wave IS NOT NULL AND NEW.wave != v_epic_wave THEN
                RAISE WARNING 'work_item wave (%) does not match Epic wave (%) (work_id: %)',
                    NEW.wave, v_epic_wave, NEW.id;
            END IF;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ----------------------------------------------------------------------------
-- 5. Trigger to validate work_item on status change
-- Note: Currently set to NOTICE level to not break existing workflows
-- Enable strict mode by changing to RAISE EXCEPTION
-- ----------------------------------------------------------------------------

DROP TRIGGER IF EXISTS trg_validate_work_item_ready ON work_item;

CREATE TRIGGER trg_validate_work_item_ready
    BEFORE UPDATE OF status ON work_item
    FOR EACH ROW
    WHEN (OLD.status IS DISTINCT FROM NEW.status)
    EXECUTE FUNCTION validate_work_item_ready();

-- ----------------------------------------------------------------------------
-- 6. Data Repair Helper Function
-- Automatically fixes common data integrity issues
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION repair_work_item_data()
RETURNS TABLE (
    work_id TEXT,
    repair_type TEXT,
    old_value TEXT,
    new_value TEXT,
    success BOOLEAN
) AS $$
DECLARE
    r RECORD;
    v_repo TEXT := 'codefromkarl/stardrifter';
BEGIN
    -- Repair 1: Set repo for work items with canonical_story but NULL repo
    FOR r IN
        SELECT wi.id, wi.repo
        FROM work_item wi
        WHERE wi.canonical_story_issue_number IS NOT NULL
          AND wi.repo IS NULL
    LOOP
        UPDATE work_item SET repo = v_repo WHERE id = r.id;
        work_id := r.id;
        repair_type := 'set_repo';
        old_value := r.repo::TEXT;
        new_value := v_repo;
        success := TRUE;
        RETURN NEXT;
    END LOOP;

    -- Repair 2: Set canonical_story_issue_number from source_issue_number
    FOR r IN
        SELECT wi.id, wi.canonical_story_issue_number, wi.source_issue_number
        FROM work_item wi
        WHERE wi.canonical_story_issue_number IS NULL
          AND wi.source_issue_number IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM program_story ps
              WHERE ps.issue_number = wi.source_issue_number
          )
    LOOP
        UPDATE work_item
        SET canonical_story_issue_number = r.source_issue_number
        WHERE id = r.id;
        work_id := r.id;
        repair_type := 'set_canonical_story';
        old_value := r.canonical_story_issue_number::TEXT;
        new_value := r.source_issue_number::TEXT;
        success := TRUE;
        RETURN NEXT;
    END LOOP;

    -- Repair 3: Inherit wave from parent Story
    FOR r IN
        SELECT wi.id, wi.wave, ps.active_wave
        FROM work_item wi
        JOIN program_story ps ON ps.issue_number = wi.canonical_story_issue_number AND ps.repo = wi.repo
        WHERE wi.wave IS NULL
          AND ps.active_wave IS NOT NULL
    LOOP
        UPDATE work_item SET wave = r.active_wave WHERE id = r.id;
        work_id := r.id;
        repair_type := 'inherit_wave_from_story';
        old_value := r.wave::TEXT;
        new_value := r.active_wave;
        success := TRUE;
        RETURN NEXT;
    END LOOP;

END;
$$ LANGUAGE plpgsql;

-- ----------------------------------------------------------------------------
-- 7. Updated v_active_task_queue with integrity checks
-- Only includes work items that pass all integrity checks
-- ----------------------------------------------------------------------------

DROP VIEW IF EXISTS v_active_task_queue_strict;

CREATE VIEW v_active_task_queue_strict AS
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
  AND wi.repo IS NOT NULL
  AND wi.wave IS NOT NULL
  AND (e.active_wave IS NULL OR wi.wave = e.active_wave)
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

-- ----------------------------------------------------------------------------
-- 8. Grant permissions
-- ----------------------------------------------------------------------------

COMMENT ON VIEW v_work_item_integrity_check IS
    'Identifies work items with missing or inconsistent data (NULL fields)';

COMMENT ON VIEW v_wave_consistency_check IS
    'Identifies work items where wave does not match parent Epic/Story';

COMMENT ON VIEW v_orphan_work_items IS
    'Identifies work items that cannot be executed due to missing associations';

COMMENT ON FUNCTION validate_work_item_ready() IS
    'Validates work_item data before status change to ready/pending';

COMMENT ON FUNCTION repair_work_item_data() IS
    'Automatically fixes common data integrity issues in work_item table';

COMMENT ON VIEW v_active_task_queue_strict IS
    'Stricter version of v_active_task_queue with integrity checks';
