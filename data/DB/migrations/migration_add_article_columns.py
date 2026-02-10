"""
마이그레이션: 조문번호 컬럼 추가

목적:
- 기존 DB에 article_number, article_number_normalized 컬럼 추가
- PostgreSQL 정규화 함수 생성
- 자동 정규화 트리거 생성
- 인덱스 생성
- 기존 데이터 마이그레이션

실행 방법:
    python DB/02_04_migration_add_article_columns.py

주의:
- 이 스크립트는 idempotent 합니다 (여러 번 실행해도 안전)
- 기존 데이터가 있는 DB에 안전하게 적용됩니다
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import os
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime

# .env 파일 로드
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# PostgreSQL 연결 설정
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost").strip(),
    "port": int(os.getenv("DB_PORT", "5432").strip()),
    "database": os.getenv("DB_NAME", "ddoksori").strip(),
    "user": os.getenv("DB_USER", "postgres").strip(),
    "password": os.getenv("DB_PASSWORD", "postgres").strip()
}


def print_section(title):
    """섹션 헤더 출력"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def main():
    print_section("조문번호 컬럼 추가 마이그레이션")
    print(f"\n시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    start_time = datetime.now()

    # DB 연결
    print("[1/7] 데이터베이스 연결 중...")
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        print("      연결 성공!\n")
    except Exception as e:
        print(f"      [ERROR] 연결 실패: {e}")
        return

    try:
        # ============================================================
        # Step 1: 컬럼 추가
        # ============================================================
        print("[2/7] 컬럼 추가 중...")
        cursor.execute("""
            ALTER TABLE vector_chunks
            ADD COLUMN IF NOT EXISTS article_number VARCHAR(50);

            ALTER TABLE vector_chunks
            ADD COLUMN IF NOT EXISTS article_number_normalized VARCHAR(50);
        """)
        conn.commit()
        print("      article_number, article_number_normalized 컬럼 추가 완료\n")

        # ============================================================
        # Step 2: 정규화 함수 생성
        # ============================================================
        print("[3/7] PostgreSQL 정규화 함수 생성 중...")
        cursor.execute("""
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
            '조문번호 정규화 함수: "제" 제거';
        """)
        conn.commit()
        print("      normalize_article_number() 함수 생성 완료\n")

        # ============================================================
        # Step 3: 트리거 생성
        # ============================================================
        print("[4/7] 자동 정규화 트리거 생성 중...")
        cursor.execute("""
            CREATE OR REPLACE FUNCTION auto_normalize_article_trigger()
            RETURNS TRIGGER AS $$
            BEGIN
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
            '조문번호 자동 정규화 트리거';
        """)
        conn.commit()
        print("      trigger_auto_normalize_article 생성 완료\n")

        # ============================================================
        # Step 4: 기존 데이터 마이그레이션
        # ============================================================
        print("[5/7] 기존 데이터 마이그레이션 중...")

        # 4-1. article_number 추출 (metadata->>'조문번호')
        cursor.execute("""
            UPDATE vector_chunks
            SET article_number = TRIM(metadata->>'조문번호')
            WHERE
                dataset_type = 'law_guide'
                AND metadata->>'조문번호' IS NOT NULL
                AND TRIM(metadata->>'조문번호') != ''
                AND article_number IS NULL;
        """)
        updated_article = cursor.rowcount
        conn.commit()
        print(f"      article_number: {updated_article:,}개 업데이트")

        # 4-2. article_number_normalized 생성
        cursor.execute("""
            UPDATE vector_chunks
            SET article_number_normalized = normalize_article_number(article_number)
            WHERE
                article_number IS NOT NULL
                AND article_number_normalized IS NULL;
        """)
        updated_normalized = cursor.rowcount
        conn.commit()
        print(f"      article_number_normalized: {updated_normalized:,}개 생성\n")

        # ============================================================
        # Step 5: 인덱스 생성
        # ============================================================
        print("[6/7] 인덱스 생성 중...")

        # 단일 인덱스
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_article_number
            ON vector_chunks(article_number)
            WHERE article_number IS NOT NULL;
        """)
        print("      idx_article_number 생성 완료")

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_article_number_normalized
            ON vector_chunks(article_number_normalized)
            WHERE article_number_normalized IS NOT NULL;
        """)
        print("      idx_article_number_normalized 생성 완료")

        # 복합 인덱스
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_law_article
            ON vector_chunks(law_name, article_number)
            WHERE law_name IS NOT NULL AND article_number IS NOT NULL;
        """)
        print("      idx_law_article 생성 완료")

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_law_article_normalized
            ON vector_chunks(law_name, article_number_normalized)
            WHERE law_name IS NOT NULL AND article_number_normalized IS NOT NULL;
        """)
        print("      idx_law_article_normalized 생성 완료\n")

        conn.commit()

        # ============================================================
        # Step 6: 통계 업데이트
        # ============================================================
        print("[7/7] 통계 업데이트 중...")
        old_isolation_level = conn.isolation_level
        conn.set_isolation_level(0)  # autocommit
        cursor.execute("VACUUM ANALYZE vector_chunks")
        conn.set_isolation_level(old_isolation_level)
        print("      VACUUM ANALYZE 완료\n")

        # ============================================================
        # Step 7: 검증
        # ============================================================
        print_section("마이그레이션 검증")

        # 컬럼 확인
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(article_number) as with_article,
                COUNT(article_number_normalized) as with_normalized
            FROM vector_chunks
            WHERE dataset_type = 'law_guide'
        """)
        result = cursor.fetchone()
        print(f"\n[law_guide 데이터셋]")
        print(f"  총 레코드: {result['total']:,}개")
        print(f"  article_number: {result['with_article']:,}개")
        print(f"  article_number_normalized: {result['with_normalized']:,}개")

        # 샘플 확인
        print(f"\n[샘플 데이터]")
        cursor.execute("""
            SELECT
                law_name,
                article_number,
                article_number_normalized
            FROM vector_chunks
            WHERE article_number IS NOT NULL
            ORDER BY law_name, article_number
            LIMIT 5
        """)
        for row in cursor.fetchall():
            print(f"  {row['law_name']:20s} | {row['article_number']:15s} → {row['article_number_normalized']}")

        # 인덱스 확인
        print(f"\n[인덱스 확인]")
        cursor.execute("""
            SELECT
                indexrelname as index_name,
                pg_size_pretty(pg_relation_size(indexrelid)) AS size
            FROM pg_stat_user_indexes
            WHERE tablename = 'vector_chunks'
              AND indexrelname LIKE 'idx_article%'
            ORDER BY indexrelname
        """)
        for row in cursor.fetchall():
            print(f"  {row['index_name']:40s} | {row['size']}")

        # 테스트 쿼리
        print(f"\n[검색 테스트]")
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM vector_chunks
            WHERE law_name = '민법' AND article_number_normalized = '13조'
        """)
        count = cursor.fetchone()['count']
        print(f"  민법 + '13조' 검색: {count}건 (성공 예상)")

        cursor.execute("""
            SELECT COUNT(*) as count
            FROM vector_chunks
            WHERE law_name = '민법'
              AND article_number_normalized = normalize_article_number('제13조')
        """)
        count = cursor.fetchone()['count']
        print(f"  민법 + '제13조' 검색 (함수): {count}건 (성공 예상)")

        print_section("마이그레이션 완료!")

        elapsed_time = (datetime.now() - start_time).total_seconds()
        print(f"\n소요 시간: {elapsed_time:.2f}초 ({elapsed_time/60:.2f}분)")
        print(f"종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        print("[사용 예시]")
        print("""
-- Python API에서 사용:
cursor.execute('''
    SELECT * FROM vector_chunks
    WHERE law_name = %s
      AND article_number_normalized = normalize_article_number(%s)
''', ('민법', '13조'))  # '13조' 또는 '제13조' 모두 작동!

-- SQL에서 직접 사용:
SELECT * FROM vector_chunks
WHERE law_name = '민법'
  AND article_number_normalized = '13조';  -- '제13조' 매칭!
        """)

    except Exception as e:
        print(f"\n[ERROR] 에러 발생: {e}")
        conn.rollback()
        print("      [ROLLBACK] 롤백 완료")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        cursor.close()
        conn.close()
        print("\n데이터베이스 연결 종료\n")

    return 0


if __name__ == "__main__":
    exit(main())
