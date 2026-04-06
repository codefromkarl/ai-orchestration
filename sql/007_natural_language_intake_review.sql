-- Natural language intake review metadata migration
-- Keeps review / approval fields available as a forward-compatible edge contract.

ALTER TABLE IF EXISTS natural_language_intent
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;

ALTER TABLE IF EXISTS natural_language_intent
    ADD COLUMN IF NOT EXISTS approved_by TEXT;

ALTER TABLE IF EXISTS natural_language_intent
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;

ALTER TABLE IF EXISTS natural_language_intent
    ADD COLUMN IF NOT EXISTS reviewed_by TEXT;

ALTER TABLE IF EXISTS natural_language_intent
    ADD COLUMN IF NOT EXISTS review_action TEXT;

ALTER TABLE IF EXISTS natural_language_intent
    ADD COLUMN IF NOT EXISTS review_feedback TEXT;
