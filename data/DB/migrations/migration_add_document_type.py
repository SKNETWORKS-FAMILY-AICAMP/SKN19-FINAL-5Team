"""
마이그레이션: document_type 컬럼 추가

목적:
- 기존 DB에 document_type 컬럼 추가
- law_guide 데이터를 '법률', '시행령', '행정규칙', '별표'로 분류
- 인덱스 생성

실행 방법:
    python DB/02_05_migration_add_document_type.py

주의:
- 이 스크립트는 idempotent 합니다 (여러 번 실행해도 안전)
- 기존 데이터가 있는 DB에 안전하게 적용됩니다
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

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
    print_section("document_type 컬럼 추가 마이그레이션")
    print(f"\n시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    start_time = datetime.now()

    # DB 연결
    print("[1/6] 데이터베이스 연결 중...")
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        print("      ✅ 연결 성공!\n")
    except Exception as e:
        print(f"      ❌ 연결 실패: {e}")
        return

    try:
        # ============================================================
        # Step 1: 컬럼 추가
        # ============================================================
        print("[2/6] document_type 컬럼 추가 중...")
        cursor.execute("""
            ALTER TABLE vector_chunks
            ADD COLUMN IF NOT EXISTS document_type VARCHAR(20);
        """)
        conn.commit()
        print("      ✅ document_type 컬럼 추가 완료\n")

        # ============================================================
        # Step 2: 기존 데이터 분류
        # ============================================================
        print("[3/6] 기존 law_guide 데이터 분류 중...")

        # 분류 로직:
        # 1. metadata->>'문서유형'이 있으면 그대로 사용
        # 2. chunk_type 또는 law_name 기반 추론
        # 3. 파일명 기반 추론

        # 2-1. metadata->>'문서유형' 직접 사용
        cursor.execute("""
            UPDATE vector_chunks
            SET document_type = TRIM(metadata->>'문서유형')
            WHERE
                dataset_type = 'law_guide'
                AND metadata->>'문서유형' IS NOT NULL
                AND TRIM(metadata->>'문서유형') != ''
                AND document_type IS NULL;
        """)
        updated_from_metadata = cursor.rowcount
        conn.commit()
        print(f"      metadata->>'문서유형' 사용: {updated_from_metadata:,}개")

        # 2-2. chunk_type 기반 분류
        # chunk_type이 'law_ED'면 법률, 'guide'면 행정규칙
        cursor.execute("""
            UPDATE vector_chunks
            SET document_type = CASE
                WHEN chunk_type = 'law_ED' THEN '법률'
                WHEN chunk_type = 'guide' THEN '행정규칙'
                ELSE NULL
            END
            WHERE
                dataset_type = 'law_guide'
                AND chunk_type IN ('law_ED', 'guide')
                AND document_type IS NULL;
        """)
        updated_from_chunk_type = cursor.rowcount
        conn.commit()
        print(f"      chunk_type 기반 분류: {updated_from_chunk_type:,}개")

        # 2-3. source_file 기반 추가 분류
        cursor.execute("""
            UPDATE vector_chunks
            SET document_type = CASE
                WHEN source_file LIKE '%법령%' OR source_file LIKE '%law%' THEN '법률'
                WHEN source_file LIKE '%시행령%' THEN '시행령'
                WHEN source_file LIKE '%가이드%' OR source_file LIKE '%guide%' OR source_file LIKE '%해결기준%' THEN '행정규칙'
                WHEN source_file LIKE '%별표%' THEN '별표'
                ELSE NULL
            END
            WHERE
                dataset_type = 'law_guide'
                AND source_file IS NOT NULL
                AND document_type IS NULL;
        """)
        updated_from_source_file = cursor.rowcount
        conn.commit()
        print(f"      source_file 기반 분류: {updated_from_source_file:,}개")

        # 2-4. text 내용 기반 추론 (별표 감지)
        cursor.execute("""
            UPDATE vector_chunks
            SET document_type = '별표'
            WHERE
                dataset_type = 'law_guide'
                AND (text LIKE '별표%' OR text LIKE '[별표%')
                AND document_type IS NULL;
        """)
        updated_from_text = cursor.rowcount
        conn.commit()
        print(f"      text 내용 기반 분류 (별표): {updated_from_text:,}개\n")

        # ============================================================
        # Step 3: 인덱스 생성
        # ============================================================
        print("[4/6] 인덱스 생성 중...")

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_document_type
            ON vector_chunks(document_type)
            WHERE document_type IS NOT NULL;
        """)
        print("      ✅ idx_document_type 생성 완료")

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_dataset_document_type
            ON vector_chunks(dataset_type, document_type)
            WHERE document_type IS NOT NULL;
        """)
        print("      ✅ idx_dataset_document_type 생성 완료\n")

        conn.commit()

        # ============================================================
        # Step 4: 통계 업데이트
        # ============================================================
        print("[5/6] 통계 업데이트 중...")
        old_isolation_level = conn.isolation_level
        conn.set_isolation_level(0)  # autocommit
        cursor.execute("VACUUM ANALYZE vector_chunks")
        conn.set_isolation_level(old_isolation_level)
        print("      ✅ VACUUM ANALYZE 완료\n")

        # ============================================================
        # Step 5: 검증
        # ============================================================
        print("[6/6] 마이그레이션 검증 중...")
        print_section("마이그레이션 결과")

        # 전체 통계
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(document_type) as with_document_type
            FROM vector_chunks
            WHERE dataset_type = 'law_guide'
        """)
        result = cursor.fetchone()
        print(f"\n[law_guide 데이터셋]")
        print(f"  총 레코드: {result['total']:,}개")
        print(f"  document_type 있음: {result['with_document_type']:,}개")
        print(f"  document_type 없음: {result['total'] - result['with_document_type']:,}개")

        # document_type별 분포
        cursor.execute("""
            SELECT
                document_type,
                COUNT(*) as count
            FROM vector_chunks
            WHERE dataset_type = 'law_guide' AND document_type IS NOT NULL
            GROUP BY document_type
            ORDER BY count DESC
        """)
        print(f"\n[document_type별 분포]")
        for row in cursor.fetchall():
            print(f"  {row['document_type']:15s}: {row['count']:,}개")

        # 샘플 확인
        print(f"\n[샘플 데이터]")
        cursor.execute("""
            SELECT
                document_type,
                law_name,
                LEFT(text, 60) as text_preview
            FROM vector_chunks
            WHERE dataset_type = 'law_guide' AND document_type IS NOT NULL
            ORDER BY document_type, law_name
            LIMIT 10
        """)
        for row in cursor.fetchall():
            print(f"  [{row['document_type']:8s}] {row['law_name']:20s} | {row['text_preview']}...")

        # 인덱스 확인
        print(f"\n[인덱스 확인]")
        cursor.execute("""
            SELECT
                indexname as index_name,
                pg_size_pretty(pg_relation_size(i.indexrelid)) AS size
            FROM pg_indexes
            JOIN pg_class t ON t.relname = tablename
            JOIN pg_index ix ON t.oid = ix.indrelid
            JOIN pg_class i ON i.oid = ix.indexrelid
            WHERE tablename = 'vector_chunks'
              AND indexname LIKE '%document_type%'
            ORDER BY indexname
        """)
        for row in cursor.fetchall():
            print(f"  {row['index_name']:40s} | {row['size']}")

        # NULL 데이터 확인 (분류 실패)
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM vector_chunks
            WHERE dataset_type = 'law_guide' AND document_type IS NULL
        """)
        null_count = cursor.fetchone()['count']
        if null_count > 0:
            print(f"\n[분류 실패 데이터]")
            print(f"  ⚠️  {null_count:,}개 데이터의 document_type이 NULL입니다.")
            print(f"  이 데이터들은 검색 시 document_type 필터에 걸리지 않습니다.")

            # NULL 데이터 샘플
            cursor.execute("""
                SELECT
                    chunk_type,
                    law_name,
                    source_file,
                    LEFT(text, 50) as text_preview
                FROM vector_chunks
                WHERE dataset_type = 'law_guide' AND document_type IS NULL
                LIMIT 5
            """)
            print(f"\n  샘플 (NULL document_type):")
            for row in cursor.fetchall():
                print(f"    chunk_type={row['chunk_type']}, law={row['law_name']}, file={row['source_file']}")
                print(f"    text: {row['text_preview']}...")

        print_section("마이그레이션 완료! ✅")

        elapsed_time = (datetime.now() - start_time).total_seconds()
        print(f"\n소요 시간: {elapsed_time:.2f}초 ({elapsed_time/60:.2f}분)")
        print(f"종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        print("[사용 예시]")
        print("""
-- Python API에서 사용:
cursor.execute('''
    SELECT * FROM vector_chunks
    WHERE dataset_type = 'law_guide'
      AND document_type = %s
''', ('행정규칙',))  # '법률', '시행령', '행정규칙', '별표'

-- SQL에서 직접 사용:
SELECT * FROM vector_chunks
WHERE dataset_type = 'law_guide'
  AND document_type IN ('행정규칙', '별표');  -- 해결기준만 검색
        """)

    except Exception as e:
        print(f"\n❌ 에러 발생: {e}")
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
