-- 005_rag.sql — F7 (RAG)

-- 1) Chave de idempotência da origem dentro do corpus.
--    source_ref: path relativo a docs/ (corpus 'method') | artifact_id (corpus de repo)
--    | sha do commit | id da review.
ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS source_ref text NOT NULL DEFAULT '';

-- 2) Reindexar não duplica chunk.
--    A chave inclui `heading` e o hash do corpo: um mesmo `source_ref` (path de docs/,
--    artifact_id, sha, id de review) gera UM chunk por seção H2/H3 — e seções homônimas
--    existem no método (`## BR` aparece duas vezes em META-006). Sem `heading`/corpo na
--    chave, `index_method`/`index_artifact` violariam a unicidade ao gravá-los.
--    O índice garante: mesma origem + mesmo heading + mesmo corpo = chunk duplicado.
CREATE UNIQUE INDEX IF NOT EXISTS chunks_source_ref_uniq
    ON chunks (corpus_id, source_kind, source_ref, heading, md5(coalesce(text, '')))
    WHERE source_ref <> '';

-- 3) tsv preenchida por trigger.
--    Coluna generated seria a alternativa, mas exigiria dropar a coluna tsv criada
--    por F1 (Contrato Comum §4: nunca reescrever tabela). O trigger cobre o mesmo
--    papel sem tocar no DDL canônico.
CREATE OR REPLACE FUNCTION chunks_tsv_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.tsv := to_tsvector('portuguese',
                            coalesce(NEW.heading, '') || ' ' || coalesce(NEW.text, ''));
    RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER chunks_tsv
    BEFORE INSERT OR UPDATE OF heading, text ON chunks
    FOR EACH ROW EXECUTE FUNCTION chunks_tsv_update();

-- 4) Índice do FTS.
CREATE INDEX IF NOT EXISTS chunks_tsv_gin ON chunks USING GIN (tsv);

-- 5) Filtro de corpus (invariante: o corpus nunca cruza corpora).
CREATE INDEX IF NOT EXISTS chunks_corpus_idx ON chunks (corpus_id);

-- 6) `commits.status` NÃO é do F7 (Contrato Comum §4.3): a coluna é do F4
--    (migration 004_commits.sql), com valores canônicos 'present' | 'orphaned'.
--    O F7 só consome: o dossiê exclui `status = 'orphaned'`.
