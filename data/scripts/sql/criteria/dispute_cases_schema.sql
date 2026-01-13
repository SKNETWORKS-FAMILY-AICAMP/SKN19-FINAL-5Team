-- ============================================
-- 분쟁조정사례 데이터 스키마
-- kjw/data/preprocess/ 하위 데이터 (kca.jsonl, ecmc.jsonl, kcdrc.jsonl) 적재용
-- ============================================

-- pgvector 확장 활성화 (필요시)
-- CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================
-- 1. DISPUTE_CASES (분쟁조정사례 기본 정보)
-- ============================================

CREATE TABLE IF NOT EXISTS dispute_cases (
    case_id TEXT PRIMARY KEY,
    agency TEXT NOT NULL,  -- 'kca', 'ecmc', 'kcdrc'
    case_no TEXT,
    decision_date DATE,
    source_pdf TEXT,
    case_index INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE dispute_cases IS '분쟁조정사례 기본 정보 테이블';
COMMENT ON COLUMN dispute_cases.case_id IS '사례 고유 식별자 (agency_case_index 형식, 예: kca_1)';
COMMENT ON COLUMN dispute_cases.agency IS '기관 코드: kca(한국소비자원), ecmc(전자거래분쟁조정위원회), kcdrc(한국콘텐츠진흥원)';
COMMENT ON COLUMN dispute_cases.case_no IS '사건번호';
COMMENT ON COLUMN dispute_cases.decision_date IS '결정일자';
COMMENT ON COLUMN dispute_cases.source_pdf IS '원본 PDF 파일명';

-- ============================================
-- 2. DISPUTE_CASE_CHUNKS (분쟁조정사례 청크)
-- ============================================

CREATE TABLE IF NOT EXISTS dispute_case_chunks (
    chunk_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES dispute_cases(case_id) ON DELETE CASCADE,
    section_type TEXT NOT NULL,  -- 'facts', 'claims', 'analysis', 'decision'
    chunk_index INTEGER NOT NULL,
    page_start INTEGER,
    page_end INTEGER,
    text TEXT NOT NULL,
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE dispute_case_chunks IS '분쟁조정사례 청크 테이블 (검색·조회·RAG 활용)';
COMMENT ON COLUMN dispute_case_chunks.chunk_id IS '청크 고유 식별자 (case_id_chunk_index 형식)';
COMMENT ON COLUMN dispute_case_chunks.case_id IS 'dispute_cases.case_id 참조';
COMMENT ON COLUMN dispute_case_chunks.section_type IS '섹션 타입: facts(사건개요), claims(당사자주장), analysis(조정부판단), decision(주문/조정결과)';
COMMENT ON COLUMN dispute_case_chunks.chunk_index IS '청크 인덱스 (같은 case_id, section_type 내에서 순서)';
COMMENT ON COLUMN dispute_case_chunks.text IS '청크 텍스트 내용';
COMMENT ON COLUMN dispute_case_chunks.embedding IS '벡터 임베딩 (text-embedding-3-small, 1536차원)';

-- ============================================
-- 인덱스
-- ============================================

-- 기관별 사례 조회
CREATE INDEX IF NOT EXISTS idx_dispute_cases_agency ON dispute_cases(agency);

-- 사건번호 조회
CREATE INDEX IF NOT EXISTS idx_dispute_cases_case_no ON dispute_cases(case_no);

-- 결정일자 조회
CREATE INDEX IF NOT EXISTS idx_dispute_cases_decision_date ON dispute_cases(decision_date);

-- case_id 조회 (외래키)
CREATE INDEX IF NOT EXISTS idx_dispute_case_chunks_case_id ON dispute_case_chunks(case_id);

-- 기관 + 섹션 타입 조합 검색
CREATE INDEX IF NOT EXISTS idx_dispute_case_chunks_agency_section 
    ON dispute_case_chunks(case_id, section_type);

-- 섹션 타입별 검색
CREATE INDEX IF NOT EXISTS idx_dispute_case_chunks_section_type 
    ON dispute_case_chunks(section_type);

-- 벡터 검색용 인덱스 (HNSW)
CREATE INDEX IF NOT EXISTS idx_dispute_case_chunks_embedding 
    ON dispute_case_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE embedding IS NOT NULL;

-- 전문 검색용 인덱스 (한국어)
CREATE INDEX IF NOT EXISTS idx_dispute_case_chunks_text_fts 
    ON dispute_case_chunks USING gin (to_tsvector('korean', text));

-- ============================================
-- 통계 및 검증 쿼리 (참고용)
-- ============================================

-- 기관별 사례 수
-- SELECT agency, COUNT(*) FROM dispute_cases GROUP BY agency ORDER BY agency;

-- 섹션 타입별 청크 수
-- SELECT section_type, COUNT(*) FROM dispute_case_chunks GROUP BY section_type ORDER BY section_type;

-- 사례별 청크 수
-- SELECT case_id, COUNT(*) as chunk_count FROM dispute_case_chunks GROUP BY case_id ORDER BY chunk_count DESC;

-- 임베딩이 없는 청크 수
-- SELECT section_type, COUNT(*) FROM dispute_case_chunks WHERE embedding IS NULL GROUP BY section_type;
