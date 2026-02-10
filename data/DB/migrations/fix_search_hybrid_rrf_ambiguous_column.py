"""
마이그레이션: search_hybrid_rrf 함수 Ambiguous Column 오류 수정

문제:
- RETURNS TABLE(chunk_id ...) 형태로 인해 chunk_id가 내부 변수로도 존재
- vector_results CTE에서 SELECT chunk_id 사용 시 모호성 발생

해결:
- 테이블에 alias(vc) 부여
- 모든 컬럼 참조를 vc.컬럼명 형태로 명시

관련 문서: 04_02_DB오류해결.md
"""

import psycopg2
import os
from pathlib import Path
from dotenv import load_dotenv

# .env 파일 로드
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# PostgreSQL 연결 정보
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost").strip(),
    "port": int(os.getenv("DB_PORT", "5432").strip()),
    "database": os.getenv("DB_NAME", "ddoksori").strip(),
    "user": os.getenv("DB_USER", "postgres").strip(),
    "password": os.getenv("DB_PASSWORD", "postgres").strip()
}

# 수정된 함수 정의
FIXED_FUNCTION_SQL = """
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
"""

print("=" * 80)
print("[MIGRATION] search_hybrid_rrf 함수 Ambiguous Column 오류 수정")
print("=" * 80)

try:
    # 데이터베이스 연결
    print(f"\n[INFO] 연결 중... {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    cursor = conn.cursor()
    print("[OK] 연결 성공")

    # 기존 함수 확인
    print("\n[INFO] 기존 함수 확인 중...")
    cursor.execute("""
        SELECT routine_name
        FROM information_schema.routines
        WHERE routine_schema = 'public' AND routine_name = 'search_hybrid_rrf';
    """)
    result = cursor.fetchone()

    if result:
        print(f"[OK] 기존 함수 발견: {result[0]}")
    else:
        print("[WARNING] 기존 함수가 없습니다. 새로 생성합니다.")

    # 기존 함수 삭제 (반환 타입 변경을 위해 필요)
    if result:
        print("\n[INFO] 기존 함수 삭제 중...")
        cursor.execute("""
            DROP FUNCTION IF EXISTS search_hybrid_rrf(
                text, vector, character varying, character varying,
                character varying, integer, integer, integer
            );
        """)
        print("[OK] 기존 함수 삭제 완료")

    # 함수 생성
    print("\n[INFO] 새 함수 생성 중...")
    cursor.execute(FIXED_FUNCTION_SQL)
    conn.commit()
    print("[OK] 함수 생성 완료")

    # 업데이트 확인
    print("\n[INFO] 업데이트 확인 중...")
    cursor.execute("""
        SELECT pg_get_functiondef(p.oid)
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.proname = 'search_hybrid_rrf';
    """)
    function_def = cursor.fetchone()

    if function_def and 'vc.chunk_id' in function_def[0]:
        print("[OK] 함수가 올바르게 업데이트되었습니다 (vc.chunk_id 확인됨)")
    else:
        print("[WARNING] 함수 업데이트를 확인할 수 없습니다")

    print("\n" + "=" * 80)
    print("[SUCCESS] 마이그레이션 완료!")
    print("=" * 80)
    print("\n다음 단계:")
    print("1. 검색 API 테스트: python DB/03_02_test_search_api.py")
    print("2. 관련 문서 확인: DB/04_02_DB오류해결.md")

    cursor.close()
    conn.close()

except Exception as e:
    print(f"\n[ERROR] 오류 발생: {e}")
    if 'conn' in locals():
        conn.rollback()
        conn.close()
    raise
