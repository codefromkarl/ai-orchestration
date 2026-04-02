-- ============================================================================
-- Data Integrity Triggers for Taskplane
-- ============================================================================
-- Purpose: Automatically inherit repo and wave from parent Story/Epic
--          to ensure data consistency at the source
-- Date: 2026-03-23
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Trigger 1: Auto-inherit repo from program_story on INSERT/UPDATE
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION trg_inherit_work_item_repo()
RETURNS TRIGGER AS $$
BEGIN
    -- Only process when repo is NULL and canonical_story_issue_number is set
    IF NEW.repo IS NULL AND NEW.canonical_story_issue_number IS NOT NULL THEN
        SELECT ps.repo INTO NEW.repo
        FROM program_story ps
        WHERE ps.issue_number = NEW.canonical_story_issue_number;

        IF NEW.repo IS NULL THEN
            -- Try to find the story in any repo
            SELECT ps.repo INTO NEW.repo
            FROM program_story ps
            WHERE ps.issue_number = NEW.canonical_story_issue_number
            LIMIT 1;

            IF NEW.repo IS NULL THEN
                RAISE EXCEPTION 'Cannot inherit repo: story #% does not exist in program_story',
                    NEW.canonical_story_issue_number;
            END IF;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_inherit_work_item_repo_before_insert ON work_item;

CREATE TRIGGER trg_inherit_work_item_repo_before_insert
    BEFORE INSERT ON work_item
    FOR EACH ROW
    EXECUTE FUNCTION trg_inherit_work_item_repo();

-- ----------------------------------------------------------------------------
-- Trigger 2: Auto-inherit wave from parent Epic on INSERT/UPDATE
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION trg_inherit_work_item_wave()
RETURNS TRIGGER AS $$
DECLARE
    v_epic_wave TEXT;
    v_story_wave TEXT;
BEGIN
    -- Only process when wave is NULL or 'unassigned'
    IF (NEW.wave IS NULL OR NEW.wave = 'unassigned')
       AND NEW.canonical_story_issue_number IS NOT NULL THEN

        -- First try to get wave from parent Epic
        SELECT pe.active_wave, ps.active_wave
        INTO v_epic_wave, v_story_wave
        FROM program_story ps
        JOIN program_epic pe ON pe.issue_number = ps.epic_issue_number
                             AND pe.repo = ps.repo
        WHERE ps.issue_number = NEW.canonical_story_issue_number;

        -- Priority: Epic wave > Story wave > 'Wave0' (default)
        IF v_epic_wave IS NOT NULL THEN
            NEW.wave := v_epic_wave;
        ELSIF v_story_wave IS NOT NULL THEN
            NEW.wave := v_story_wave;
        ELSE
            NEW.wave := 'Wave0';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_inherit_work_item_wave_before_insert ON work_item;

CREATE TRIGGER trg_inherit_work_item_wave_before_insert
    BEFORE INSERT OR UPDATE ON work_item
    FOR EACH ROW
    EXECUTE FUNCTION trg_inherit_work_item_wave();

-- ----------------------------------------------------------------------------
-- Trigger 3: Sync repo when canonical_story_issue_number changes
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION trg_sync_repo_on_story_change()
RETURNS TRIGGER AS $$
BEGIN
    -- When canonical_story_issue_number changes, update repo to match
    IF NEW.canonical_story_issue_number IS DISTINCT FROM OLD.canonical_story_issue_number
       AND NEW.canonical_story_issue_number IS NOT NULL THEN

        SELECT ps.repo INTO NEW.repo
        FROM program_story ps
        WHERE ps.issue_number = NEW.canonical_story_issue_number
        LIMIT 1;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sync_repo_on_story_change ON work_item;

CREATE TRIGGER trg_sync_repo_on_story_change
    BEFORE UPDATE OF canonical_story_issue_number ON work_item
    FOR EACH ROW
    EXECUTE FUNCTION trg_sync_repo_on_story_change();

-- ----------------------------------------------------------------------------
-- Trigger 4: Validate data integrity before INSERT/UPDATE
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION trg_validate_work_item_integrity()
RETURNS TRIGGER AS $$
DECLARE
    v_story_exists BOOLEAN;
    v_epic_status TEXT;
    v_story_status TEXT;
BEGIN
    -- Validate canonical_story_issue_number exists
    IF NEW.canonical_story_issue_number IS NOT NULL THEN
        SELECT EXISTS(
            SELECT 1 FROM program_story
            WHERE issue_number = NEW.canonical_story_issue_number
        ) INTO v_story_exists;

        IF NOT v_story_exists THEN
            RAISE WARNING 'work_item references non-existent story #%',
                NEW.canonical_story_issue_number;
        END IF;
    END IF;

    -- Validate wave is set
    IF NEW.wave IS NULL THEN
        RAISE EXCEPTION 'work_item wave cannot be NULL (work_id: %)', NEW.id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_validate_work_item_integrity ON work_item;

CREATE TRIGGER trg_validate_work_item_integrity
    BEFORE INSERT OR UPDATE ON work_item
    FOR EACH ROW
    EXECUTE FUNCTION trg_validate_work_item_integrity();

-- ----------------------------------------------------------------------------
-- Helper Function: Backfill existing work_items with missing repo/wave
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION backfill_work_item_integrity()
RETURNS TABLE (
    work_id TEXT,
    repair_type TEXT,
    old_value TEXT,
    new_value TEXT,
    repaired BOOLEAN
) AS $$
DECLARE
    r RECORD;
BEGIN
    -- Repair 1: Backfill repo from program_story
    FOR r IN
        SELECT wi.id, wi.repo as old_repo, ps.repo as new_repo
        FROM work_item wi
        JOIN program_story ps ON ps.issue_number = wi.canonical_story_issue_number
        WHERE wi.repo IS NULL
          AND wi.canonical_story_issue_number IS NOT NULL
    LOOP
        UPDATE work_item SET repo = r.new_repo WHERE id = r.id;
        work_id := r.id;
        repair_type := 'backfill_repo_from_story';
        old_value := r.old_repo::TEXT;
        new_value := r.new_repo;
        repaired := TRUE;
        RETURN NEXT;
    END LOOP;

    -- Repair 2: Backfill wave from parent Epic
    FOR r IN
        SELECT wi.id, wi.wave as old_wave,
               COALESCE(pe.active_wave, ps.active_wave, 'Wave0') as new_wave
        FROM work_item wi
        JOIN program_story ps ON ps.issue_number = wi.canonical_story_issue_number AND ps.repo = wi.repo
        JOIN program_epic pe ON pe.issue_number = ps.epic_issue_number AND pe.repo = ps.repo
        WHERE (wi.wave IS NULL OR wi.wave = 'unassigned')
    LOOP
        UPDATE work_item SET wave = r.new_wave WHERE id = r.id;
        work_id := r.id;
        repair_type := 'backfill_wave_from_epic';
        old_value := r.old_wave::TEXT;
        new_value := r.new_wave;
        repaired := TRUE;
        RETURN NEXT;
    END LOOP;

    -- Repair 3: Fix 'unassigned' wave to actual wave from parent
    FOR r IN
        SELECT wi.id, wi.wave as old_wave,
               COALESCE(pe.active_wave, ps.active_wave, 'Wave0') as new_wave
        FROM work_item wi
        JOIN program_story ps ON ps.issue_number = wi.canonical_story_issue_number AND ps.repo = wi.repo
        JOIN program_epic pe ON pe.issue_number = ps.epic_issue_number AND pe.repo = ps.repo
        WHERE wi.wave = 'unassigned'
          AND (pe.active_wave IS NOT NULL OR ps.active_wave IS NOT NULL)
    LOOP
        UPDATE work_item SET wave = r.new_wave WHERE id = r.id;
        work_id := r.id;
        repair_type := 'fix_unassigned_wave';
        old_value := r.old_wave;
        new_value := r.new_wave;
        repaired := TRUE;
        RETURN NEXT;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- ----------------------------------------------------------------------------
-- Comments
-- ----------------------------------------------------------------------------

COMMENT ON FUNCTION trg_inherit_work_item_repo() IS
    'Trigger function to auto-inherit repo from program_story on INSERT';

COMMENT ON FUNCTION trg_inherit_work_item_wave() IS
    'Trigger function to auto-inherit wave from parent Epic on INSERT/UPDATE';

COMMENT ON FUNCTION trg_sync_repo_on_story_change() IS
    'Trigger function to sync repo when canonical_story_issue_number changes';

COMMENT ON FUNCTION trg_validate_work_item_integrity() IS
    'Trigger function to validate work_item data integrity';

COMMENT ON FUNCTION backfill_work_item_integrity() IS
    'Helper function to backfill missing repo and wave for existing work_items';
