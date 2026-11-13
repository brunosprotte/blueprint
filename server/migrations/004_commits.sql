-- F4 — status do commit (reconcile) + idempotência por (repo_id, sha).
ALTER TABLE commits ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'present';

ALTER TABLE commits DROP CONSTRAINT IF EXISTS commits_status_check;
ALTER TABLE commits ADD CONSTRAINT commits_status_check CHECK (status IN ('present','orphaned'));

CREATE UNIQUE INDEX IF NOT EXISTS commits_repo_sha_uniq
    ON commits (repo_id, sha);

CREATE INDEX IF NOT EXISTS commits_repo_created_idx
    ON commits (repo_id, created_at DESC);
