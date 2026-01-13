-- ============================================
-- 마이그레이션: SPLADE Sparse Vector 지원 추가
-- 작성일: 2026-01-08
-- 목적: chunks 테이블에 SPLADE sparse vector 저장 및 검색 최적화
-- ============================================

-- 1. chunks 테이블에 splade_sparse_vector 컬럼 추가
-- JSONB 형식으로 {token_id: weight} 형태 저장
-- 예: {"1234": 2.5, "5678": 1.8, ...}
ALTER TABLE chunks 
ADD COLUMN IF NOT EXISTS splade_sparse_vector JSONB;

-- 2. SPLADE 모델 정보 컬럼 추가
ALTER TABLE chunks
ADD COLUMN IF NOT EXISTS splade_model VARCHAR(50) DEFAULT 'naver/splade-v3';

-- 3. SPLADE 인코딩 완료 여부 플래그 추가
ALTER TABLE chunks
ADD COLUMN IF NOT EXISTS splade_encoded BOOLEAN DEFAULT FALSE;

-- 4. 코멘트 추가
COMMENT ON COLUMN chunks.splade_sparse_vector IS 'SPLADE sparse vector: {token_id: weight} 형태의 JSONB. 0이 아닌 토큰만 저장하여 공간 효율적';
COMMENT ON COLUMN chunks.splade_model IS '사용된 SPLADE 모델 버전';
COMMENT ON COLUMN chunks.splade_encoded IS 'SPLADE 인코딩 완료 여부';

-- 5. GIN 인덱스 생성 (JSONB 검색 최적화)
-- token_id로 빠른 검색을 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_chunks_splade_vector_gin 
ON chunks USING GIN (splade_sparse_vector);

-- 6. splade_encoded 인덱스 (인코딩 상태 확인용)
CREATE INDEX IF NOT EXISTS idx_chunks_splade_encoded 
ON chunks(splade_encoded) 
WHERE splade_encoded = FALSE;

-- 7. 활성 청크 + SPLADE 인코딩 완료된 청크만을 위한 복합 인덱스
CREATE INDEX IF NOT EXISTS idx_chunks_splade_active 
ON chunks(doc_id, chunk_type) 
WHERE splade_encoded = TRUE AND drop = FALSE;

-- 8. 함수: SPLADE sparse vector에서 특정 토큰 검색
-- 사용 예: SELECT * FROM chunks WHERE splade_vector_contains_token(splade_sparse_vector, '1234');
CREATE OR REPLACE FUNCTION splade_vector_contains_token(
    sparse_vec JSONB,
    token_id TEXT
) RETURNS BOOLEAN AS $$
BEGIN
    RETURN sparse_vec ? token_id;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 9. 함수: SPLADE sparse vector의 dot product 계산 (PostgreSQL 내에서)
-- 주의: 이 함수는 간단한 구현이며, 실제 검색은 Python에서 수행하는 것이 더 효율적
CREATE OR REPLACE FUNCTION splade_vector_dot_product(
    vec1 JSONB,
    vec2 JSONB
) RETURNS FLOAT AS $$
DECLARE
    result FLOAT := 0.0;
    key TEXT;
BEGIN
    -- vec1의 모든 키에 대해 vec2에 같은 키가 있으면 곱셈하여 누적
    FOR key IN SELECT jsonb_object_keys(vec1)
    LOOP
        IF vec2 ? key THEN
            result := result + (vec1->>key)::FLOAT * (vec2->>key)::FLOAT;
        END IF;
    END LOOP;
    
    RETURN result;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 10. 통계 정보 업데이트
ANALYZE chunks;

-- 마이그레이션 완료 메시지
DO $$
BEGIN
    RAISE NOTICE '✅ SPLADE sparse vector 지원이 추가되었습니다.';
    RAISE NOTICE '   - splade_sparse_vector 컬럼 (JSONB)';
    RAISE NOTICE '   - GIN 인덱스 생성 완료';
    RAISE NOTICE '   - 다음 단계: encode_splade_vectors.py 실행하여 인코딩 시작';
END $$;
