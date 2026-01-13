-- law_schema.sql

CREATE EXTENSION IF NOT EXISTS vector;

-- =========================
-- 1) laws
-- =========================
CREATE TABLE IF NOT EXISTS laws (
  law_id              TEXT PRIMARY KEY,
  law_name            TEXT NOT NULL,
  law_type            TEXT,
  ministry            TEXT,
  promulgation_date   DATE,
  enforcement_date    DATE,
  revision_type       TEXT,
  domain              TEXT
);

-- =========================
-- 2) law_units
-- =========================
CREATE TABLE IF NOT EXISTS law_units (
  doc_id                 TEXT PRIMARY KEY,
  law_id                 TEXT NOT NULL REFERENCES laws(law_id) ON DELETE CASCADE,
  parent_id              TEXT,

  level                  TEXT NOT NULL,
  is_indexable           BOOLEAN NOT NULL DEFAULT TRUE,

  article_no             TEXT,
  article_title          TEXT,
  paragraph_no           TEXT,
  item_no                TEXT,
  subitem_no             TEXT,

  path                   TEXT,
  text                   TEXT NOT NULL,
  amendment_note         TEXT,

  ref_citations_internal JSONB NOT NULL DEFAULT '[]'::jsonb,
  ref_citations_external JSONB NOT NULL DEFAULT '[]'::jsonb,
  mentioned_laws         JSONB NOT NULL DEFAULT '[]'::jsonb
);

-- indexes
CREATE INDEX IF NOT EXISTS idx_law_units_law_id ON law_units(law_id);
CREATE INDEX IF NOT EXISTS idx_law_units_parent_id ON law_units(parent_id);
CREATE INDEX IF NOT EXISTS idx_law_units_level ON law_units(level);
CREATE INDEX IF NOT EXISTS idx_law_units_is_indexable ON law_units(is_indexable);
-- 선택: 조문 단위 조회가 잦으면
-- CREATE INDEX IF NOT EXISTS idx_law_units_law_article ON law_units(law_id, article_no);

-- =========================
-- 3) statute_chunk_vectors
-- =========================
CREATE TABLE IF NOT EXISTS statute_chunk_vectors (
  unit_id         TEXT NOT NULL,
  embedding_model TEXT NOT NULL,   -- 예: "text-embedding-3-large@2025-xx" 또는 "bge-m3-v1" 등

  law_id          TEXT NOT NULL,
  unit_level      TEXT,
  path            TEXT,

  node_refs       JSONB NOT NULL DEFAULT '[]'::jsonb,
  index_text      TEXT,

  embedding       VECTOR(1024) NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (unit_id, embedding_model)
);

-- 필터/조인용 인덱스
CREATE INDEX IF NOT EXISTS idx_statute_chunk_vectors_law_id
  ON statute_chunk_vectors(law_id);

CREATE INDEX IF NOT EXISTS idx_statute_chunk_vectors_unit_level
  ON statute_chunk_vectors(unit_level);

CREATE INDEX IF NOT EXISTS idx_statute_chunk_vectors_embedding_model
  ON statute_chunk_vectors(embedding_model);

-- 벡터 인덱스 (HNSW + cosine)
CREATE INDEX IF NOT EXISTS idx_statute_chunk_vectors_embedding_hnsw
  ON statute_chunk_vectors
  USING hnsw (embedding vector_cosine_ops);



select * from laws;
select * from law_units;


SELECT COUNT(*) FROM laws;
SELECT COUNT(*) FROM law_units;

-- 법령별 유닛 수
SELECT law_id, COUNT(*) AS n
FROM law_units
GROUP BY law_id
ORDER BY n DESC;