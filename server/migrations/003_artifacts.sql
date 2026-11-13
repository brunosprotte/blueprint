-- F4 — colunas aditivas de artefato + índices de sync e de grafo.
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS doubts_index  text;
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS doubts_content text;

CREATE UNIQUE INDEX IF NOT EXISTS artifacts_repo_path_uniq
    ON artifacts (repo_id, path)
    WHERE repo_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS artifacts_demand_status_idx
    ON artifacts (demand_id, status);

CREATE UNIQUE INDEX IF NOT EXISTS spec_edges_uniq
    ON spec_edges (parent_id, child_id, type);

CREATE INDEX IF NOT EXISTS spec_edges_child_idx
    ON spec_edges (child_id);

CREATE INDEX IF NOT EXISTS doubts_artifact_idx
    ON doubts (artifact_id);
