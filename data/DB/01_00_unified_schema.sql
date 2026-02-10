-- =====================================================
-- 통합 벡터 데이터베이스 스키마
-- A_law_ED_guide + B_case 데이터셋 통합
-- PostgreSQL 17.7 with pgvector 0.8.1
--
-- 최신 기능 (2026-01-28):
-- - 제목 가중치 시스템: 제목(A=0.6) > 본문(B=0.4)
-- - 자동 정규화: 조문번호 "제" 제거
-- - 문서 타입 분류: 법률/시행령/행정규칙/별표
-- =====================================================

-- =====================================================
-- 1. 확장 설치
-- =====================================================

-- pgvector 확장 설치 (벡터 연산 지원)
CREATE EXTENSION IF NOT EXISTS vector;

-- =====================================================
-- 2. 데이터베이스 생성 (필요 시)
-- =====================================================

-- 새 데이터베이스가 필요한 경우 아래 주석 해제
-- CREATE DATABASE consumer_rag;
-- \c consumer_rag;

-- =====================================================
-- 3. 메인 통합 테이블
-- =====================================================

DROP TABLE IF EXISTS vector_chunks CASCADE;

CREATE TABLE vector_chunks (
    -- 기본 키
    id SERIAL PRIMARY KEY,

    -- 청크 고유 식별자 (A, B 데이터셋 모두)
    chunk_id VARCHAR(500) UNIQUE NOT NULL,

    -- 데이터셋 구분
    dataset_type VARCHAR(20) NOT NULL CHECK (dataset_type IN ('law_guide', 'case')),

    -- 텍스트 내용
    -- A_law_ED_guide: 'text' 필드
    -- B_case: 'content' 필드
    text TEXT NOT NULL,

    -- 임베딩 벡터 (1536차원, Matryoshka)
    embedding vector(1536) NOT NULL,

    -- 검색 최적화 필드 (자주 필터링되는 항목)
    -- A_law_ED_guide: 법령명 (예: '소비자기본법')
    -- B_case: NULL
    law_name VARCHAR(500),

    -- A_law_ED_guide: 조문번호 (원본, 표시용)
    -- 예: '제13조', '제16조제2항'
    -- B_case: NULL
    article_number VARCHAR(50),

    -- A_law_ED_guide: 조문번호 (정규화, 검색용)
    -- "제"를 제거한 버전: '13조', '16조2항'
    -- 사용자가 "13조" 또는 "제13조"로 검색해도 매칭되도록
    -- B_case: NULL
    article_number_normalized VARCHAR(50),

    -- A_law_ED_guide: 청크 타입 (조_전체, 항_조항, 호_조항, 부모_청크, 자식_청크)
    -- B_case: 'case'
    chunk_type VARCHAR(50),

    -- B_case: 카테고리 (상담, 해결, 조정)
    -- A_law_ED_guide: NULL
    category VARCHAR(50),

    -- A_law_ED_guide: 문서 유형 (법률, 시행령, 행정규칙, 별표)
    -- B_case: NULL
    document_type VARCHAR(20),

    -- 출처 정보 (Source Information) - 신뢰도 및 인용 표기용
    -- B_case 크롤링 데이터: 원본 URL
    -- A_law_ED_guide, B_case PDF: NULL
    source_url VARCHAR(1000),

    -- B_case PDF 데이터: 파일명 (경로 제외)
    -- 예: "2010년 소비자분쟁 해결사례집.pdf"
    -- A_law_ED_guide, B_case 크롤링: NULL
    source_file VARCHAR(500),

    -- B_case PDF 데이터: 인쇄 페이지 번호
    -- A_law_ED_guide, B_case 크롤링: NULL
    printed_page INTEGER,

    -- 연도 정보 (통계 및 필터링용)
    -- B_case PDF: 파일명에서 추출한 연도
    -- A_law_ED_guide: 시행일 연도
    -- B_case 크롤링: NULL (또는 추출 가능 시 설정)
    source_year INTEGER,

    -- 데이터셋별 상세 메타데이터 (JSONB)
    metadata JSONB,

    -- 전문 검색용 tsvector (Full-Text Search for BM25)
    -- 하이브리드 검색을 위한 키워드 기반 검색 지원
    -- 가중치: 제목(A=0.6) > 본문(B=0.4)
    text_tsv tsvector,

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- =====================================================
-- 4. 인덱스 생성
-- =====================================================

-- 4.1 기본 인덱스

-- 청크 ID 인덱스 (UNIQUE 제약으로 자동 생성되지만 명시)
CREATE UNIQUE INDEX idx_chunk_id ON vector_chunks(chunk_id);

-- 데이터셋 타입 인덱스
CREATE INDEX idx_dataset_type ON vector_chunks(dataset_type);

-- 법령명 인덱스 (A_law_ED_guide 필터링)
CREATE INDEX idx_law_name ON vector_chunks(law_name) WHERE law_name IS NOT NULL;

-- 조문번호 인덱스 (A_law_ED_guide 필터링)
-- 원본 조문번호 (표시용)
CREATE INDEX idx_article_number ON vector_chunks(article_number) WHERE article_number IS NOT NULL;

-- 정규화된 조문번호 (검색용) - 주 검색 인덱스
CREATE INDEX idx_article_number_normalized ON vector_chunks(article_number_normalized) WHERE article_number_normalized IS NOT NULL;

-- 청크 타입 인덱스
CREATE INDEX idx_chunk_type ON vector_chunks(chunk_type);

-- 카테고리 인덱스 (B_case 필터링)
CREATE INDEX idx_category ON vector_chunks(category) WHERE category IS NOT NULL;

-- 문서 유형 인덱스 (A_law_ED_guide 필터링)
CREATE INDEX idx_document_type ON vector_chunks(document_type) WHERE document_type IS NOT NULL;

-- 타임스탬프 인덱스
CREATE INDEX idx_created_at ON vector_chunks(created_at);

-- 출처 정보 인덱스 (Source Information Indexes)
-- B_case 크롤링: URL 기반 검색 및 그룹핑
CREATE INDEX idx_source_url ON vector_chunks(source_url) WHERE source_url IS NOT NULL;

-- B_case PDF: 파일명 기반 검색 및 그룹핑
CREATE INDEX idx_source_file ON vector_chunks(source_file) WHERE source_file IS NOT NULL;

-- 연도별 필터링 및 통계 (모든 데이터셋)
CREATE INDEX idx_source_year ON vector_chunks(source_year) WHERE source_year IS NOT NULL;

-- PDF 파일 + 페이지 번호 복합 인덱스 (정확한 출처 추적)
CREATE INDEX idx_source_file_page ON vector_chunks(source_file, printed_page)
WHERE source_file IS NOT NULL AND printed_page IS NOT NULL;

-- 4.2 복합 인덱스

-- 데이터셋 + 카테고리 (B_case 검색)
CREATE INDEX idx_dataset_category ON vector_chunks(dataset_type, category)
WHERE category IS NOT NULL;

-- 법령명 + 청크 타입 (A_law_ED_guide 검색)
CREATE INDEX idx_law_chunk_type ON vector_chunks(law_name, chunk_type)
WHERE law_name IS NOT NULL;

-- 법령명 + 조문번호 (A_law_ED_guide 조문 검색) - 가장 많이 사용되는 조합
CREATE INDEX idx_law_article ON vector_chunks(law_name, article_number)
WHERE law_name IS NOT NULL AND article_number IS NOT NULL;

-- 법령명 + 정규화된 조문번호 (A_law_ED_guide 조문 검색) - 주 검색 인덱스
CREATE INDEX idx_law_article_normalized ON vector_chunks(law_name, article_number_normalized)
WHERE law_name IS NOT NULL AND article_number_normalized IS NOT NULL;

-- 4.3 JSONB 인덱스 (메타데이터 검색)

-- GIN 인덱스: JSONB 필드 전체 검색
CREATE INDEX idx_metadata_gin ON vector_chunks USING GIN(metadata);

-- 특정 JSONB 키에 대한 B-tree 인덱스 (A_law_ED_guide 키워드 검색)
CREATE INDEX idx_metadata_keywords ON vector_chunks
USING GIN((metadata->'keywords')) WHERE dataset_type = 'law_guide';

-- 4.4 전문 검색 인덱스 (Full-Text Search) - 하이브리드 검색용

-- GIN 인덱스: tsvector 기반 키워드 검색 (BM25 유사)
CREATE INDEX idx_text_tsv ON vector_chunks USING GIN(text_tsv);

-- 4.5 벡터 인덱스 (HNSW) - 가장 중요!

-- HNSW 인덱스: 코사인 유사도 기반 벡터 검색
-- 참고: 대용량 데이터 삽입 후 생성하는 것이 효율적
-- 초기에는 주석 처리하고, 모든 데이터 삽입 후 실행 권장
CREATE INDEX idx_embedding_hnsw ON vector_chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- 대안: IVFFlat 인덱스 (10만 개 이상 데이터에 적합)
-- CREATE INDEX idx_embedding_ivfflat ON vector_chunks
-- USING ivfflat (embedding vector_cosine_ops)
-- WITH (lists = 100);

-- =====================================================
-- 5. 조문번호 정규화 (Article Number Normalization)
-- =====================================================

-- 5.1 조문번호 정규화 함수
-- "제"를 제거하여 검색 유연성 확보
-- 예: "제13조" → "13조", "제16조제2항" → "16조2항"

CREATE OR REPLACE FUNCTION normalize_article_number(article TEXT)
RETURNS TEXT AS $$
BEGIN
    IF article IS NULL THEN
        RETURN NULL;
    END IF;

    -- "제"를 모두 제거
    RETURN REPLACE(article, '제', '');
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION normalize_article_number IS
'조문번호 정규화 함수: "제" 제거
예시: normalize_article_number(''제13조'') → ''13조''
사용자가 "13조" 또는 "제13조"로 검색해도 매칭되도록 지원';

-- 5.2 자동 정규화 트리거
-- INSERT/UPDATE 시 article_number_normalized 자동 생성

CREATE OR REPLACE FUNCTION auto_normalize_article_trigger()
RETURNS TRIGGER AS $$
BEGIN
    -- article_number가 있으면 자동으로 정규화
    IF NEW.article_number IS NOT NULL THEN
        NEW.article_number_normalized := normalize_article_number(NEW.article_number);
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_auto_normalize_article ON vector_chunks;

CREATE TRIGGER trigger_auto_normalize_article
BEFORE INSERT OR UPDATE OF article_number
ON vector_chunks
FOR EACH ROW
EXECUTE FUNCTION auto_normalize_article_trigger();

COMMENT ON TRIGGER trigger_auto_normalize_article ON vector_chunks IS
'조문번호 자동 정규화 트리거
INSERT/UPDATE 시 article_number → article_number_normalized 자동 변환';

-- =====================================================
-- 6. 유틸리티 함수
-- =====================================================

-- 5.1 기본 벡터 유사도 검색 함수

CREATE OR REPLACE FUNCTION search_similar_chunks(
    query_embedding vector(1536),
    filter_dataset VARCHAR(20) DEFAULT NULL,
    filter_category VARCHAR(50) DEFAULT NULL,
    filter_law_name VARCHAR(500) DEFAULT NULL,
    filter_year INTEGER DEFAULT NULL,
    result_limit INTEGER DEFAULT 10
)
RETURNS TABLE (
    chunk_id VARCHAR(500),
    dataset_type VARCHAR(20),
    text TEXT,
    similarity FLOAT,
    law_name VARCHAR(500),
    chunk_type VARCHAR(50),
    category VARCHAR(50),
    source_url VARCHAR(1000),
    source_file VARCHAR(500),
    printed_page INTEGER,
    source_year INTEGER,
    metadata JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        vc.chunk_id,
        vc.dataset_type,
        vc.text,
        1 - (vc.embedding <=> query_embedding) AS similarity,
        vc.law_name,
        vc.chunk_type,
        vc.category,
        vc.source_url,
        vc.source_file,
        vc.printed_page,
        vc.source_year,
        vc.metadata
    FROM vector_chunks vc
    WHERE
        (filter_dataset IS NULL OR vc.dataset_type = filter_dataset)
        AND (filter_category IS NULL OR vc.category = filter_category)
        AND (filter_law_name IS NULL OR vc.law_name = filter_law_name)
        AND (filter_year IS NULL OR vc.source_year = filter_year)
    ORDER BY vc.embedding <=> query_embedding
    LIMIT result_limit;
END;
$$ LANGUAGE plpgsql;

-- 5.2 하이브리드 검색 함수 (법령 + 사례 동시 검색)

CREATE OR REPLACE FUNCTION search_hybrid(
    query_embedding vector(1536),
    law_limit INTEGER DEFAULT 5,
    case_limit INTEGER DEFAULT 5,
    filter_category VARCHAR(50) DEFAULT NULL,
    filter_year INTEGER DEFAULT NULL
)
RETURNS TABLE (
    source VARCHAR(20),
    chunk_id VARCHAR(500),
    text TEXT,
    similarity FLOAT,
    law_name VARCHAR(500),
    category VARCHAR(50),
    source_url VARCHAR(1000),
    source_file VARCHAR(500),
    printed_page INTEGER,
    source_year INTEGER,
    metadata JSONB
) AS $$
BEGIN
    RETURN QUERY
    (
        -- 법령 검색
        SELECT
            'law_guide'::VARCHAR(20) as source,
            vc.chunk_id,
            vc.text,
            1 - (vc.embedding <=> query_embedding) AS similarity,
            vc.law_name,
            vc.category,
            vc.source_url,
            vc.source_file,
            vc.printed_page,
            vc.source_year,
            vc.metadata
        FROM vector_chunks vc
        WHERE vc.dataset_type = 'law_guide'
          AND (filter_year IS NULL OR vc.source_year = filter_year)
        ORDER BY vc.embedding <=> query_embedding
        LIMIT law_limit
    )
    UNION ALL
    (
        -- 사례 검색
        SELECT
            'case'::VARCHAR(20) as source,
            vc.chunk_id,
            vc.text,
            1 - (vc.embedding <=> query_embedding) AS similarity,
            vc.law_name,
            vc.category,
            vc.source_url,
            vc.source_file,
            vc.printed_page,
            vc.source_year,
            vc.metadata
        FROM vector_chunks vc
        WHERE vc.dataset_type = 'case'
          AND (filter_category IS NULL OR vc.category = filter_category)
          AND (filter_year IS NULL OR vc.source_year = filter_year)
        ORDER BY vc.embedding <=> query_embedding
        LIMIT case_limit
    )
    ORDER BY similarity DESC;
END;
$$ LANGUAGE plpgsql;

-- 5.3 메타데이터 키워드 검색 + 벡터 유사도

CREATE OR REPLACE FUNCTION search_with_keywords(
    query_embedding vector(1536),
    keyword TEXT,
    result_limit INTEGER DEFAULT 10
)
RETURNS TABLE (
    chunk_id VARCHAR(500),
    dataset_type VARCHAR(20),
    text TEXT,
    similarity FLOAT,
    metadata JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        vc.chunk_id,
        vc.dataset_type,
        vc.text,
        1 - (vc.embedding <=> query_embedding) AS similarity,
        vc.metadata
    FROM vector_chunks vc
    WHERE
        vc.dataset_type = 'law_guide'
        AND vc.metadata->'keywords' ? keyword
    ORDER BY vc.embedding <=> query_embedding
    LIMIT result_limit;
END;
$$ LANGUAGE plpgsql;

-- 5.4 청크 개수 통계 함수

CREATE OR REPLACE FUNCTION get_chunk_statistics()
RETURNS TABLE (
    dataset_type VARCHAR(20),
    category VARCHAR(50),
    chunk_type VARCHAR(50),
    total_chunks BIGINT,
    avg_text_length FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        vc.dataset_type,
        vc.category,
        vc.chunk_type,
        COUNT(*) as total_chunks,
        AVG(LENGTH(vc.text)) as avg_text_length
    FROM vector_chunks vc
    GROUP BY vc.dataset_type, vc.category, vc.chunk_type
    ORDER BY vc.dataset_type, vc.category, vc.chunk_type;
END;
$$ LANGUAGE plpgsql;

-- 5.5 하이브리드 검색 함수 (BM25 + 벡터 + RRF)

-- BM25 키워드 검색 함수
CREATE OR REPLACE FUNCTION search_bm25(
    query_text TEXT,
    filter_dataset VARCHAR(20) DEFAULT NULL,
    filter_category VARCHAR(50) DEFAULT NULL,
    filter_document_type VARCHAR(20) DEFAULT NULL,
    result_limit INTEGER DEFAULT 100
)
RETURNS TABLE (
    chunk_id VARCHAR(500),
    dataset_type VARCHAR(20),
    text TEXT,
    bm25_score FLOAT,
    bm25_rank BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        vc.chunk_id,
        vc.dataset_type,
        vc.text,
        ts_rank_cd('{0.1, 0.2, 0.4, 0.6}', vc.text_tsv, plainto_tsquery('simple', query_text))::FLOAT as bm25_score,
        ROW_NUMBER() OVER (ORDER BY ts_rank_cd('{0.1, 0.2, 0.4, 0.6}', vc.text_tsv, plainto_tsquery('simple', query_text)) DESC) as bm25_rank
    FROM vector_chunks vc
    WHERE
        vc.text_tsv @@ plainto_tsquery('simple', query_text)
        AND (filter_dataset IS NULL OR vc.dataset_type = filter_dataset)
        AND (filter_category IS NULL OR vc.category = filter_category)
        AND (filter_document_type IS NULL OR vc.document_type = filter_document_type)
    ORDER BY bm25_score DESC
    LIMIT result_limit;
END;
$$ LANGUAGE plpgsql;

-- 하이브리드 검색 함수 (RRF 통합)
CREATE OR REPLACE FUNCTION search_hybrid_rrf(
    query_text TEXT,
    query_embedding vector(1536),
    filter_dataset VARCHAR(20) DEFAULT NULL,
    filter_category VARCHAR(50) DEFAULT NULL,
    filter_document_type VARCHAR(20) DEFAULT NULL,
    filter_year INTEGER DEFAULT NULL,
    result_limit INTEGER DEFAULT 10,
    rrf_k INTEGER DEFAULT 60
)
RETURNS TABLE (
    chunk_id VARCHAR(500),
    dataset_type VARCHAR(20),
    text TEXT,
    rrf_score FLOAT,
    bm25_score FLOAT,
    vector_similarity FLOAT,
    source_url VARCHAR(1000),
    source_file VARCHAR(500),
    printed_page INTEGER,
    source_year INTEGER,
    metadata JSONB
) AS $$
BEGIN
    RETURN QUERY
    WITH bm25_results AS (
        SELECT
            vc.chunk_id,
            ts_rank_cd('{0.1, 0.2, 0.4, 0.6}', vc.text_tsv, plainto_tsquery('simple', query_text))::FLOAT as score,
            ROW_NUMBER() OVER (ORDER BY ts_rank_cd('{0.1, 0.2, 0.4, 0.6}', vc.text_tsv, plainto_tsquery('simple', query_text)) DESC) as rank
        FROM vector_chunks vc
        WHERE
            vc.text_tsv @@ plainto_tsquery('simple', query_text)
            AND (filter_dataset IS NULL OR vc.dataset_type = filter_dataset)
            AND (filter_category IS NULL OR vc.category = filter_category)
            AND (filter_document_type IS NULL OR vc.document_type = filter_document_type)
            AND (filter_year IS NULL OR vc.source_year = filter_year)
        ORDER BY score DESC
        LIMIT 100
    ),
    vector_results AS (
        SELECT
            vc.chunk_id,
            (1 - (vc.embedding <=> query_embedding))::FLOAT as similarity,
            ROW_NUMBER() OVER (ORDER BY vc.embedding <=> query_embedding) as rank
        FROM vector_chunks vc
        WHERE
            (filter_dataset IS NULL OR vc.dataset_type = filter_dataset)
            AND (filter_category IS NULL OR vc.category = filter_category)
            AND (filter_document_type IS NULL OR vc.document_type = filter_document_type)
            AND (filter_year IS NULL OR vc.source_year = filter_year)
        ORDER BY vc.embedding <=> query_embedding
        LIMIT 100
    ),
    rrf_combined AS (
        SELECT
            COALESCE(b.chunk_id, v.chunk_id) as chunk_id,
            -- RRF: 1 / (k + rank)
            (COALESCE(1.0 / (rrf_k + b.rank), 0) +
             COALESCE(1.0 / (rrf_k + v.rank), 0))::FLOAT as rrf_score,
            COALESCE(b.score, 0)::FLOAT as bm25_score,
            COALESCE(v.similarity, 0)::FLOAT as vector_similarity
        FROM bm25_results b
        FULL OUTER JOIN vector_results v ON b.chunk_id = v.chunk_id
    )
    SELECT
        vc.chunk_id,
        vc.dataset_type,
        vc.text,
        rc.rrf_score,
        rc.bm25_score,
        rc.vector_similarity,
        vc.source_url,
        vc.source_file,
        vc.printed_page,
        vc.source_year,
        vc.metadata
    FROM rrf_combined rc
    JOIN vector_chunks vc ON rc.chunk_id = vc.chunk_id
    ORDER BY rc.rrf_score DESC
    LIMIT result_limit;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- 6. 통계 뷰
-- =====================================================

-- 6.1 데이터셋별 통계 뷰

CREATE OR REPLACE VIEW dataset_statistics AS
SELECT
    dataset_type,
    COUNT(*) as total_chunks,
    COUNT(DISTINCT law_name) as unique_laws,
    COUNT(DISTINCT category) as unique_categories,
    AVG(LENGTH(text)) as avg_text_length,
    MIN(LENGTH(text)) as min_text_length,
    MAX(LENGTH(text)) as max_text_length,
    MIN(created_at) as first_inserted,
    MAX(created_at) as last_inserted
FROM vector_chunks
GROUP BY dataset_type;

-- 6.2 법령별 통계 뷰 (A_law_ED_guide)

CREATE OR REPLACE VIEW law_statistics AS
SELECT
    law_name,
    chunk_type,
    COUNT(*) as total_chunks,
    AVG(LENGTH(text)) as avg_text_length
FROM vector_chunks
WHERE dataset_type = 'law_guide' AND law_name IS NOT NULL
GROUP BY law_name, chunk_type
ORDER BY law_name, chunk_type;

-- 6.3 카테고리별 통계 뷰 (B_case)

CREATE OR REPLACE VIEW case_statistics AS
SELECT
    category,
    COUNT(*) as total_chunks,
    AVG(LENGTH(text)) as avg_text_length,
    MIN(created_at) as first_inserted,
    MAX(created_at) as last_inserted
FROM vector_chunks
WHERE dataset_type = 'case' AND category IS NOT NULL
GROUP BY category
ORDER BY category;

-- 6.4 출처별 통계 뷰 (Source Statistics)

-- PDF 파일별 통계
CREATE OR REPLACE VIEW pdf_source_statistics AS
SELECT
    source_file,
    source_year,
    category,
    COUNT(*) as total_chunks,
    MIN(printed_page) as first_page,
    MAX(printed_page) as last_page,
    AVG(LENGTH(text)) as avg_text_length
FROM vector_chunks
WHERE source_file IS NOT NULL
GROUP BY source_file, source_year, category
ORDER BY source_year DESC, source_file, category;

-- 크롤링 URL 도메인별 통계
CREATE OR REPLACE VIEW url_source_statistics AS
SELECT
    SUBSTRING(source_url FROM 'https?://([^/]+)') as domain,
    category,
    COUNT(*) as total_chunks,
    AVG(LENGTH(text)) as avg_text_length
FROM vector_chunks
WHERE source_url IS NOT NULL
GROUP BY domain, category
ORDER BY domain, category;

-- 연도별 통계
CREATE OR REPLACE VIEW year_statistics AS
SELECT
    source_year,
    dataset_type,
    category,
    COUNT(*) as total_chunks,
    AVG(LENGTH(text)) as avg_text_length
FROM vector_chunks
WHERE source_year IS NOT NULL
GROUP BY source_year, dataset_type, category
ORDER BY source_year DESC, dataset_type, category;

-- =====================================================
-- 7. 검색 품질 모니터링 테이블
-- =====================================================

-- 하이브리드 검색 품질 로그
CREATE TABLE IF NOT EXISTS search_quality_logs (
    id SERIAL PRIMARY KEY,

    -- 쿼리 정보
    query_text TEXT NOT NULL,
    query_embedding vector(1536),

    -- 검색 결과
    bm25_top_chunk_id VARCHAR(500),
    bm25_top_score FLOAT,
    vector_top_chunk_id VARCHAR(500),
    vector_top_similarity FLOAT,
    rrf_top_chunk_id VARCHAR(500),
    rrf_top_score FLOAT,

    -- 사용자 피드백
    user_clicked_chunk_id VARCHAR(500),
    user_rating INTEGER CHECK (user_rating BETWEEN 1 AND 5),

    -- 검색 성능
    search_time_ms INTEGER,
    total_results INTEGER,

    -- 필터 정보
    filter_dataset VARCHAR(20),
    filter_category VARCHAR(50),
    filter_year INTEGER,

    -- 타임스탬프
    created_at TIMESTAMP DEFAULT NOW()
);

-- 검색 로그 인덱스
CREATE INDEX idx_search_logs_created_at ON search_quality_logs(created_at);
CREATE INDEX idx_search_logs_query_text ON search_quality_logs USING GIN(to_tsvector('simple', query_text));

-- 검색 품질 분석 뷰
CREATE OR REPLACE VIEW search_quality_analysis AS
SELECT
    DATE(created_at) as search_date,
    COUNT(*) as total_searches,
    AVG(search_time_ms) as avg_search_time_ms,
    AVG(user_rating) as avg_user_rating,
    -- BM25이 RRF 1위와 일치한 비율
    SUM(CASE WHEN bm25_top_chunk_id = rrf_top_chunk_id THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as bm25_accuracy,
    -- 벡터가 RRF 1위와 일치한 비율
    SUM(CASE WHEN vector_top_chunk_id = rrf_top_chunk_id THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as vector_accuracy,
    -- 사용자가 1위 결과를 클릭한 비율 (CTR)
    SUM(CASE WHEN user_clicked_chunk_id = rrf_top_chunk_id THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(user_clicked_chunk_id), 0) as click_through_rate
FROM search_quality_logs
GROUP BY DATE(created_at)
ORDER BY search_date DESC;

-- =====================================================
-- 8. 데이터 검증 함수
-- =====================================================

-- 8.1 임베딩 차원 검증

CREATE OR REPLACE FUNCTION validate_embedding_dimensions()
RETURNS TABLE (
    chunk_id VARCHAR(500),
    actual_dimension INTEGER,
    expected_dimension INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        vc.chunk_id,
        vector_dims(vc.embedding) as actual_dimension,
        1536 as expected_dimension
    FROM vector_chunks vc
    WHERE vector_dims(vc.embedding) != 1536;
END;
$$ LANGUAGE plpgsql;

-- 8.2 중복 chunk_id 검증

CREATE OR REPLACE FUNCTION validate_duplicate_chunks()
RETURNS TABLE (
    chunk_id VARCHAR(500),
    duplicate_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        vc.chunk_id,
        COUNT(*) as duplicate_count
    FROM vector_chunks vc
    GROUP BY vc.chunk_id
    HAVING COUNT(*) > 1;
END;
$$ LANGUAGE plpgsql;

-- 8.3 NULL 값 검증

CREATE OR REPLACE FUNCTION validate_null_values()
RETURNS TABLE (
    validation_check VARCHAR(100),
    null_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 'chunk_id_null'::VARCHAR(100), COUNT(*) FROM vector_chunks WHERE chunk_id IS NULL
    UNION ALL
    SELECT 'text_null'::VARCHAR(100), COUNT(*) FROM vector_chunks WHERE text IS NULL
    UNION ALL
    SELECT 'embedding_null'::VARCHAR(100), COUNT(*) FROM vector_chunks WHERE embedding IS NULL
    UNION ALL
    SELECT 'dataset_type_null'::VARCHAR(100), COUNT(*) FROM vector_chunks WHERE dataset_type IS NULL;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- 9. 트리거 (자동 업데이트)
-- =====================================================

-- updated_at 자동 갱신 트리거 함수
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- updated_at 트리거 생성
CREATE TRIGGER trigger_update_updated_at
BEFORE UPDATE ON vector_chunks
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- tsvector 자동 업데이트 함수 (제목 가중치 적용)
-- 제목: A 가중치 (1.0), 본문: B 가중치 (0.4)
-- ts_rank 검색 시 {0.6, 0.4, 0.2, 0.1} 가중치 배열 사용하면 0.6:0.4 비율 달성
CREATE OR REPLACE FUNCTION update_text_tsv_with_weights()
RETURNS TRIGGER AS $$
DECLARE
    title_text TEXT;
    body_text TEXT;
BEGIN
    -- dataset_type에 따라 다른 처리
    IF NEW.dataset_type = 'law_guide' THEN
        -- law_guide: text의 첫 줄에서 제목 추출
        -- 예: "제1조(법원)\n내용..." -> 제목: "제1조(법원)"
        title_text := split_part(NEW.text, E'\n', 1);
        body_text := substring(NEW.text from position(E'\n' in NEW.text) + 1);

    ELSIF NEW.dataset_type = 'case' THEN
        -- case: metadata->>'title' 사용
        title_text := COALESCE(NEW.metadata->>'title', '');
        body_text := NEW.text;

    ELSE
        -- 기타: text만 사용
        title_text := '';
        body_text := NEW.text;
    END IF;

    -- tsvector 생성 (제목 A 가중치, 본문 B 가중치)
    NEW.text_tsv :=
        setweight(to_tsvector('pg_catalog.simple', COALESCE(title_text, '')), 'A') ||
        setweight(to_tsvector('pg_catalog.simple', COALESCE(body_text, '')), 'B');

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- tsvector 자동 업데이트 트리거
DROP TRIGGER IF EXISTS tsvector_update ON vector_chunks;
CREATE TRIGGER tsvector_update
BEFORE INSERT OR UPDATE ON vector_chunks
FOR EACH ROW EXECUTE FUNCTION update_text_tsv_with_weights();

-- =====================================================
-- 10. 성능 최적화 설정
-- =====================================================

-- HNSW 검색 품질 설정 (세션별)
-- ef_search: 검색 시 탐색 범위 (기본값: 40)
-- 값이 클수록 정확도 증가, 속도 감소
-- SET hnsw.ef_search = 100;

-- 벡터 연산 병렬 처리 설정
-- ALTER TABLE vector_chunks SET (parallel_workers = 4);

-- 전문 검색 설정 (Full-Text Search)
-- default_text_search_config: 한글은 simple 사용 (형태소 분석 없음)
-- SET default_text_search_config = 'pg_catalog.simple';

-- =====================================================
-- 11. 권한 설정 (필요 시)
-- =====================================================

-- 특정 사용자에게 권한 부여 (주석 해제 후 사용)
-- GRANT SELECT, INSERT, UPDATE, DELETE ON vector_chunks TO your_app_user;
-- GRANT USAGE, SELECT ON SEQUENCE vector_chunks_id_seq TO your_app_user;
-- GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO your_app_user;

-- =====================================================
-- 12. 코멘트 (테이블 및 컬럼 설명)
-- =====================================================

COMMENT ON TABLE vector_chunks IS
'통합 벡터 청크 테이블: A_law_ED_guide (법령/기준/규정) + B_case (상담/해결/조정 사례)';

COMMENT ON COLUMN vector_chunks.chunk_id IS
'청크 고유 식별자 (A: 법령_조항, B: crawl_카테고리_번호_필드_인덱스)';

COMMENT ON COLUMN vector_chunks.dataset_type IS
'데이터셋 구분: law_guide (A_law_ED_guide), case (B_case)';

COMMENT ON COLUMN vector_chunks.text IS
'임베딩된 텍스트 내용 (A: text 필드, B: content 필드)';

COMMENT ON COLUMN vector_chunks.embedding IS
'OpenAI text-embedding-3-large 벡터 (1536차원, Matryoshka)';

COMMENT ON COLUMN vector_chunks.law_name IS
'법령명 (A_law_ED_guide 전용, 예: 소비자기본법)';

COMMENT ON COLUMN vector_chunks.chunk_type IS
'청크 타입 (A: 조_전체/항_조항/호_조항/부모_청크/자식_청크, B: case)';

COMMENT ON COLUMN vector_chunks.category IS
'사례 카테고리 (B_case 전용: 상담, 해결, 조정)';

COMMENT ON COLUMN vector_chunks.document_type IS
'문서 유형 (A_law_ED_guide 전용: 법률, 시행령, 행정규칙, 별표)';

COMMENT ON COLUMN vector_chunks.source_url IS
'원본 URL (B_case 크롤링 전용, 인용 및 추적용)';

COMMENT ON COLUMN vector_chunks.source_file IS
'PDF 파일명 (B_case PDF 전용, 예: 2010년 소비자분쟁 해결사례집.pdf)';

COMMENT ON COLUMN vector_chunks.printed_page IS
'인쇄 페이지 번호 (B_case PDF 전용, 정확한 출처 표기용)';

COMMENT ON COLUMN vector_chunks.source_year IS
'연도 정보 (A: 시행일 연도, B_PDF: 파일명 연도, 통계 및 필터링용)';

COMMENT ON COLUMN vector_chunks.metadata IS
'데이터셋별 상세 메타데이터 (JSONB 형식)';

COMMENT ON COLUMN vector_chunks.text_tsv IS
'전문 검색용 tsvector (하이브리드 검색의 BM25 키워드 검색에 사용)';

COMMENT ON INDEX idx_embedding_hnsw IS
'HNSW 벡터 유사도 인덱스 (코사인 거리, m=16, ef_construction=64)';

COMMENT ON INDEX idx_text_tsv IS
'GIN 전문 검색 인덱스 (BM25 유사 키워드 검색, 하이브리드 검색용)';

COMMENT ON TABLE search_quality_logs IS
'하이브리드 검색 품질 모니터링 로그 (BM25, 벡터, RRF 성능 비교)';

-- =====================================================
-- 13. 테스트 쿼리 예시
-- =====================================================

-- 12.1 기본 통계 확인
-- SELECT * FROM dataset_statistics;
-- SELECT * FROM law_statistics LIMIT 10;
-- SELECT * FROM case_statistics;

-- 12.2 전체 청크 개수 확인
-- SELECT COUNT(*) as total_chunks FROM vector_chunks;
-- SELECT dataset_type, COUNT(*) FROM vector_chunks GROUP BY dataset_type;

-- 12.3 데이터 샘플 확인 (A_law_ED_guide)
-- SELECT chunk_id, law_name, chunk_type, LEFT(text, 100) as preview
-- FROM vector_chunks
-- WHERE dataset_type = 'law_guide'
-- LIMIT 5;

-- 12.4 데이터 샘플 확인 (B_case)
-- SELECT chunk_id, category, LEFT(text, 100) as preview
-- FROM vector_chunks
-- WHERE dataset_type = 'case'
-- LIMIT 5;

-- 12.5 임베딩 차원 검증
-- SELECT * FROM validate_embedding_dimensions();

-- 12.6 NULL 값 검증
-- SELECT * FROM validate_null_values();

-- 12.7 중복 검증
-- SELECT * FROM validate_duplicate_chunks();

-- 12.8 벡터 유사도 검색 테스트 (임베딩 예시 필요)
-- SELECT * FROM search_similar_chunks(
--     '[0.1, 0.2, ...]'::vector(1536),
--     NULL,  -- filter_dataset
--     NULL,  -- filter_category
--     NULL,  -- filter_law_name
--     10     -- result_limit
-- );

-- 12.9 하이브리드 검색 테스트
-- SELECT * FROM search_hybrid(
--     '[0.1, 0.2, ...]'::vector(1536),
--     5,     -- law_limit
--     5,     -- case_limit
--     '조정'  -- filter_category
-- );

-- 12.10 키워드 검색 테스트
-- SELECT * FROM search_with_keywords(
--     '[0.1, 0.2, ...]'::vector(1536),
--     '환불',
--     10
-- );

-- 12.11 출처별 검색 테스트

-- 특정 연도 PDF 사례만 검색
-- SELECT chunk_id, text, source_file, printed_page, similarity
-- FROM search_similar_chunks(
--     '[0.1, 0.2, ...]'::vector(1536),
--     'case',     -- filter_dataset
--     NULL,       -- filter_category
--     NULL,       -- filter_law_name
--     2020,       -- filter_year
--     10          -- result_limit
-- );

-- 특정 PDF 파일 내에서 페이지별로 검색
-- SELECT chunk_id, printed_page, LEFT(text, 100) as preview
-- FROM vector_chunks
-- WHERE source_file = '2020년 소비자분쟁 해결사례집.pdf'
-- ORDER BY printed_page;

-- 크롤링 URL 기반 검색 (특정 도메인)
-- SELECT chunk_id, source_url, LEFT(text, 100) as preview
-- FROM vector_chunks
-- WHERE source_url LIKE '%consumer.go.kr%'
-- LIMIT 10;

-- 12.12 출처별 통계 확인

-- PDF 파일별 통계
-- SELECT * FROM pdf_source_statistics;

-- 크롤링 URL 도메인별 통계
-- SELECT * FROM url_source_statistics;

-- 연도별 통계
-- SELECT * FROM year_statistics;

-- 12.13 하이브리드 검색 테스트 (BM25 + 벡터 + RRF)

-- BM25 키워드 검색만
-- SELECT chunk_id, bm25_score, LEFT(text, 100) as preview
-- FROM search_bm25(
--     '소비자기본법 제16조 환불',  -- 키워드 쿼리
--     'case',                      -- filter_dataset
--     NULL,                        -- filter_category
--     10                           -- result_limit
-- );

-- 하이브리드 검색 (RRF 통합)
-- SELECT
--     chunk_id,
--     dataset_type,
--     rrf_score,
--     bm25_score,
--     vector_similarity,
--     source_file,
--     printed_page,
--     LEFT(text, 100) as preview
-- FROM search_hybrid_rrf(
--     '소비자기본법 제16조 환불',              -- 키워드 쿼리
--     '[0.1, 0.2, ...]'::vector(1536),        -- 벡터 쿼리
--     NULL,                                    -- filter_dataset
--     NULL,                                    -- filter_category
--     NULL,                                    -- filter_year
--     10,                                      -- result_limit
--     60                                       -- rrf_k
-- );

-- 검색 품질 분석
-- SELECT * FROM search_quality_analysis
-- ORDER BY search_date DESC
-- LIMIT 30;

-- =====================================================
-- 설정 완료
-- =====================================================

-- 테이블 정보 출력
\d vector_chunks

-- 인덱스 목록 출력
\di

-- 함수 목록 출력
\df

-- 뷰 목록 출력
\dv

-- 통계 확인
SELECT
    'Database Setup Complete!' as status,
    COUNT(*) as total_chunks,
    COUNT(DISTINCT dataset_type) as datasets,
    pg_size_pretty(pg_total_relation_size('vector_chunks')) as table_size
FROM vector_chunks;

-- =====================================================
-- 다음 단계 안내
-- =====================================================

/*
[완료] 1. 스키마 생성 완료
[TODO] 2. A_law_ED_guide 데이터 삽입 (02_01_insert_law_guide.py)
[TODO] 3. B_case 데이터 삽입 (02_02_insert_case.py)
[TODO] 4. 인덱스 재구축 (필요 시)
[TODO] 5. 검색 API 구축 (03_01_search_api.py)
[TODO] 6. RAG 파이프라인 통합

참고:
- 대용량 데이터 삽입 시 HNSW 인덱스를 DROP 후 데이터 삽입, 완료 후 재생성 권장
- 정기적으로 VACUUM ANALYZE 실행
- 검색 품질 향상 필요 시 hnsw.ef_search 값 조정
*/
