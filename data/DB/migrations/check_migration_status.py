import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import os
from pathlib import Path

# .env 파일 로드 (migrations/ 폴더에서 실행되므로 상위 폴더의 .env 참조)
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

DB_CONFIG = {
    "host": os.getenv("DB_HOST").strip(),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME").strip(),
    "user": os.getenv("DB_USER").strip(),
    "password": os.getenv("DB_PASSWORD").strip()
}

try:
    print("="*80)
    print("Migration 상태 확인")
    print("="*80)

    conn = psycopg2.connect(**DB_CONFIG, connect_timeout=10)
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # 1. 컬럼 존재 확인
    print("\n[1] article_number 컬럼 존재 여부 확인:")
    cursor.execute("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'vector_chunks'
          AND column_name IN ('article_number', 'article_number_normalized')
        ORDER BY column_name
    """)
    columns = cursor.fetchall()

    if columns:
        print("   ✅ 컬럼 존재:")
        for col in columns:
            print(f"      - {col['column_name']} ({col['data_type']})")
    else:
        print("   ❌ 컬럼이 존재하지 않습니다.")
        print("   → migration을 실행해야 합니다.")

    # 2. 함수 존재 확인
    print("\n[2] normalize_article_number() 함수 존재 여부:")
    cursor.execute("""
        SELECT proname, pg_get_functiondef(oid) as definition
        FROM pg_proc
        WHERE proname = 'normalize_article_number'
    """)
    func = cursor.fetchone()

    if func:
        print("   ✅ 함수 존재")
    else:
        print("   ❌ 함수가 존재하지 않습니다.")

    # 3. 트리거 존재 확인
    print("\n[3] 트리거 존재 여부:")
    cursor.execute("""
        SELECT trigger_name, event_manipulation, action_statement
        FROM information_schema.triggers
        WHERE trigger_name = 'trigger_auto_normalize_article'
          AND event_object_table = 'vector_chunks'
    """)
    trigger = cursor.fetchone()

    if trigger:
        print("   ✅ 트리거 존재")
    else:
        print("   ❌ 트리거가 존재하지 않습니다.")

    # 4. 인덱스 존재 확인
    print("\n[4] 인덱스 존재 여부:")
    cursor.execute("""
        SELECT
            indexname,
            pg_size_pretty(pg_relation_size(indexrelid)) AS size
        FROM pg_indexes
        JOIN pg_stat_user_indexes ON indexrelname = indexname
        WHERE tablename = 'vector_chunks'
          AND indexname LIKE 'idx_article%'
        ORDER BY indexname
    """)
    indexes = cursor.fetchall()

    if indexes:
        print("   ✅ 인덱스 존재:")
        for idx in indexes:
            print(f"      - {idx['indexname']} ({idx['size']})")
    else:
        print("   ❌ article 관련 인덱스가 존재하지 않습니다.")

    # 5. 데이터 확인
    if columns:
        print("\n[5] 실제 데이터 확인:")
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(article_number) as with_article,
                COUNT(article_number_normalized) as with_normalized
            FROM vector_chunks
            WHERE dataset_type = 'law_guide'
        """)
        result = cursor.fetchone()

        print(f"   law_guide 데이터셋:")
        print(f"      - 총 레코드: {result['total']:,}개")
        print(f"      - article_number 있음: {result['with_article']:,}개")
        print(f"      - article_number_normalized 있음: {result['with_normalized']:,}개")

        # 샘플 데이터
        if result['with_article'] > 0:
            print("\n   샘플 데이터 (최대 5개):")
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
                print(f"      {row['law_name']:20s} | {row['article_number']:15s} → {row['article_number_normalized']}")

    print("\n" + "="*80)
    print("결론:")
    print("="*80)

    if columns and func and trigger and indexes:
        print("✅ Migration이 이미 적용되어 있습니다!")
        print("   스냅샷을 찍을 때 migration이 실행된 상태였습니다.")
        print("   별도의 작업이 필요하지 않습니다.")
    else:
        print("❌ Migration이 적용되지 않았습니다!")
        print("   스냅샷을 찍기 전에 migration을 실행하지 않았거나,")
        print("   스냅샷을 찍은 후에 migration을 실행했습니다.")
        print("\n   다음 명령어로 migration을 실행하세요:")
        print("   python migrations/migration_add_article_columns.py")

    print("="*80 + "\n")

    cursor.close()
    conn.close()

except Exception as e:
    print(f"\n❌ 오류 발생: {e}")
    import traceback
    traceback.print_exc()
