"""
document_type 데이터 분류 (수정 버전)

실제 데이터 구조에 맞게 분류 로직 적용:
- chunk_id에 "별표" 포함 → 별표
- law_name에 "지침" 포함 → 행정규칙
- law_name에 "시행령" 포함 → 시행령
- 그 외 → 법률

실행 방법:
    python DB/02_06_fix_document_type_classification.py
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

DB_CONFIG = {
    "host": os.getenv("DB_HOST").strip(),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME").strip(),
    "user": os.getenv("DB_USER").strip(),
    "password": os.getenv("DB_PASSWORD").strip()
}

print("="*80)
print("document_type 데이터 분류 (실제 데이터 기반)")
print("="*80)
print(f"\n시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

start_time = datetime.now()

try:
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    print("[1/5] 우선순위 기반 분류 시작...")

    # 1. 별표 분류 (chunk_id 기반)
    print("\n  [1-1] 별표 분류 중...")
    cursor.execute("""
        UPDATE vector_chunks
        SET document_type = '별표'
        WHERE
            dataset_type = 'law_guide'
            AND chunk_id LIKE '별표%'
            AND document_type IS NULL;
    """)
    count_byulpyo = cursor.rowcount
    conn.commit()
    print(f"       ✅ 별표: {count_byulpyo:,}개")

    # 2. 행정규칙 분류 (law_name에 "지침" 포함)
    print("  [1-2] 행정규칙 분류 중...")
    cursor.execute("""
        UPDATE vector_chunks
        SET document_type = '행정규칙'
        WHERE
            dataset_type = 'law_guide'
            AND law_name LIKE '%지침%'
            AND document_type IS NULL;
    """)
    count_guideline = cursor.rowcount
    conn.commit()
    print(f"       ✅ 행정규칙: {count_guideline:,}개")

    # 3. 시행령 분류 (law_name에 "시행령" 포함)
    print("  [1-3] 시행령 분류 중...")
    cursor.execute("""
        UPDATE vector_chunks
        SET document_type = '시행령'
        WHERE
            dataset_type = 'law_guide'
            AND law_name LIKE '%시행령%'
            AND document_type IS NULL;
    """)
    count_si_haengryeong = cursor.rowcount
    conn.commit()
    print(f"       ✅ 시행령: {count_si_haengryeong:,}개")

    # 4. 시행규칙 분류 (law_name에 "시행규칙" 포함)
    print("  [1-4] 시행규칙 분류 중...")
    cursor.execute("""
        UPDATE vector_chunks
        SET document_type = '시행규칙'
        WHERE
            dataset_type = 'law_guide'
            AND law_name LIKE '%시행규칙%'
            AND document_type IS NULL;
    """)
    count_si_haeng_gyuchik = cursor.rowcount
    conn.commit()
    print(f"       ✅ 시행규칙: {count_si_haeng_gyuchik:,}개")

    # 5. 나머지는 법률
    print("  [1-5] 법률 분류 중 (나머지)...")
    cursor.execute("""
        UPDATE vector_chunks
        SET document_type = '법률'
        WHERE
            dataset_type = 'law_guide'
            AND document_type IS NULL;
    """)
    count_law = cursor.rowcount
    conn.commit()
    print(f"       ✅ 법률: {count_law:,}개\n")

    # 통계
    print("[2/5] 분류 결과 확인...")
    cursor.execute("""
        SELECT
            document_type,
            COUNT(*) as count
        FROM vector_chunks
        WHERE dataset_type = 'law_guide'
        GROUP BY document_type
        ORDER BY
            CASE document_type
                WHEN '법률' THEN 1
                WHEN '시행령' THEN 2
                WHEN '시행규칙' THEN 3
                WHEN '행정규칙' THEN 4
                WHEN '별표' THEN 5
                ELSE 6
            END
    """)

    print("\n  document_type별 분포:")
    for row in cursor.fetchall():
        dt = row['document_type'] if row['document_type'] else 'NULL'
        print(f"    {dt:15s}: {row['count']:,}개")

    # 샘플 확인
    print("\n[3/5] 샘플 데이터 확인...")
    for doc_type in ['법률', '시행령', '시행규칙', '행정규칙', '별표']:
        cursor.execute("""
            SELECT law_name, COUNT(*) as count
            FROM vector_chunks
            WHERE dataset_type = 'law_guide' AND document_type = %s
            GROUP BY law_name
            ORDER BY count DESC
            LIMIT 3
        """, (doc_type,))

        results = cursor.fetchall()
        if results:
            print(f"\n  [{doc_type}] 상위 법령:")
            for row in results:
                law = row['law_name'] if row['law_name'] else '(law_name 없음)'
                print(f"    {law:40s}: {row['count']:,}개")

    # 인덱스 통계
    print("\n[4/5] 인덱스 크기 확인...")
    cursor.execute("""
        SELECT
            indexname,
            pg_size_pretty(pg_relation_size(schemaname||'.'||indexname)) as size
        FROM pg_indexes
        WHERE tablename = 'vector_chunks' AND indexname LIKE '%document_type%'
    """)
    for row in cursor.fetchall():
        print(f"  {row['indexname']:40s}: {row['size']}")

    # VACUUM ANALYZE
    print("\n[5/5] 통계 업데이트 중...")
    old_isolation = conn.isolation_level
    conn.set_isolation_level(0)
    cursor.execute("VACUUM ANALYZE vector_chunks")
    conn.set_isolation_level(old_isolation)
    print("  ✅ VACUUM ANALYZE 완료")

    print("\n" + "="*80)
    print("✅ 분류 완료!")
    print("="*80)

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n총 소요 시간: {elapsed:.2f}초")
    print(f"종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    cursor.close()
    conn.close()

except Exception as e:
    print(f"\n❌ 오류: {e}")
    import traceback
    traceback.print_exc()
