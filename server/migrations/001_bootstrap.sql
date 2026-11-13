-- 001_bootstrap.sql — schema inicial do servidor SDD (design master §8 + §8.1)
-- Contrato §4: FK com on delete cascade, exceto referências a `users`
-- (demands.created_by) — usuário não some junto com o histórico.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text primary key,
    applied_at timestamptz not null default now()
);

CREATE TABLE IF NOT EXISTS users (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    github_id   bigint NOT NULL UNIQUE,
    login       text NOT NULL,
    email       text,
    avatar_url  text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS repos (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner          text NOT NULL,
    name           text NOT NULL,
    default_branch text NOT NULL DEFAULT 'main',
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (owner, name)
);

CREATE TABLE IF NOT EXISTS tokens (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    repo_id      uuid REFERENCES repos(id) ON DELETE CASCADE,
    token_hash   text NOT NULL UNIQUE,
    scopes       text[] NOT NULL DEFAULT '{}',
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    revoked_at   timestamptz
);

CREATE TABLE IF NOT EXISTS sessions (
    id         text PRIMARY KEY,
    user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS demands (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id     uuid REFERENCES repos(id) ON DELETE CASCADE,
    module      text,
    title       text NOT NULL,
    body        text,
    status      text NOT NULL DEFAULT 'open',
    claimed_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    claimed_at  timestamptz,
    created_by  uuid REFERENCES users(id) ON DELETE RESTRICT,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS artifacts (
    id         text PRIMARY KEY,
    demand_id  uuid REFERENCES demands(id) ON DELETE CASCADE,
    repo_id    uuid REFERENCES repos(id) ON DELETE CASCADE,
    kind       text NOT NULL,
    module     text,
    feature    text,
    path       text,
    sha        text,
    status     text NOT NULL DEFAULT 'draft',
    version    text,
    content    text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS spec_edges (
    parent_id text NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    child_id  text NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    type      text NOT NULL,
    PRIMARY KEY (parent_id, child_id, type)
);

CREATE TABLE IF NOT EXISTS doubts (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id text NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    question    text NOT NULL,
    status      text NOT NULL DEFAULT 'pending',
    source      text,
    raised_at   timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz
);

CREATE TABLE IF NOT EXISTS commits (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    demand_id  uuid REFERENCES demands(id) ON DELETE CASCADE,
    repo_id    uuid REFERENCES repos(id) ON DELETE CASCADE,
    sha        text NOT NULL,
    message    text,
    branch     text,
    author     text,
    files      jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reviews (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    commit_id  uuid REFERENCES commits(id) ON DELETE CASCADE,
    demand_id  uuid REFERENCES demands(id) ON DELETE CASCADE,
    verdict    text NOT NULL,
    findings   jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id text REFERENCES artifacts(id) ON DELETE CASCADE,
    demand_id   uuid REFERENCES demands(id) ON DELETE CASCADE,
    source_kind text NOT NULL,
    heading     text,
    text        text NOT NULL,
    token_count int,
    tsv         tsvector,
    corpus_id   text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS events (
    id          bigserial PRIMARY KEY,
    demand_id   uuid REFERENCES demands(id) ON DELETE CASCADE,
    artifact_id text REFERENCES artifacts(id) ON DELETE CASCADE,
    type        text NOT NULL,
    payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
    actor       uuid REFERENCES users(id) ON DELETE SET NULL,
    at          timestamptz NOT NULL DEFAULT now()
);

-- Índices — design master §8.1
CREATE INDEX IF NOT EXISTS demands_repo_status_idx   ON demands (repo_id, status);
CREATE INDEX IF NOT EXISTS artifacts_demand_kind_idx ON artifacts (demand_id, kind);
CREATE INDEX IF NOT EXISTS artifacts_repo_path_idx   ON artifacts (repo_id, path);
CREATE INDEX IF NOT EXISTS commits_demand_created_idx ON commits (demand_id, created_at DESC);
CREATE INDEX IF NOT EXISTS reviews_demand_idx        ON reviews (demand_id);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin            ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS events_demand_at_idx      ON events (demand_id, at DESC);
