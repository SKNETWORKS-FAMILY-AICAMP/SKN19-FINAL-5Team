-- ============================================
-- 분쟁조정기준 데이터 스키마 (새 버전)
-- criteria (원천) + criteria_units (단위 레코드) 구조
-- ============================================

-- pgvector 확장 활성화 (필요시)
-- CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================
-- 1. CRITERIA (분쟁기준 데이터 원천)
-- ============================================

CREATE TABLE IF NOT EXISTS criteria (
    source_id TEXT PRIMARY KEY,
    source_label TEXT,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE criteria IS '분쟁조정기준 데이터 원천 테이블 (별표1~4, 지침 등)';
COMMENT ON COLUMN criteria.source_id IS '원천 고유 식별자 (예: table1, table2, table3, table4, ecommerce_guideline, guideline_mcst)';
COMMENT ON COLUMN criteria.source_label IS '화면/문서 표시용 이름 (예: 별표1 품목 분류, 전자상거래 소비자보호 지침)';
COMMENT ON COLUMN criteria.description IS '원천 데이터에 대한 간단한 설명';

-- ============================================
-- 2. CRITERIA_UNITS (분쟁기준 단위 레코드)
-- ============================================

CREATE TABLE IF NOT EXISTS criteria_units (
    unit_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES criteria(source_id) ON DELETE CASCADE,
    record_type TEXT,
    unit_type TEXT,
    path_hint TEXT,
    unit_text TEXT NOT NULL,
    content_md5 TEXT,
    doc JSONB NOT NULL,
    embedding VECTOR(1536),
    -- 계층 검색용 필드
    category TEXT,
    industry TEXT,
    item_group TEXT,
    item TEXT,
    dispute_type TEXT,
    search_stage TEXT,  -- 'stage1' 또는 'stage2'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE criteria_units IS '분쟁조정기준 단위 레코드 (검색·조회·RAG 활용)';
COMMENT ON COLUMN criteria_units.unit_id IS '단위 고유 식별자 (원천 ID + 내부 식별자 조합)';
COMMENT ON COLUMN criteria_units.source_id IS 'criteria.source_id 참조';
COMMENT ON COLUMN criteria_units.record_type IS '원천별 레코드 구분값 (예: item_chunk, rule_chunk, reference_block)';
COMMENT ON COLUMN criteria_units.unit_type IS '청킹 과정에서 생성된 세부 유형 (없을 경우 NULL)';
COMMENT ON COLUMN criteria_units.path_hint IS '문서/헤딩 기반 경로 요약 (검색 결과 설명용)';
COMMENT ON COLUMN criteria_units.unit_text IS '검색·RAG 응답에 사용할 대표 텍스트';
COMMENT ON COLUMN criteria_units.content_md5 IS '대표 텍스트 기반 중복 방지용 해시';
COMMENT ON COLUMN criteria_units.doc IS '업로드된 JSONL 원형 데이터 전체 (JSONB)';
COMMENT ON COLUMN criteria_units.embedding IS '벡터 임베딩 (OpenAI text-embedding-3-small, 1536차원)';

-- ============================================
-- 인덱스 생성
-- ============================================

-- 기본 인덱스
CREATE INDEX IF NOT EXISTS idx_criteria_units_source_id ON criteria_units(source_id);
CREATE INDEX IF NOT EXISTS idx_criteria_units_record_type ON criteria_units(record_type);
CREATE INDEX IF NOT EXISTS idx_criteria_units_unit_type ON criteria_units(unit_type);
CREATE INDEX IF NOT EXISTS idx_criteria_units_content_md5 ON criteria_units(content_md5);

-- 벡터 검색 인덱스 (HNSW)
CREATE INDEX IF NOT EXISTS idx_criteria_units_embedding_hnsw 
    ON criteria_units USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 전문 검색 인덱스 (한국어)
CREATE INDEX IF NOT EXISTS idx_criteria_units_unit_text_gin 
    ON criteria_units USING gin(to_tsvector('korean', unit_text));

-- JSONB 인덱스 (doc 내부 필드 검색용)
CREATE INDEX IF NOT EXISTS idx_criteria_units_doc_gin 
    ON criteria_units USING gin(doc);

-- 복합 인덱스 (source_id + record_type 조합 검색)
CREATE INDEX IF NOT EXISTS idx_criteria_units_source_record 
    ON criteria_units(source_id, record_type);

-- 계층 검색용 인덱스
CREATE INDEX IF NOT EXISTS idx_criteria_units_category_industry 
    ON criteria_units(category, industry);
CREATE INDEX IF NOT EXISTS idx_criteria_units_item_group 
    ON criteria_units(item_group);
CREATE INDEX IF NOT EXISTS idx_criteria_units_search_stage 
    ON criteria_units(search_stage);
CREATE INDEX IF NOT EXISTS idx_criteria_units_dispute_type 
    ON criteria_units(dispute_type);

-- ============================================
-- 초기 데이터: criteria 원천 등록
-- ============================================

INSERT INTO criteria (source_id, source_label, description) VALUES
    ('table1', '별표1 품목 분류', '소비자분쟁해결기준 대상품목 분류'),
    ('table2', '별표2 해결기준', '소비자분쟁해결기준 품목별 해결기준'),
    ('table3', '별표3 품질보증기간', '소비자분쟁해결기준 품목별 품질보증기간 및 부품보유기간'),
    ('table4', '별표4 내용연수', '소비자분쟁해결기준 품목별 내용연수'),
    ('ecommerce_guideline', '전자상거래 소비자보호 지침', '전자상거래 등에서의 소비자보호 지침'),
    ('content_guideline', '콘텐츠 소비자보호 지침', '콘텐츠 소비자보호 지침')
ON CONFLICT (source_id) DO NOTHING;

-- ============================================
-- 통계 및 검증 쿼리 (참고용)
-- ============================================

-- 원천별 단위 레코드 수
-- SELECT source_id, COUNT(*) FROM criteria_units GROUP BY source_id ORDER BY source_id;

-- record_type별 레코드 수
-- SELECT source_id, record_type, COUNT(*) FROM criteria_units GROUP BY source_id, record_type ORDER BY source_id, record_type;

-- 임베딩이 없는 레코드 수
-- SELECT source_id, COUNT(*) FROM criteria_units WHERE embedding IS NULL AND unit_text IS NOT NULL GROUP BY source_id;

-- 중복 체크 (content_md5)
-- SELECT content_md5, COUNT(*) FROM criteria_units WHERE content_md5 IS NOT NULL GROUP BY content_md5 HAVING COUNT(*) > 1;
