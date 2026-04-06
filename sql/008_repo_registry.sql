CREATE TABLE IF NOT EXISTS repo_registry (
    repo TEXT PRIMARY KEY,
    workdir TEXT NOT NULL,
    log_dir TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_repo_registry_updated_at
    ON repo_registry (updated_at DESC);
