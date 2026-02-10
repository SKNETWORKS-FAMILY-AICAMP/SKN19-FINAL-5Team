"""
Migration: 제목 가중치 적용 (Title Weighting)

목적:
1. tsvector에 가중치 적용 (제목 A=0.6, 본문 B=0.4)
2. case 데이터의 text 필드에 제목 추가
3. 기존 데이터의 tsvector 재생성

실행 방법:
    python migrations/migration_add_title_weighting.py

주의사항:
- 이 마이그레이션은 기존 데이터를 수정합니다
- 실행 전 백업 권장
- 약 5-10분 소요 예상 (37,478개 case 청크)
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import os
from pathlib import Path
import time

# .env 파일 로드
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

DB_CONFIG = {
    "host": os.getenv("DB_HOST").strip(),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME").strip(),
    "user": os.getenv("DB_USER").strip(),
    "password": os.getenv("DB_PASSWORD").strip()
}

BATCH_SIZE = 1000  # 한 번에 업데이트할 레코드 수


def print_section(title: str):
    """섹션 제목 출력"""
    print("\n" + "="*80)
    print(title)
    print("="*80)


def check_current_state(cursor):
    """현재 상태 확인"""
    print_section("1. 현재 상태 확인")

    # case 데이터 중 제목이 text에 포함되지 않은 건수 확인
    cursor.execute("""
        SELECT
            COUNT(*) as total_cases,
            COUNT(CASE
                WHEN metadata->>'title' IS NOT NULL
                     AND text NOT LIKE (metadata->>'title') || '%'
                THEN 1
            END) as cases_without_title_in_text
        FROM vector_chunks
        WHERE dataset_type = 'case'
          AND metadata->>'title' IS NOT NULL
    """)
    result = cursor.fetchone()

    print(f"   총 case 레코드: {result['total_cases']:,}개")
    print(f"   text에 제목 누락: {result['cases_without_title_in_text']:,}개")

    return result['cases_without_title_in_text']


def create_weighted_tsvector_function(cursor):
    """가중치 적용 tsvector 함수 생성"""
    print_section("2. 가중치 적용 tsvector 함수 생성")

    # 기존 트리거 삭제
    cursor.execute("""
        DROP TRIGGER IF EXISTS trigger_update_text_tsv ON vector_chunks;
    """)
    print("   ✅ 기존 트리거 삭제 완료")

    # 기존 함수 삭제
    cursor.execute("""
        DROP FUNCTION IF EXISTS update_text_tsv();
    """)
    print("   ✅ 기존 함수 삭제 완료")

    # 새로운 가중치 적용 함수 생성
    cursor.execute("""
        CREATE OR REPLACE FUNCTION update_text_tsv_with_weights()
        RETURNS TRIGGER AS $$
        DECLARE
            title_text TEXT;
            body_text TEXT;
        BEGIN
            -- 데이터셋 타입에 따라 제목 추출 방식 다르게 처리
            IF NEW.dataset_type = 'law_guide' THEN
                -- law_guide: 첫 줄을 제목으로 간주
                title_text := split_part(NEW.text, E'\n', 1);
                body_text := substring(NEW.text from position(E'\n' in NEW.text) + 1);

            ELSIF NEW.dataset_type = 'case' THEN
                -- case: metadata에서 제목 추출
                title_text := COALESCE(NEW.metadata->>'title', '');
                body_text := NEW.text;

            ELSE
                -- 기타: 제목 없이 본문만
                title_text := '';
                body_text := NEW.text;
            END IF;

            -- 가중치 적용 tsvector 생성
            -- A = 제목 (weight: 0.6)
            -- B = 본문 (weight: 0.4)
            NEW.text_tsv :=
                setweight(to_tsvector('pg_catalog.simple', COALESCE(title_text, '')), 'A') ||
                setweight(to_tsvector('pg_catalog.simple', COALESCE(body_text, '')), 'B');

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    print("   ✅ 가중치 적용 함수 생성 완료")

    # 새로운 트리거 생성
    cursor.execute("""
        CREATE TRIGGER trigger_update_text_tsv
            BEFORE INSERT OR UPDATE OF text, metadata
            ON vector_chunks
            FOR EACH ROW
            EXECUTE FUNCTION update_text_tsv_with_weights();
    """)
    print("   ✅ 새로운 트리거 생성 완료")


def update_case_text_with_titles(cursor, conn):
    """case 데이터의 text 필드에 제목 추가"""
    print_section("3. case 데이터 text 필드에 제목 추가")

    # 업데이트가 필요한 레코드 수 확인
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM vector_chunks
        WHERE dataset_type = 'case'
          AND metadata->>'title' IS NOT NULL
          AND metadata->>'title' != ''
          AND text NOT LIKE (metadata->>'title') || '%'
    """)
    total_count = cursor.fetchone()['count']

    if total_count == 0:
        print("   ℹ️  업데이트가 필요한 레코드가 없습니다.")
        return

    print(f"   업데이트 대상: {total_count:,}개")

    # 배치 단위로 업데이트
    updated_count = 0
    start_time = time.time()

    cursor.execute("""
        SELECT chunk_id, text, metadata->>'title' as title
        FROM vector_chunks
        WHERE dataset_type = 'case'
          AND metadata->>'title' IS NOT NULL
          AND metadata->>'title' != ''
          AND text NOT LIKE (metadata->>'title') || '%'
    """)

    records_to_update = cursor.fetchall()

    for i in range(0, len(records_to_update), BATCH_SIZE):
        batch = records_to_update[i:i + BATCH_SIZE]

        for record in batch:
            title = record['title']
            current_text = record['text']
            new_text = f"{title}\n\n{current_text}"

            cursor.execute("""
                UPDATE vector_chunks
                SET text = %s
                WHERE chunk_id = %s
            """, (new_text, record['chunk_id']))

        updated_count += len(batch)
        conn.commit()

        # 진행 상황 출력
        elapsed = time.time() - start_time
        progress = (updated_count / total_count) * 100
        print(f"   진행: {updated_count:,}/{total_count:,} ({progress:.1f}%) - {elapsed:.1f}초 경과", end='\r')

    print(f"\n   ✅ 업데이트 완료: {updated_count:,}개 ({time.time() - start_time:.1f}초)")


def regenerate_all_tsvectors(cursor, conn):
    """모든 레코드의 tsvector 재생성"""
    print_section("4. 모든 레코드의 tsvector 재생성")

    # 총 레코드 수 확인
    cursor.execute("SELECT COUNT(*) as count FROM vector_chunks")
    total_count = cursor.fetchone()['count']
    print(f"   대상 레코드: {total_count:,}개")

    # 배치 단위로 tsvector 재생성
    # UPDATE를 실행하면 트리거가 자동으로 tsvector를 재생성함
    start_time = time.time()

    cursor.execute("SELECT chunk_id FROM vector_chunks")
    all_chunk_ids = [row['chunk_id'] for row in cursor.fetchall()]

    updated_count = 0
    for i in range(0, len(all_chunk_ids), BATCH_SIZE):
        batch_ids = all_chunk_ids[i:i + BATCH_SIZE]

        # text 필드를 자기 자신으로 업데이트 (트리거 실행용)
        cursor.execute("""
            UPDATE vector_chunks
            SET text = text
            WHERE chunk_id = ANY(%s)
        """, (batch_ids,))

        updated_count += len(batch_ids)
        conn.commit()

        # 진행 상황 출력
        elapsed = time.time() - start_time
        progress = (updated_count / total_count) * 100
        print(f"   진행: {updated_count:,}/{total_count:,} ({progress:.1f}%) - {elapsed:.1f}초 경과", end='\r')

    print(f"\n   ✅ tsvector 재생성 완료: {updated_count:,}개 ({time.time() - start_time:.1f}초)")


def verify_results(cursor):
    """결과 검증"""
    print_section("5. 결과 검증")

    # case 데이터 확인
    cursor.execute("""
        SELECT
            COUNT(*) as total_cases,
            COUNT(CASE
                WHEN metadata->>'title' IS NOT NULL
                     AND text LIKE (metadata->>'title') || '%'
                THEN 1
            END) as cases_with_title_in_text
        FROM vector_chunks
        WHERE dataset_type = 'case'
          AND metadata->>'title' IS NOT NULL
    """)
    result = cursor.fetchone()
    print(f"   case 데이터:")
    print(f"      - 총 레코드: {result['total_cases']:,}개")
    print(f"      - text에 제목 포함: {result['cases_with_title_in_text']:,}개")

    # 샘플 데이터 확인
    print("\n   샘플 데이터 (case, 최대 3개):")
    cursor.execute("""
        SELECT
            substring(metadata->>'title', 1, 50) as title,
            substring(text, 1, 100) as text_preview
        FROM vector_chunks
        WHERE dataset_type = 'case'
          AND metadata->>'title' IS NOT NULL
        LIMIT 3
    """)
    for i, row in enumerate(cursor.fetchall(), 1):
        print(f"      [{i}] 제목: {row['title']}")
        print(f"          본문: {row['text_preview']}...")

    # tsvector 가중치 확인
    print("\n   tsvector 가중치 확인:")
    cursor.execute("""
        SELECT text_tsv
        FROM vector_chunks
        WHERE dataset_type = 'case'
          AND metadata->>'title' IS NOT NULL
        LIMIT 1
    """)
    result = cursor.fetchone()
    if result:
        tsv_str = str(result['text_tsv'])[:200]
        if "'A'" in tsv_str:
            print(f"      ✅ 가중치 'A' 발견 (제목)")
        if "'B'" in tsv_str:
            print(f"      ✅ 가중치 'B' 발견 (본문)")


def main():
    """메인 실행 함수"""
    print_section("제목 가중치 적용 Migration 시작")
    print("주의: 이 작업은 기존 데이터를 수정합니다.")

    try:
        # DB 연결
        print("\n데이터베이스 연결 중...")
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=10)
        conn.autocommit = False  # 트랜잭션 모드
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        print("✅ 연결 성공\n")

        # 1. 현재 상태 확인
        cases_without_title = check_current_state(cursor)

        # 2. 가중치 적용 함수 및 트리거 생성
        create_weighted_tsvector_function(cursor)
        conn.commit()

        # 3. case 데이터 text 필드에 제목 추가
        if cases_without_title > 0:
            update_case_text_with_titles(cursor, conn)
        else:
            print_section("3. case 데이터 text 필드에 제목 추가")
            print("   ℹ️  모든 case 데이터에 이미 제목이 포함되어 있습니다.")

        # 4. 모든 tsvector 재생성
        regenerate_all_tsvectors(cursor, conn)

        # 5. 결과 검증
        verify_results(cursor)

        print_section("Migration 완료")
        print("✅ 모든 작업이 성공적으로 완료되었습니다.")
        print("\n다음 단계:")
        print("1. 검색 API 재시작 (python DB/03_01_search_api.py)")
        print("2. 검색 테스트로 제목 가중치 확인")

        cursor.close()
        conn.close()

    except KeyboardInterrupt:
        print("\n\n❌ 사용자에 의해 취소되었습니다.")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        sys.exit(1)

    except Exception as e:
        print(f"\n\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        sys.exit(1)


if __name__ == "__main__":
    main()
