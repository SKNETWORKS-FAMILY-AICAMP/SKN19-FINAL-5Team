"""
A_law_ED_guide 데이터 삽입 스크립트
PostgreSQL vector_chunks 테이블에 법령 데이터 삽입

데이터 소스:
- A_law_ED_guide/03_A_embedded/embedded_chunks_law_ED.jsonl
- A_law_ED_guide/03_A_embedded/embedded_chunks_guide_1.jsonl
- A_law_ED_guide/03_A_embedded/embedded_chunks_guide_2.jsonl

총 예상 건수: 6,138개
"""

import json
import psycopg2
from psycopg2.extras import execute_batch, Json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import os
from dotenv import load_dotenv

# .env 파일 로드 (상위 폴더에서)
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# 데이터 경로 설정
BASE_DIR = Path(__file__).parent.parent
EMBEDDED_DIR = BASE_DIR / "A_law_ED_guide" / "03_A_embedded"

# 임베딩 파일 리스트
EMBEDDING_FILES = [
    EMBEDDED_DIR / "embedded_chunks_law_ED.jsonl",
    EMBEDDED_DIR / "embedded_chunks_guide_1.jsonl",
    EMBEDDED_DIR / "embedded_chunks_guide_2.jsonl"
]

# PostgreSQL 연결 설정 (환경변수 우선, 없으면 기본값)
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost").strip(),
    "port": int(os.getenv("DB_PORT", "5432").strip()),
    "database": os.getenv("DB_NAME", "ddoksori").strip(),
    "user": os.getenv("DB_USER", "postgres").strip(),
    "password": os.getenv("DB_PASSWORD", "postgres").strip()
}

# 배치 크기 (한 번에 삽입할 레코드 수)
BATCH_SIZE = 500


def extract_year_from_date(date_str: Optional[str]) -> Optional[int]:
    """
    날짜 문자열에서 연도 추출

    Args:
        date_str: 날짜 문자열 (예: "2026-01-01")

    Returns:
        연도 (int) 또는 None
    """
    if not date_str:
        return None

    try:
        # 다양한 날짜 형식 처리
        if isinstance(date_str, str):
            # YYYY-MM-DD 형식
            if "-" in date_str:
                year = date_str.split("-")[0]
                return int(year)
            # YYYYMMDD 형식
            elif len(date_str) >= 4:
                return int(date_str[:4])
    except (ValueError, IndexError):
        pass

    return None


def extract_article_number(chunk: Dict[str, Any]) -> Optional[str]:
    """
    조문번호 추출

    Args:
        chunk: 원본 청크 데이터

    Returns:
        조문번호 (str) 또는 None
    """
    # metadata에서 조문번호 추출
    article_number = chunk.get("조문번호")

    if article_number and isinstance(article_number, str):
        article_number = article_number.strip()
        if article_number:
            return article_number

    return None


def extract_document_type(chunk: Dict[str, Any]) -> Optional[str]:
    """
    문서 유형 추출 (법률, 시행령, 시행규칙, 행정규칙, 별표)

    우선순위:
    1. chunk_id에 '별표' 포함 → 별표
    2. law_name에 '지침' 포함 → 행정규칙
    3. law_name에 '시행령' 포함 → 시행령
    4. law_name에 '시행규칙' 포함 → 시행규칙
    5. 그 외 → 법률

    Args:
        chunk: 원본 청크 데이터

    Returns:
        문서 유형 (str) 또는 None
    """
    chunk_id = chunk.get("chunk_id", "")
    law_name = chunk.get("법령명", "")

    # 1. chunk_id에 '별표' 포함 (최우선)
    if "별표" in chunk_id:
        return "별표"

    # 2. law_name 기반 분류
    if law_name:
        if "지침" in law_name:
            return "행정규칙"
        elif "시행규칙" in law_name:
            return "시행규칙"
        elif "시행령" in law_name:
            return "시행령"
        else:
            return "법률"

    # 3. law_name이 없는 경우 기본값
    return "법률"


def transform_law_guide_chunk(chunk: Dict[str, Any]) -> Dict[str, Any]:
    """
    A_law_ED_guide 청크를 vector_chunks 스키마에 맞게 변환

    Args:
        chunk: 원본 청크 데이터

    Returns:
        변환된 청크 데이터
    """
    # 연도 정보 추출 (시행일에서)
    source_year = extract_year_from_date(chunk.get("시행일"))

    # 문서 유형 추출
    document_type = extract_document_type(chunk)

    # 조문번호 추출
    article_number = extract_article_number(chunk)

    # 메타데이터 구성
    metadata = {
        "법령번호": chunk.get("법령번호"),
        "시행일": chunk.get("시행일"),
        "법령유형": chunk.get("법령유형"),
        "모법": chunk.get("모법"),
        "편": chunk.get("편"),
        "장": chunk.get("장"),
        "절": chunk.get("절"),
        "관": chunk.get("관"),
        "조문번호": chunk.get("조문번호"),
        "조문제목": chunk.get("조문제목"),
        "항번호": chunk.get("항번호"),
        "호번호": chunk.get("호번호"),
        "원문_조문": chunk.get("원문_조문"),
        "hierarchy_path": chunk.get("hierarchy_path"),
        "text_length": chunk.get("text_length"),
        "참조조문": chunk.get("참조조문", []),
        "준용조문": chunk.get("준용조문", []),
        "위임대상": chunk.get("위임대상", []),
        "위임근거": chunk.get("위임근거"),
        "keywords": chunk.get("keywords", []),
        "example_cases": chunk.get("example_cases", []),
        "created_at": chunk.get("metadata", {}).get("created_at")
    }

    # NULL 값 제거 (JSONB에서 불필요한 NULL 제거)
    metadata = {k: v for k, v in metadata.items() if v is not None}

    return {
        "chunk_id": chunk["chunk_id"],
        "dataset_type": "law_guide",
        "text": chunk["text"],
        "embedding": chunk["embedding"],
        "law_name": chunk.get("법령명"),
        "chunk_type": chunk.get("chunk_type"),
        "document_type": document_type,  # 문서 유형 추가
        "article_number": article_number,  # 조문번호 추가
        "category": None,  # A_law_ED_guide는 category 없음
        "source_url": None,  # A_law_ED_guide는 URL 없음
        "source_file": None,  # A_law_ED_guide는 PDF 파일 아님
        "printed_page": None,  # A_law_ED_guide는 페이지 번호 없음
        "source_year": source_year,
        "metadata": Json(metadata)  # Dict를 JSON으로 변환
    }


def load_jsonl_file(file_path: Path) -> List[Dict[str, Any]]:
    """
    JSONL 파일 로드

    Args:
        file_path: JSONL 파일 경로

    Returns:
        청크 리스트
    """
    chunks = []

    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            try:
                chunk = json.loads(line.strip())
                chunks.append(chunk)
            except json.JSONDecodeError as e:
                print(f"[WARNING] JSON 파싱 에러 ({file_path.name}, line {line_num}): {e}")
                continue

    return chunks


def insert_chunks_batch(
    cursor,
    chunks: List[Dict[str, Any]],
    batch_size: int = BATCH_SIZE
) -> int:
    """
    청크 배치 삽입

    Args:
        cursor: psycopg2 커서
        chunks: 삽입할 청크 리스트
        batch_size: 배치 크기

    Returns:
        삽입된 레코드 수
    """
    insert_query = """
        INSERT INTO vector_chunks (
            chunk_id,
            dataset_type,
            text,
            embedding,
            law_name,
            chunk_type,
            document_type,
            article_number,
            category,
            source_url,
            source_file,
            printed_page,
            source_year,
            metadata
        ) VALUES (
            %(chunk_id)s,
            %(dataset_type)s,
            %(text)s,
            %(embedding)s::vector(1536),
            %(law_name)s,
            %(chunk_type)s,
            %(document_type)s,
            %(article_number)s,
            %(category)s,
            %(source_url)s,
            %(source_file)s,
            %(printed_page)s,
            %(source_year)s,
            %(metadata)s::jsonb
        )
        ON CONFLICT (chunk_id) DO UPDATE SET
            text = EXCLUDED.text,
            embedding = EXCLUDED.embedding,
            document_type = EXCLUDED.document_type,
            article_number = EXCLUDED.article_number,
            updated_at = NOW()
    """

    inserted_count = 0

    # 배치 단위로 삽입
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]

        try:
            execute_batch(cursor, insert_query, batch, page_size=batch_size)
            inserted_count += len(batch)
            print(f"  [OK] {inserted_count}/{len(chunks)} 건 삽입 완료")
        except Exception as e:
            print(f"  [ERROR] 배치 삽입 에러 (batch {i//batch_size + 1}): {e}")
            # 에러 발생 시 개별 삽입 시도
            for chunk in batch:
                try:
                    cursor.execute(insert_query, chunk)
                    inserted_count += 1
                except Exception as chunk_error:
                    print(f"    [ERROR] 청크 삽입 실패 (chunk_id: {chunk.get('chunk_id')}): {chunk_error}")

    return inserted_count


def main():
    """메인 실행 함수"""
    print("=" * 80)
    print("A_law_ED_guide 데이터 삽입 시작")
    print("=" * 80)
    print()

    # PostgreSQL 연결
    print("[INFO] 데이터베이스 연결 중...")
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False  # 트랜잭션 모드
        cursor = conn.cursor()
        print("  [OK] 데이터베이스 연결 성공\n")
    except Exception as e:
        print(f"  [ERROR] 데이터베이스 연결 실패: {e}")
        return

    total_inserted = 0
    total_chunks = 0

    try:
        # 각 파일 처리
        for file_path in EMBEDDING_FILES:
            if not file_path.exists():
                print(f"[WARNING] 파일을 찾을 수 없습니다: {file_path}")
                continue

            print(f"[FILE] {file_path.name} 처리 중...")

            # JSONL 파일 로드
            raw_chunks = load_jsonl_file(file_path)
            print(f"  [OK] {len(raw_chunks):,}개 청크 로드 완료")

            # 청크 변환
            print(f"  [PROCESS] 청크 변환 중...")
            transformed_chunks = []
            for chunk in raw_chunks:
                try:
                    transformed_chunk = transform_law_guide_chunk(chunk)
                    transformed_chunks.append(transformed_chunk)
                except Exception as e:
                    print(f"    [WARNING] 청크 변환 에러 (chunk_id: {chunk.get('chunk_id')}): {e}")

            print(f"  [OK] {len(transformed_chunks):,}개 청크 변환 완료")

            # 청크 삽입
            print(f"  [INSERT] 데이터베이스 삽입 중...")
            inserted = insert_chunks_batch(cursor, transformed_chunks)

            total_chunks += len(raw_chunks)
            total_inserted += inserted

            # 중간 커밋
            conn.commit()
            print(f"  [OK] {file_path.name} 처리 완료 ({inserted:,}건 삽입)\n")

        # 최종 통계 출력
        print("=" * 80)
        print("[STATS] 삽입 완료 통계")
        print("=" * 80)
        print(f"총 처리 청크: {total_chunks:,}건")
        print(f"삽입 성공: {total_inserted:,}건")
        print(f"실패: {total_chunks - total_inserted:,}건")
        print()

        # 데이터베이스 통계 확인
        print("[INFO] 데이터베이스 통계 확인...")
        cursor.execute("""
            SELECT
                COUNT(*) as total_chunks,
                COUNT(DISTINCT law_name) as unique_laws,
                COUNT(DISTINCT chunk_type) as unique_chunk_types,
                AVG(LENGTH(text))::int as avg_text_length
            FROM vector_chunks
            WHERE dataset_type = 'law_guide'
        """)

        stats = cursor.fetchone()
        print(f"  - 총 청크 수: {stats[0]:,}개")
        print(f"  - 고유 법령 수: {stats[1]:,}개")
        print(f"  - 청크 타입 수: {stats[2]:,}개")
        print(f"  - 평균 텍스트 길이: {stats[3]:,}자")
        print()

        # 법령별 통계
        print("[INFO] 법령별 청크 수 (상위 10개):")
        cursor.execute("""
            SELECT
                law_name,
                COUNT(*) as chunk_count
            FROM vector_chunks
            WHERE dataset_type = 'law_guide' AND law_name IS NOT NULL
            GROUP BY law_name
            ORDER BY chunk_count DESC
            LIMIT 10
        """)

        for law_name, count in cursor.fetchall():
            print(f"  - {law_name}: {count:,}개")
        print()

        # 청크 타입별 통계
        print("[INFO] 청크 타입별 분포:")
        cursor.execute("""
            SELECT
                chunk_type,
                COUNT(*) as chunk_count
            FROM vector_chunks
            WHERE dataset_type = 'law_guide'
            GROUP BY chunk_type
            ORDER BY chunk_count DESC
        """)

        for chunk_type, count in cursor.fetchall():
            print(f"  - {chunk_type}: {count:,}개")
        print()

        # 문서 유형별 통계
        print("[INFO] 문서 유형별 분포:")
        cursor.execute("""
            SELECT
                document_type,
                COUNT(*) as chunk_count
            FROM vector_chunks
            WHERE dataset_type = 'law_guide'
            GROUP BY document_type
            ORDER BY chunk_count DESC
        """)

        for doc_type, count in cursor.fetchall():
            doc_type_name = doc_type if doc_type else "미분류"
            print(f"  - {doc_type_name}: {count:,}개")
        print()

        # 조문번호 통계
        print("[INFO] 조문번호 통계:")
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(article_number) as with_article
            FROM vector_chunks
            WHERE dataset_type = 'law_guide'
        """)
        article_stats = cursor.fetchone()
        print(f"  - 조문번호 있음: {article_stats[1]:,}개 / {article_stats[0]:,}개")
        print()

        print("[SUCCESS] A_law_ED_guide 데이터 삽입 완료!")

    except Exception as e:
        print(f"\n[ERROR] 에러 발생: {e}")
        conn.rollback()
        print("  [ROLLBACK] 롤백 완료")

    finally:
        cursor.close()
        conn.close()
        print("\n[INFO] 데이터베이스 연결 종료")


if __name__ == "__main__":
    start_time = datetime.now()
    print(f"[START] 시작 시간: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    main()

    end_time = datetime.now()
    elapsed_time = (end_time - start_time).total_seconds()
    print(f"\n[END] 종료 시간: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[TIME] 소요 시간: {elapsed_time:.2f}초 ({elapsed_time/60:.2f}분)")
