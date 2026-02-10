-- PostgreSQL + pgvector 설정 스크립트 (B_case 전용 - 레거시)
-- 소비자 분쟁 사례 벡터 DB 구축
--
-- ⚠️ 주의: 이 스크립트는 B_case 데이터만 처리하는 레거시 버전입니다.
-- ⚠️ 최신 통합 스키마는 DB/01_00_unified_schema.sql을 사용하세요.
-- ⚠️ 통합 스키마는 A_law_ED_guide + B_case를 단일 테이블(vector_chunks)로 관리합니다.
--
-- 현재 데이터 규모 (Semantic Chunking 적용):
-- - 크롤링 데이터: 41,438개 청크
-- - PDF 데이터: 4,876개 청크
-- - 총 B_case: 46,314개 청크

-- ======================================
-- 1. pgvector 확장 설치
-- ======================================

CREATE EXTENSION IF NOT EXISTS vector;

-- ======================================
-- 2. 데이터베이스 생성 (필요시)
-- ======================================

-- 새 데이터베이스 생성이 필요한 경우:
-- CREATE DATABASE consumer_cases;
-- \c consumer_cases;

-- ======================================
-- 3. 메인 테이블 생성
-- ======================================

DROP TABLE IF EXISTS consumer_case_chunks CASCADE;

CREATE TABLE consumer_case_chunks (
    -- 기본 키
    id SERIAL PRIMARY KEY,

    -- 청크 식별자
    chunk_id VARCHAR(255) UNIQUE NOT NULL,

    -- 데이터 분류
    data_source VARCHAR(50) NOT NULL CHECK (data_source IN ('crawling', 'pdf')),
    category VARCHAR(50) NOT NULL CHECK (category IN ('상담', '해결', '조정')),

    -- 원본 정보
    original_number VARCHAR(100) NOT NULL,
    field_name VARCHAR(100) NOT NULL,
    chunk_index INTEGER NOT NULL CHECK (chunk_index > 0),
    total_chunks INTEGER NOT NULL CHECK (total_chunks > 0),

    -- 텍스트 내용
    content TEXT NOT NULL,

    -- 임베딩 벡터 (1536차원)
    embedding vector(1536) NOT NULL,

    -- 메타데이터 (JSON)
    metadata JSONB,

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT NOW()
);

-- ======================================
-- 4. 일반 인덱스 생성
-- ======================================

-- 청크 ID 인덱스 (중복 체크용)
CREATE INDEX idx_chunk_id ON consumer_case_chunks(chunk_id);

-- 데이터 소스 인덱스 (필터링용)
CREATE INDEX idx_data_source ON consumer_case_chunks(data_source);

-- 카테고리 인덱스 (필터링용)
CREATE INDEX idx_category ON consumer_case_chunks(category);

-- 원본 번호 인덱스 (원본 추적용)
CREATE INDEX idx_original_number ON consumer_case_chunks(original_number);

-- 메타데이터 GIN 인덱스 (JSON 검색용)
CREATE INDEX idx_metadata ON consumer_case_chunks USING GIN(metadata);

-- 타임스탬프 인덱스
CREATE INDEX idx_created_at ON consumer_case_chunks(created_at);

-- ======================================
-- 5. 벡터 인덱스 생성 (HNSW)
-- ======================================

-- HNSW: Hierarchical Navigable Small World
-- 가장 빠른 검색 속도, 높은 정확도
-- m: 그래프 연결 수 (16 = 기본값, 품질 양호)
-- ef_construction: 구축 시 탐색 범위 (64 = 기본값)

CREATE INDEX idx_embedding_hnsw ON consumer_case_chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- 대안: IVFFlat 인덱스 (더 빠른 구축, 약간 낮은 정확도)
-- CREATE INDEX idx_embedding_ivfflat ON consumer_case_chunks
-- USING ivfflat (embedding vector_cosine_ops)
-- WITH (lists = 100);

-- ======================================
-- 6. 유틸리티 함수
-- ======================================

-- 코사인 유사도 검색 함수
CREATE OR REPLACE FUNCTION search_similar_chunks(
    query_embedding vector(1536),
    filter_category VARCHAR(50) DEFAULT NULL,
    filter_data_source VARCHAR(50) DEFAULT NULL,
    result_limit INTEGER DEFAULT 5
)
RETURNS TABLE (
    chunk_id VARCHAR(255),
    category VARCHAR(50),
    data_source VARCHAR(50),
    content TEXT,
    similarity FLOAT,
    metadata JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.chunk_id,
        c.category,
        c.data_source,
        c.content,
        1 - (c.embedding <=> query_embedding) AS similarity,
        c.metadata
    FROM consumer_case_chunks c
    WHERE
        (filter_category IS NULL OR c.category = filter_category)
        AND (filter_data_source IS NULL OR c.data_source = filter_data_source)
    ORDER BY c.embedding <=> query_embedding
    LIMIT result_limit;
END;
$$ LANGUAGE plpgsql;

-- ======================================
-- 7. 통계 뷰
-- ======================================

CREATE OR REPLACE VIEW chunk_statistics AS
SELECT
    data_source,
    category,
    COUNT(*) as total_chunks,
    AVG(LENGTH(content)) as avg_content_length,
    MIN(created_at) as first_inserted,
    MAX(created_at) as last_inserted
FROM consumer_case_chunks
GROUP BY data_source, category
ORDER BY data_source, category;

-- ======================================
-- 8. 데이터 검증 함수
-- ======================================

CREATE OR REPLACE FUNCTION validate_embedding_dimension()
RETURNS TABLE (
    chunk_id VARCHAR(255),
    actual_dimension INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.chunk_id,
        vector_dims(c.embedding) as actual_dimension
    FROM consumer_case_chunks c
    WHERE vector_dims(c.embedding) != 1536;
END;
$$ LANGUAGE plpgsql;

-- ======================================
-- 9. 권한 설정 (필요시)
-- ======================================

-- 특정 사용자에게 권한 부여
-- GRANT SELECT, INSERT, UPDATE ON consumer_case_chunks TO your_user;
-- GRANT USAGE, SELECT ON SEQUENCE consumer_case_chunks_id_seq TO your_user;

-- ======================================
-- 10. 테스트 쿼리
-- ======================================

-- 테이블 확인
-- SELECT COUNT(*) FROM consumer_case_chunks;

-- 통계 확인
-- SELECT * FROM chunk_statistics;

-- 카테고리별 분포 확인
-- SELECT category, data_source, COUNT(*)
-- FROM consumer_case_chunks
-- GROUP BY category, data_source
-- ORDER BY category, data_source;

-- 임베딩 차원 검증
-- SELECT * FROM validate_embedding_dimension();

-- 유사도 검색 테스트 (임베딩 벡터 예시 필요)
-- SELECT * FROM search_similar_chunks(
--     '[0.1, 0.2, ...]'::vector(1536),
--     '조정',
--     NULL,
--     5
-- );

-- ======================================
-- 설정 완료
-- ======================================

-- 테이블 정보 출력
\d consumer_case_chunks

-- 인덱스 목록 출력
\di

COMMENT ON TABLE consumer_case_chunks IS '소비자 분쟁 사례 청크 및 임베딩 데이터';
COMMENT ON COLUMN consumer_case_chunks.embedding IS 'OpenAI text-embedding-3-large (1536차원, Matryoshka)';
COMMENT ON INDEX idx_embedding_hnsw IS 'HNSW 벡터 유사도 인덱스 (코사인 거리)';
