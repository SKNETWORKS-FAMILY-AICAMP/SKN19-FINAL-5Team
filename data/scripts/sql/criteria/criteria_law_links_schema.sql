-- ============================================
-- 분쟁조정기준-법령 연결 데이터 스키마
-- 별표2의 reference_block과 법령(laws/law_units) 간 연결
-- ============================================

-- ============================================
-- 1. CRITERIA_LAW_LINKS (분쟁조정기준-법령 연결)
-- ============================================

CREATE TABLE IF NOT EXISTS criteria_law_links (
    link_id TEXT PRIMARY KEY,
    criteria_unit_id TEXT NOT NULL REFERENCES criteria_units(unit_id) ON DELETE CASCADE,
    law_unit_id TEXT REFERENCES law_units(doc_id) ON DELETE SET NULL,
    law_id TEXT REFERENCES laws(law_id) ON DELETE SET NULL,
    link_type TEXT NOT NULL,  -- 'cites', 'references', 'based_on', 'derived_from'
    raw_citation TEXT,
    law_name TEXT,
    article_no TEXT,
    ref_id TEXT,  -- 별표2 reference_block의 ref_id
    confidence_score NUMERIC DEFAULT 1.0,  -- 매칭 신뢰도 (0.0 ~ 1.0)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE criteria_law_links IS '분쟁조정기준(criteria_units)과 법령(law_units) 간 연결 테이블';
COMMENT ON COLUMN criteria_law_links.link_id IS '연결 고유 식별자 (criteria_unit_id_law_unit_id 형식)';
COMMENT ON COLUMN criteria_law_links.criteria_unit_id IS 'criteria_units.unit_id 참조 (별표2 해결기준)';
COMMENT ON COLUMN criteria_law_links.law_unit_id IS 'law_units.doc_id 참조 (법령 조문)';
COMMENT ON COLUMN criteria_law_links.law_id IS 'laws.law_id 참조 (법령 기본 정보)';
COMMENT ON COLUMN criteria_law_links.link_type IS '연결 타입: cites(인용), references(참조), based_on(근거), derived_from(파생)';
COMMENT ON COLUMN criteria_law_links.raw_citation IS '원문 인용 텍스트 (예: "「종자산업법」 제23조")';
COMMENT ON COLUMN criteria_law_links.ref_id IS '별표2 reference_block의 ref_id (예: "table2_ref_p1_01")';
COMMENT ON COLUMN criteria_law_links.confidence_score IS '법령 매칭 신뢰도 (1.0=확실, 0.0=불확실)';

-- ============================================
-- 2. ITEM_DISPUTE_TYPE_MAPPING (품목-분쟁유형 매핑)
-- ============================================

CREATE TABLE IF NOT EXISTS item_dispute_type_mapping (
    mapping_id TEXT PRIMARY KEY,
    item_name TEXT NOT NULL,
    item_group TEXT,
    category TEXT,
    dispute_type_id TEXT,
    dispute_type TEXT,
    criteria_unit_id TEXT REFERENCES criteria_units(unit_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE item_dispute_type_mapping IS '품목명과 분쟁유형 매핑 테이블 (별표1, 별표2 기반)';
COMMENT ON COLUMN item_dispute_type_mapping.mapping_id IS '매핑 고유 식별자';
COMMENT ON COLUMN item_dispute_type_mapping.item_name IS '품목명 (별표1의 items 또는 별표2의 item)';
COMMENT ON COLUMN item_dispute_type_mapping.item_group IS '품목 그룹 (별표1의 item_group)';
COMMENT ON COLUMN item_dispute_type_mapping.category IS '대분류 (예: "상품(재화)", "서비스")';
COMMENT ON COLUMN item_dispute_type_mapping.dispute_type_id IS '분쟁유형 ID (별표2의 dispute_type_id)';
COMMENT ON COLUMN item_dispute_type_mapping.dispute_type IS '분쟁유형 설명 (별표2의 dispute_type)';
COMMENT ON COLUMN item_dispute_type_mapping.criteria_unit_id IS '관련 criteria_units.unit_id (별표2 해결기준)';

-- ============================================
-- 인덱스
-- ============================================

-- criteria_unit_id 조회 (어떤 법령이 연결되어 있는지)
CREATE INDEX IF NOT EXISTS idx_criteria_law_links_criteria_unit 
    ON criteria_law_links(criteria_unit_id);

-- law_unit_id 조회 (어떤 기준이 이 법령을 참조하는지)
CREATE INDEX IF NOT EXISTS idx_criteria_law_links_law_unit 
    ON criteria_law_links(law_unit_id);

-- law_id 조회
CREATE INDEX IF NOT EXISTS idx_criteria_law_links_law_id 
    ON criteria_law_links(law_id);

-- ref_id 조회 (별표2 reference_block 기반)
CREATE INDEX IF NOT EXISTS idx_criteria_law_links_ref_id 
    ON criteria_law_links(ref_id);

-- link_type 조회
CREATE INDEX IF NOT EXISTS idx_criteria_law_links_link_type 
    ON criteria_law_links(link_type);

-- 복합 인덱스 (criteria_unit_id + link_type)
CREATE INDEX IF NOT EXISTS idx_criteria_law_links_criteria_link_type 
    ON criteria_law_links(criteria_unit_id, link_type);

-- 품목명 검색
CREATE INDEX IF NOT EXISTS idx_item_dispute_type_mapping_item_name 
    ON item_dispute_type_mapping(item_name);

-- 품목 그룹 검색
CREATE INDEX IF NOT EXISTS idx_item_dispute_type_mapping_item_group 
    ON item_dispute_type_mapping(item_group);

-- 분쟁유형 검색
CREATE INDEX IF NOT EXISTS idx_item_dispute_type_mapping_dispute_type 
    ON item_dispute_type_mapping(dispute_type);

-- 복합 인덱스 (품목명 + 분쟁유형)
CREATE INDEX IF NOT EXISTS idx_item_dispute_type_mapping_item_dispute 
    ON item_dispute_type_mapping(item_name, dispute_type);

-- ============================================
-- 통계 및 검증 쿼리 (참고용)
-- ============================================

-- criteria_unit_id별 연결된 법령 수
-- SELECT criteria_unit_id, COUNT(*) as law_count FROM criteria_law_links GROUP BY criteria_unit_id ORDER BY law_count DESC;

-- law_id별 참조하는 기준 수
-- SELECT law_id, COUNT(*) as criteria_count FROM criteria_law_links GROUP BY law_id ORDER BY criteria_count DESC;

-- link_type별 연결 수
-- SELECT link_type, COUNT(*) FROM criteria_law_links GROUP BY link_type;

-- 매칭 신뢰도별 분포
-- SELECT 
--     CASE 
--         WHEN confidence_score >= 0.9 THEN 'high'
--         WHEN confidence_score >= 0.7 THEN 'medium'
--         ELSE 'low'
--     END as confidence_level,
--     COUNT(*) as count
-- FROM criteria_law_links
-- GROUP BY confidence_level;

-- 품목별 분쟁유형 수
-- SELECT item_name, COUNT(DISTINCT dispute_type) as dispute_type_count 
-- FROM item_dispute_type_mapping 
-- GROUP BY item_name 
-- ORDER BY dispute_type_count DESC;
