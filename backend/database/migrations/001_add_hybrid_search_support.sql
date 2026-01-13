-- Migration: Add Hybrid Search Support
-- 작성일: 2026-01-07
-- 목적: 하이브리드 검색을 위한 메타데이터 및 Full-Text Search 지원 추가

-- ============================================
-- 1. documents 테이블 확장
-- ============================================

-- keywords 컬럼 추가 (추출된 키워드 배열)
ALTER TABLE documents ADD COLUMN IF NOT EXISTS 
    keywords TEXT[];

-- search_vector 컬럼 추가 (PostgreSQL Full-Text Search)
ALTER TABLE documents ADD COLUMN IF NOT EXISTS
    search_vector tsvector;

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_documents_keywords 
    ON documents USING GIN(keywords);

CREATE INDEX IF NOT EXISTS idx_documents_search_vector 
    ON documents USING GIN(search_vector);

-- 코멘트 추가
COMMENT ON COLUMN documents.keywords IS '문서에서 추출된 핵심 키워드 배열 (검색 최적화용)';
COMMENT ON COLUMN documents.search_vector IS 'PostgreSQL Full-Text Search를 위한 tsvector (한국어 지원)';

-- ============================================
-- 2. chunks 테이블 확장
-- ============================================

-- importance_score 컬럼 추가 (청크 중요도 점수)
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS
    importance_score FLOAT DEFAULT 1.0;

-- importance_score에 대한 인덱스
CREATE INDEX IF NOT EXISTS idx_chunks_importance 
    ON chunks(importance_score) WHERE drop = FALSE;

-- 코멘트 추가
COMMENT ON COLUMN chunks.importance_score IS '청크 중요도 점수 (1.0 기본값, 재랭킹 시 사용)';

-- ============================================
-- 3. Materialized View 생성
-- ============================================

-- 기존 materialized view가 있다면 삭제
DROP MATERIALIZED VIEW IF EXISTS mv_searchable_chunks CASCADE;

-- 검색 최적화를 위한 materialized view 생성
CREATE MATERIALIZED VIEW mv_searchable_chunks AS
SELECT 
    c.chunk_id,
    c.doc_id,
    c.chunk_type,
    c.content,
    c.embedding,
    c.importance_score,
    d.doc_type,
    d.source_org,
    d.metadata,
    d.keywords,
    to_tsvector('simple', c.content) AS content_vector,  -- simple parser for Korean compatibility
    d.category_path
FROM chunks c
JOIN documents d ON c.doc_id = d.doc_id
WHERE c.drop = FALSE AND c.embedding IS NOT NULL;

-- Materialized View 인덱스
CREATE INDEX idx_mv_chunks_content 
    ON mv_searchable_chunks USING GIN(content_vector);

CREATE INDEX idx_mv_chunks_embedding 
    ON mv_searchable_chunks USING ivfflat(embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX idx_mv_chunks_doc_type 
    ON mv_searchable_chunks(doc_type);

CREATE INDEX idx_mv_chunks_chunk_type 
    ON mv_searchable_chunks(chunk_type);

CREATE INDEX idx_mv_chunks_importance 
    ON mv_searchable_chunks(importance_score);

COMMENT ON MATERIALIZED VIEW mv_searchable_chunks IS '검색 최적화를 위한 청크 통합 뷰 (활성 청크만 포함)';

-- ============================================
-- 4. 하이브리드 검색 함수
-- ============================================

-- 키워드 + 벡터 하이브리드 검색 함수
CREATE OR REPLACE FUNCTION hybrid_search_chunks(
    query_embedding vector(1024),
    query_keywords TEXT[],
    doc_type_filter VARCHAR(50) DEFAULT NULL,
    chunk_type_filter VARCHAR(50) DEFAULT NULL,
    source_org_filter VARCHAR(100) DEFAULT NULL,
    vector_weight FLOAT DEFAULT 0.7,
    keyword_weight FLOAT DEFAULT 0.3,
    top_k INTEGER DEFAULT 10,
    min_similarity FLOAT DEFAULT 0.0
)
RETURNS TABLE (
    chunk_id VARCHAR(255),
    doc_id VARCHAR(255),
    chunk_type VARCHAR(50),
    content TEXT,
    doc_title TEXT,
    doc_type VARCHAR(50),
    source_org VARCHAR(100),
    category_path TEXT[],
    vector_score FLOAT,
    keyword_score FLOAT,
    final_score FLOAT
) AS $$
BEGIN
    RETURN QUERY
    WITH vector_results AS (
        SELECT 
            c.chunk_id,
            c.doc_id,
            c.chunk_type,
            c.content,
            d.title AS doc_title,
            d.doc_type,
            d.source_org,
            d.category_path,
            (1 - (c.embedding <=> query_embedding)) AS vscore
        FROM chunks c
        JOIN documents d ON c.doc_id = d.doc_id
        WHERE 
            c.drop = FALSE
            AND c.embedding IS NOT NULL
            AND (doc_type_filter IS NULL OR d.doc_type = doc_type_filter)
            AND (chunk_type_filter IS NULL OR c.chunk_type = chunk_type_filter)
            AND (source_org_filter IS NULL OR d.source_org = source_org_filter)
            AND (1 - (c.embedding <=> query_embedding)) >= min_similarity
    ),
    keyword_results AS (
        SELECT 
            c.chunk_id,
            CASE 
                WHEN query_keywords IS NULL OR array_length(query_keywords, 1) IS NULL THEN 0.0
                ELSE (
                    SELECT COUNT(*)::FLOAT / array_length(query_keywords, 1)
                    FROM unnest(query_keywords) kw
                    WHERE c.content ILIKE '%' || kw || '%'
                )
            END AS kscore
        FROM chunks c
        JOIN documents d ON c.doc_id = d.doc_id
        WHERE 
            c.drop = FALSE
            AND (doc_type_filter IS NULL OR d.doc_type = doc_type_filter)
            AND (chunk_type_filter IS NULL OR c.chunk_type = chunk_type_filter)
            AND (source_org_filter IS NULL OR d.source_org = source_org_filter)
    )
    SELECT 
        vr.chunk_id,
        vr.doc_id,
        vr.chunk_type,
        vr.content,
        vr.doc_title,
        vr.doc_type,
        vr.source_org,
        vr.category_path,
        vr.vscore AS vector_score,
        COALESCE(kr.kscore, 0.0) AS keyword_score,
        (vr.vscore * vector_weight + COALESCE(kr.kscore, 0.0) * keyword_weight) AS final_score
    FROM vector_results vr
    LEFT JOIN keyword_results kr ON vr.chunk_id = kr.chunk_id
    ORDER BY final_score DESC
    LIMIT top_k;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION hybrid_search_chunks IS '하이브리드 검색 함수: 벡터 유사도 + 키워드 매칭 조합';

-- ============================================
-- 5. 메타데이터 기반 검색 보조 함수
-- ============================================

-- 품목명 검색 함수
CREATE OR REPLACE FUNCTION search_by_item_name(
    item_names TEXT[],
    top_k INTEGER DEFAULT 10
)
RETURNS TABLE (
    chunk_id VARCHAR(255),
    doc_id VARCHAR(255),
    content TEXT,
    match_score FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        c.chunk_id,
        c.doc_id,
        c.content,
        CASE 
            WHEN d.metadata->>'item_name' = ANY(item_names) THEN 1.0
            WHEN d.metadata->>'aliases' ?| item_names THEN 0.8
            ELSE 0.0
        END AS match_score
    FROM chunks c
    JOIN documents d ON c.doc_id = d.doc_id
    WHERE 
        c.drop = FALSE
        AND (
            d.metadata->>'item_name' = ANY(item_names)
            OR d.metadata->>'aliases' ?| item_names
        )
    ORDER BY match_score DESC
    LIMIT top_k;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION search_by_item_name IS '품목명 기반 정확 매칭 검색 (aliases 포함)';

-- 법령 조문 검색 함수
CREATE OR REPLACE FUNCTION search_by_law_article(
    law_name_pattern TEXT,
    article_no TEXT,
    top_k INTEGER DEFAULT 10
)
RETURNS TABLE (
    chunk_id VARCHAR(255),
    doc_id VARCHAR(255),
    content TEXT,
    law_name TEXT,
    article_no_found TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        c.chunk_id,
        c.doc_id,
        c.content,
        d.metadata->>'law_name' AS law_name,
        d.metadata->>'article_no' AS article_no_found
    FROM chunks c
    JOIN documents d ON c.doc_id = d.doc_id
    WHERE 
        c.drop = FALSE
        AND d.doc_type = 'law'
        AND (law_name_pattern IS NULL OR d.metadata->>'law_name' ILIKE '%' || law_name_pattern || '%')
        AND (article_no IS NULL OR d.metadata->>'article_no' = article_no)
    ORDER BY c.chunk_index
    LIMIT top_k;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION search_by_law_article IS '법령 조문 정확 검색 (법령명 + 조문번호)';

-- ============================================
-- 6. Materialized View 갱신 함수
-- ============================================

CREATE OR REPLACE FUNCTION refresh_searchable_chunks()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_searchable_chunks;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION refresh_searchable_chunks IS 'Materialized View 갱신 함수';

-- ============================================
-- 완료 메시지
-- ============================================
DO $$
BEGIN
    RAISE NOTICE '============================================';
    RAISE NOTICE 'Migration 001: Hybrid Search Support 완료';
    RAISE NOTICE '============================================';
    RAISE NOTICE '추가된 컬럼:';
    RAISE NOTICE '  - documents.keywords (TEXT[])';
    RAISE NOTICE '  - documents.search_vector (tsvector)';
    RAISE NOTICE '  - chunks.importance_score (FLOAT)';
    RAISE NOTICE '';
    RAISE NOTICE '추가된 Materialized View:';
    RAISE NOTICE '  - mv_searchable_chunks';
    RAISE NOTICE '';
    RAISE NOTICE '추가된 함수:';
    RAISE NOTICE '  - hybrid_search_chunks()';
    RAISE NOTICE '  - search_by_item_name()';
    RAISE NOTICE '  - search_by_law_article()';
    RAISE NOTICE '  - refresh_searchable_chunks()';
    RAISE NOTICE '============================================';
END $$;
