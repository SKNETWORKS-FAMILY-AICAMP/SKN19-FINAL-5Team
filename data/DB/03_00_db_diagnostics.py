"""
DB 진단 도구 (통합)

기능:
- Quick 모드: 빠른 연결 테스트 (기본)
- Full 모드: 상세 스키마 검증

사용법:
    python 03_00_db_diagnostics.py           # Quick 모드 (빠른 연결 테스트)
    python 03_00_db_diagnostics.py --full    # Full 모드 (상세 스키마 검증)
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import os
from pathlib import Path
import argparse

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


def run_quick_test():
    """빠른 연결 테스트 (구 test_connection.py)"""
    try:
        print("=" * 80)
        print("🔌 AWS RDS 연결 테스트 중...")
        print("=" * 80)
        print(f"   Host: {DB_CONFIG['host']}")
        print(f"   Database: {DB_CONFIG['database']}")
        print(f"   User: {DB_CONFIG['user']}")
        print(f"   Port: {DB_CONFIG['port']}")

        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=10)
        cursor = conn.cursor()

        # PostgreSQL 버전 확인
        cursor.execute("SELECT version();")
        version = cursor.fetchone()
        print(f"\n✅ 연결 성공!")
        print(f"   PostgreSQL Version: {version[0][:80]}...")

        # pgvector 확인
        cursor.execute("""
            SELECT extname, extversion
            FROM pg_extension
            WHERE extname = 'vector'
        """)
        pgvector = cursor.fetchone()
        if pgvector:
            print(f"   pgvector Version: {pgvector[1]}")

        # vector_chunks 테이블 확인
        cursor.execute("SELECT COUNT(*) FROM vector_chunks")
        chunk_count = cursor.fetchone()[0]
        print(f"   총 청크 수: {chunk_count:,}개")

        # 데이터셋별 통계
        cursor.execute("""
            SELECT dataset_type, COUNT(*)
            FROM vector_chunks
            GROUP BY dataset_type
            ORDER BY dataset_type
        """)
        print(f"\n📊 데이터셋별 통계:")
        for row in cursor.fetchall():
            print(f"   - {row[0]}: {row[1]:,}개")

        # 카테고리별 통계 (case 데이터)
        cursor.execute("""
            SELECT category, COUNT(*)
            FROM vector_chunks
            WHERE dataset_type = 'case' AND category IS NOT NULL
            GROUP BY category
            ORDER BY COUNT(*) DESC
        """)
        print(f"\n📂 카테고리별 통계 (case):")
        for row in cursor.fetchall():
            print(f"   - {row[0]}: {row[1]:,}개")

        cursor.close()
        conn.close()
        print("\n" + "=" * 80)
        print("🎉 DB 연결 테스트 완료!")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ 연결 실패: {e}")
        print("\n📌 체크리스트:")
        print("   1. .env 파일의 DB_PASSWORD가 정확한가요?")
        print("   2. 인터넷 연결이 정상인가요?")
        print("   3. AWS RDS 인스턴스가 '사용 가능' 상태인가요?")
        print("   4. 보안 그룹에서 5432 포트가 열려있나요?")


def run_full_diagnostics():
    """상세 스키마 검증 (구 check_schema_sync.py)"""
    print("=" * 80)
    print("DB 스키마 및 데이터 동기화 상태 확인")
    print("=" * 80)

    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=10)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # ================================================================
        # 1. 테이블 구조 확인
        # ================================================================
        print("\n[1] vector_chunks 테이블 컬럼 확인:")
        cursor.execute("""
            SELECT
                column_name,
                data_type,
                character_maximum_length,
                is_nullable
            FROM information_schema.columns
            WHERE table_name = 'vector_chunks'
            ORDER BY ordinal_position
        """)
        columns = cursor.fetchall()

        print(f"   총 {len(columns)}개 컬럼:")
        for col in columns:
            nullable = "NULL" if col['is_nullable'] == 'YES' else "NOT NULL"
            if col['character_maximum_length']:
                print(f"      - {col['column_name']:30s} {col['data_type']}({col['character_maximum_length']}) {nullable}")
            else:
                print(f"      - {col['column_name']:30s} {col['data_type']:20s} {nullable}")

        # ================================================================
        # 2. 인덱스 확인
        # ================================================================
        print("\n[2] 인덱스 확인:")
        cursor.execute("""
            SELECT
                indexname,
                indexdef,
                pg_size_pretty(pg_relation_size(indexrelid)) AS size
            FROM pg_indexes
            JOIN pg_stat_user_indexes ON indexrelname = indexname
            WHERE tablename = 'vector_chunks'
            ORDER BY indexname
        """)
        indexes = cursor.fetchall()

        print(f"   총 {len(indexes)}개 인덱스:")
        for idx in indexes:
            print(f"      - {idx['indexname']:40s} ({idx['size']})")

        # ================================================================
        # 3. 함수 확인
        # ================================================================
        print("\n[3] 커스텀 함수 확인:")
        cursor.execute("""
            SELECT
                proname as function_name,
                pg_get_function_result(oid) as return_type
            FROM pg_proc
            WHERE pronamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
              AND prokind = 'f'
            ORDER BY proname
        """)
        functions = cursor.fetchall()

        print(f"   총 {len(functions)}개 함수:")
        important_functions = [
            'search_hybrid_rrf',
            'search_bm25',
            'search_similar_chunks',
            'normalize_article_number'
        ]

        for func in functions:
            if any(imp in func['function_name'] for imp in important_functions):
                print(f"      ✅ {func['function_name']}")

        missing_functions = []
        for imp in important_functions:
            if not any(imp in f['function_name'] for f in functions):
                missing_functions.append(imp)

        if missing_functions:
            print(f"      ❌ 누락된 중요 함수:")
            for mf in missing_functions:
                print(f"         - {mf}")

        # ================================================================
        # 4. 뷰 확인
        # ================================================================
        print("\n[4] 뷰 확인:")
        cursor.execute("""
            SELECT table_name
            FROM information_schema.views
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        views = cursor.fetchall()

        print(f"   총 {len(views)}개 뷰:")
        for view in views:
            print(f"      - {view['table_name']}")

        # ================================================================
        # 5. 데이터 개수 확인
        # ================================================================
        print("\n[5] 데이터 개수 확인:")

        # 전체 개수
        cursor.execute("SELECT COUNT(*) as count FROM vector_chunks")
        total = cursor.fetchone()['count']
        print(f"   총 청크: {total:,}개")

        # 데이터셋별
        cursor.execute("""
            SELECT dataset_type, COUNT(*) as count
            FROM vector_chunks
            GROUP BY dataset_type
            ORDER BY dataset_type
        """)
        for row in cursor.fetchall():
            print(f"      - {row['dataset_type']}: {row['count']:,}개")

        # 카테고리별
        cursor.execute("""
            SELECT category, COUNT(*) as count
            FROM vector_chunks
            WHERE dataset_type = 'case' AND category IS NOT NULL
            GROUP BY category
            ORDER BY count DESC
        """)
        print(f"\n   case 카테고리별:")
        for row in cursor.fetchall():
            print(f"      - {row['category']}: {row['count']:,}개")

        # document_type별 (law_guide)
        cursor.execute("""
            SELECT document_type, COUNT(*) as count
            FROM vector_chunks
            WHERE dataset_type = 'law_guide' AND document_type IS NOT NULL
            GROUP BY document_type
            ORDER BY count DESC
        """)
        print(f"\n   law_guide document_type별:")
        for row in cursor.fetchall():
            print(f"      - {row['document_type']}: {row['count']:,}개")

        # ================================================================
        # 6. 최신성 확인
        # ================================================================
        print("\n[6] 데이터 최신성 확인:")
        cursor.execute("""
            SELECT
                MIN(created_at) as oldest,
                MAX(created_at) as newest,
                MAX(updated_at) as last_updated
            FROM vector_chunks
        """)
        dates = cursor.fetchone()
        print(f"   가장 오래된 데이터: {dates['oldest']}")
        print(f"   가장 최신 데이터: {dates['newest']}")
        print(f"   마지막 업데이트: {dates['last_updated']}")

        # ================================================================
        # 7. 중요 필드 NULL 체크
        # ================================================================
        print("\n[7] 중요 필드 NULL 체크:")

        important_fields = [
            'embedding',
            'text',
            'dataset_type',
            'document_type',
            'category',
            'article_number'
        ]

        for field in important_fields:
            cursor.execute(f"""
                SELECT COUNT(*) as count
                FROM vector_chunks
                WHERE {field} IS NULL
            """)
            null_count = cursor.fetchone()['count']

            if null_count > 0:
                cursor.execute(f"SELECT COUNT(*) as total FROM vector_chunks")
                total = cursor.fetchone()['total']
                percentage = (null_count / total * 100)
                print(f"      {field:30s}: {null_count:,}개 NULL ({percentage:.1f}%)")

        print("\n" + "=" * 80)
        print("확인 완료")
        print("=" * 80)

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"\n❌ 오류: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="DB 진단 도구 - Quick 모드(빠른 연결 테스트) 또는 Full 모드(상세 스키마 검증)"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full 모드 실행 (상세 스키마 검증)"
    )

    args = parser.parse_args()

    if args.full:
        run_full_diagnostics()
    else:
        run_quick_test()
