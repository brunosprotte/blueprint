-- F4 — índices de fila e de ownership.
CREATE INDEX IF NOT EXISTS demands_open_queue_idx
    ON demands (repo_id, created_at)
    WHERE status = 'open';

CREATE INDEX IF NOT EXISTS demands_claimed_by_idx
    ON demands (claimed_by)
    WHERE claimed_by IS NOT NULL;
