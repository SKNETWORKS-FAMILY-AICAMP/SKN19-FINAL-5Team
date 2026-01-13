-- ============================================
-- 기관 라우팅 규칙 스키마
-- KCA(한국소비자원), ECMC(전자거래분쟁조정위원회), KCDRC(한국콘텐츠진흥원) 판단 규칙
-- ============================================

-- ============================================
-- 1. AGENCY_ROUTING_RULES (기관 라우팅 규칙)
-- ============================================

CREATE TABLE IF NOT EXISTS agency_routing_rules (
    rule_id TEXT PRIMARY KEY,
    agency TEXT NOT NULL,  -- 'kca', 'ecmc', 'kcdrc'
    rule_name TEXT,
    rule_description TEXT,
    item_category TEXT,  -- '상품(재화)', '서비스' 등
    item_group TEXT,  -- 품목 그룹 (별표1의 item_group)
    item_name TEXT,  -- 구체적 품목명
    dispute_type TEXT,  -- 분쟁 유형
    conditions JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 복잡한 조건을 JSONB로 저장
    priority INTEGER DEFAULT 0,  -- 우선순위 (높을수록 우선)
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE agency_routing_rules IS '분쟁조정 신청 기관 판단 규칙 테이블';
COMMENT ON COLUMN agency_routing_rules.rule_id IS '규칙 고유 식별자';
COMMENT ON COLUMN agency_routing_rules.agency IS '기관 코드: kca(한국소비자원), ecmc(전자거래분쟁조정위원회), kcdrc(한국콘텐츠진흥원)';
COMMENT ON COLUMN agency_routing_rules.rule_name IS '규칙 이름 (예: "전자상거래 일반 분쟁")';
COMMENT ON COLUMN agency_routing_rules.rule_description IS '규칙 설명';
COMMENT ON COLUMN agency_routing_rules.item_category IS '대분류 필터 (NULL이면 모든 분류)';
COMMENT ON COLUMN agency_routing_rules.item_group IS '품목 그룹 필터 (NULL이면 모든 그룹)';
COMMENT ON COLUMN agency_routing_rules.item_name IS '구체적 품목명 필터 (NULL이면 모든 품목)';
COMMENT ON COLUMN agency_routing_rules.dispute_type IS '분쟁 유형 필터 (NULL이면 모든 유형)';
COMMENT ON COLUMN agency_routing_rules.conditions IS '복잡한 조건 (JSONB 형식)';
COMMENT ON COLUMN agency_routing_rules.priority IS '우선순위 (높을수록 먼저 매칭)';
COMMENT ON COLUMN agency_routing_rules.is_active IS '규칙 활성화 여부';

-- conditions JSONB 예시:
-- {
--   "min_amount": 1000000,  -- 최소 분쟁 금액
--   "max_amount": 10000000,  -- 최대 분쟁 금액
--   "exclude_items": ["의료서비스"],  -- 제외 품목
--   "include_keywords": ["전자상거래", "온라인"],  -- 포함 키워드
--   "exclude_keywords": ["오프라인"],  -- 제외 키워드
--   "required_fields": ["구매일자", "거래금액"]  -- 필수 입력 필드
-- }

-- ============================================
-- 2. AGENCY_INFO (기관 정보)
-- ============================================

CREATE TABLE IF NOT EXISTS agency_info (
    agency TEXT PRIMARY KEY,
    agency_name_kr TEXT NOT NULL,
    agency_name_en TEXT,
    description TEXT,
    website_url TEXT,
    contact_phone TEXT,
    contact_email TEXT,
    application_url TEXT,
    jurisdiction TEXT,  -- 관할 범위 설명
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE agency_info IS '분쟁조정 기관 기본 정보 테이블';
COMMENT ON COLUMN agency_info.agency IS '기관 코드: kca, ecmc, kcdrc';
COMMENT ON COLUMN agency_info.agency_name_kr IS '기관 한글명';
COMMENT ON COLUMN agency_info.agency_name_en IS '기관 영문명';
COMMENT ON COLUMN agency_info.jurisdiction IS '관할 범위 설명';

-- ============================================
-- 인덱스
-- ============================================

-- 기관별 규칙 조회
CREATE INDEX IF NOT EXISTS idx_agency_routing_rules_agency 
    ON agency_routing_rules(agency);

-- 활성화된 규칙만 조회
CREATE INDEX IF NOT EXISTS idx_agency_routing_rules_active 
    ON agency_routing_rules(is_active) WHERE is_active = TRUE;

-- 우선순위별 조회
CREATE INDEX IF NOT EXISTS idx_agency_routing_rules_priority 
    ON agency_routing_rules(priority DESC);

-- 품목명 검색
CREATE INDEX IF NOT EXISTS idx_agency_routing_rules_item_name 
    ON agency_routing_rules(item_name) WHERE item_name IS NOT NULL;

-- 분쟁 유형 검색
CREATE INDEX IF NOT EXISTS idx_agency_routing_rules_dispute_type 
    ON agency_routing_rules(dispute_type) WHERE dispute_type IS NOT NULL;

-- 복합 인덱스 (기관 + 활성화 + 우선순위)
CREATE INDEX IF NOT EXISTS idx_agency_routing_rules_agency_active_priority 
    ON agency_routing_rules(agency, is_active, priority DESC) 
    WHERE is_active = TRUE;

-- JSONB 조건 검색용 GIN 인덱스
CREATE INDEX IF NOT EXISTS idx_agency_routing_rules_conditions_gin 
    ON agency_routing_rules USING gin(conditions);

-- ============================================
-- 초기 데이터: 기관 정보 등록
-- ============================================

INSERT INTO agency_info (agency, agency_name_kr, agency_name_en, description, jurisdiction) VALUES
    ('kca', '한국소비자원', 'Korea Consumer Agency', 
     '소비자 피해 구제 및 분쟁 조정을 담당하는 기관', 
     '일반 소비자 분쟁 (의료, 전자상거래, 콘텐츠 제외)'),
    ('ecmc', '전자거래분쟁조정위원회', 'Electronic Commerce Mediation Committee', 
     '전자상거래 관련 분쟁 조정을 담당하는 기관', 
     '전자상거래 관련 분쟁'),
    ('kcdrc', '한국콘텐츠진흥원', 'Korea Creative Content Agency', 
     '콘텐츠 관련 분쟁 조정을 담당하는 기관', 
     '콘텐츠 관련 분쟁')
ON CONFLICT (agency) DO UPDATE SET
    agency_name_kr = EXCLUDED.agency_name_kr,
    agency_name_en = EXCLUDED.agency_name_en,
    description = EXCLUDED.description,
    jurisdiction = EXCLUDED.jurisdiction,
    updated_at = now();

-- ============================================
-- 초기 데이터: 기본 라우팅 규칙 (예시)
-- ============================================

-- ECMC: 전자상거래 관련 분쟁
INSERT INTO agency_routing_rules (rule_id, agency, rule_name, rule_description, item_category, conditions, priority) VALUES
    ('ecmc_001', 'ecmc', '전자상거래 일반 분쟁', 
     '전자상거래 플랫폼을 통한 거래 관련 분쟁', 
     '상품(재화)',
     '{"include_keywords": ["전자상거래", "온라인", "인터넷", "쇼핑몰", "오픈마켓"]}'::jsonb,
     100)
ON CONFLICT (rule_id) DO NOTHING;

-- KCDRC: 콘텐츠 관련 분쟁
INSERT INTO agency_routing_rules (rule_id, agency, rule_name, rule_description, item_category, conditions, priority) VALUES
    ('kcdrc_001', 'kcdrc', '콘텐츠 일반 분쟁', 
     '콘텐츠 이용 관련 분쟁', 
     '서비스',
     '{"include_keywords": ["콘텐츠", "게임", "음악", "영화", "도서", "웹툰", "웹소설"]}'::jsonb,
     100)
ON CONFLICT (rule_id) DO NOTHING;

-- KCA: 기본 분쟁 (나머지)
INSERT INTO agency_routing_rules (rule_id, agency, rule_name, rule_description, conditions, priority) VALUES
    ('kca_001', 'kca', '일반 소비자 분쟁', 
     'ECMC, KCDRC 관할이 아닌 일반 소비자 분쟁', 
     '{}'::jsonb,
     10)
ON CONFLICT (rule_id) DO NOTHING;

-- ============================================
-- 통계 및 검증 쿼리 (참고용)
-- ============================================

-- 기관별 활성화된 규칙 수
-- SELECT agency, COUNT(*) as rule_count 
-- FROM agency_routing_rules 
-- WHERE is_active = TRUE 
-- GROUP BY agency 
-- ORDER BY agency;

-- 우선순위별 규칙 분포
-- SELECT 
--     CASE 
--         WHEN priority >= 100 THEN 'high'
--         WHEN priority >= 50 THEN 'medium'
--         ELSE 'low'
--     END as priority_level,
--     COUNT(*) as count
-- FROM agency_routing_rules
-- WHERE is_active = TRUE
-- GROUP BY priority_level;

-- 품목별 매칭 규칙 수
-- SELECT item_name, COUNT(*) as rule_count 
-- FROM agency_routing_rules 
-- WHERE item_name IS NOT NULL AND is_active = TRUE
-- GROUP BY item_name 
-- ORDER BY rule_count DESC;
