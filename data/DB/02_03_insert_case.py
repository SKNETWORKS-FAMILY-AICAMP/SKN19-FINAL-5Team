"""
B_case 데이터 삽입 스크립트
PostgreSQL vector_chunks 테이블에 사례 데이터 삽입

데이터 소스:
- B_case/03_B_embedded/embeddings_semantic_crawling.jsonl (크롤링 데이터)
- B_case/03_B_embedded/embeddings_semantic_pdf.jsonl (PDF 데이터)

총 예상 건수: 37,478개
"""

import json
import psycopg2
from psycopg2.extras import execute_batch, Json
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import re
import os
from dotenv import load_dotenv

# .env 파일 로드 (상위 폴더에서)
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# 데이터 경로 설정
BASE_DIR = Path(__file__).parent.parent
EMBEDDED_DIR = BASE_DIR / "B_case" / "03_B_embedded"

# 임베딩 파일 리스트 (semantic 청킹 버전 사용)
EMBEDDING_FILES = [
    {
        "path": EMBEDDED_DIR / "embeddings_semantic_crawling.jsonl",
        "type": "crawling",
        "description": "크롤링 데이터 (상담/해결/조정)"
    },
    {
        "path": EMBEDDED_DIR / "embeddings_semantic_pdf.jsonl",
        "type": "pdf",
        "description": "PDF 데이터 (해결사례집)"
    }
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
# AWS RDS db.r7g.xlarge: 200-300 권장
BATCH_SIZE = 200


def extract_year_from_metadata(metadata: Dict[str, Any], data_type: str) -> Optional[int]:
    """
    메타데이터에서 연도 추출

    Args:
        metadata: 메타데이터 딕셔너리
        data_type: 데이터 타입 ('crawling' 또는 'pdf')

    Returns:
        연도 (int) 또는 None
    """
    try:
        if data_type == "pdf":
            # PDF의 경우 year 또는 "연도" 필드 사용
            year = metadata.get("year") or metadata.get("연도")
            if year:
                return int(year)

            # source_pdf, source_file, 파일명 등에서 연도 추출
            # - source_pdf: 해결사례집 (예: "2010년 소비자분쟁 해결사례집.pdf")
            # - source_file: 조정사례 (예: "2021년 전자거래 조정사례.json")
            source_file = (
                metadata.get("source_pdf") or
                metadata.get("source_file") or
                metadata.get("파일명") or
                ""
            )
            year_match = re.search(r"(\d{4})년", source_file)
            if year_match:
                return int(year_match.group(1))

        elif data_type == "crawling":
            # 크롤링 데이터는 URL에서 연도 추출 시도
            url = metadata.get("url", "")
            # URL 패턴에서 연도 찾기 (예: /2023/)
            year_match = re.search(r"/(\d{4})/", url)
            if year_match:
                return int(year_match.group(1))

    except (ValueError, AttributeError):
        pass

    return None


def extract_printed_page(metadata: Dict[str, Any]) -> Optional[int]:
    """
    메타데이터에서 인쇄 페이지 번호 추출

    Args:
        metadata: 메타데이터 딕셔너리

    Returns:
        페이지 번호 (int) 또는 None
    """
    try:
        # printed_page_no 필드 확인
        page_no = metadata.get("printed_page_no")
        if page_no:
            return int(page_no)

        # page 필드도 확인
        page = metadata.get("page")
        if page:
            return int(page)

    except (ValueError, TypeError):
        pass

    return None


def extract_source_file(metadata: Dict[str, Any]) -> Optional[str]:
    """
    메타데이터에서 파일명 추출 (경로 제외)

    Args:
        metadata: 메타데이터 딕셔너리

    Returns:
        파일명 (str) 또는 None
    """
    # 해결사례 PDF_1: source_pdf 필드 확인
    source_pdf = metadata.get("source_pdf")
    if source_pdf:
        # 파일명만 추출 (경로 제외)
        return Path(source_pdf).name

    # 조정사례: source 필드 확인
    source = metadata.get("source")
    if source:
        return source

    # 해결사례 PDF_2: 한국어 키 "파일명" 확인
    filename_kr = metadata.get("파일명")
    if filename_kr:
        return filename_kr

    # source_file 필드 확인
    source_file = metadata.get("source_file")
    if source_file:
        return source_file

    return None


def create_text_with_title(content: str, title: Optional[str]) -> str:
    """
    제목과 본문을 결합하여 검색 최적화된 text 생성

    Args:
        content: 본문 내용
        title: 제목 (없을 수 있음)

    Returns:
        "[제목]\n\n[본문]" 형식의 텍스트
    """
    if title and title.strip():
        # 제목이 있는 경우: 제목을 맨 앞에 추가
        return f"{title.strip()}\n\n{content}"
    else:
        # 제목이 없는 경우: 본문만 사용
        return content


def transform_case_chunk(chunk: Dict[str, Any], data_type: str) -> Dict[str, Any]:
    """
    B_case 청크를 vector_chunks 스키마에 맞게 변환

    Args:
        chunk: 원본 청크 데이터
        data_type: 데이터 타입 ('crawling' 또는 'pdf')

    Returns:
        변환된 청크 데이터
    """
    metadata = chunk.get("metadata", {})

    # 데이터 타입에 따른 처리
    if data_type == "crawling":
        source_url = metadata.get("url")
        source_file = None
        printed_page = None
    elif data_type == "pdf":
        source_url = None
        source_file = extract_source_file(metadata)
        printed_page = extract_printed_page(metadata)
    else:
        source_url = None
        source_file = None
        printed_page = None

    # 연도 정보 추출
    source_year = extract_year_from_metadata(metadata, data_type)

    return {
        "chunk_id": chunk["chunk_id"],
        "dataset_type": "case",
        "text": create_text_with_title(chunk["content"], metadata.get("title")),
        "embedding": chunk["embedding"],
        "law_name": None,  # B_case는 law_name 없음
        "chunk_type": "case",
        "category": chunk.get("category"),
        "source_url": source_url,
        "source_file": source_file,
        "printed_page": printed_page,
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
                print(f"[WARNING]  JSON 파싱 에러 ({file_path.name}, line {line_num}): {e}")
                continue

    return chunks


def insert_chunks_batch(
    conn,
    cursor,
    chunks: List[Dict[str, Any]],
    batch_size: int = BATCH_SIZE
) -> tuple:
    """
    청크 배치 삽입 (커서 재생성 지원)

    Args:
        conn: psycopg2 연결 객체
        cursor: psycopg2 커서
        chunks: 삽입할 청크 리스트
        batch_size: 배치 크기

    Returns:
        (삽입된 레코드 수, 새로운 커서)
    """
    insert_query = """
        INSERT INTO vector_chunks (
            chunk_id,
            dataset_type,
            text,
            embedding,
            law_name,
            chunk_type,
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
            source_file = EXCLUDED.source_file,
            source_year = EXCLUDED.source_year,
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

            # 커서가 닫혔는지 확인
            if cursor.closed or conn.closed:
                print(f"  [WARNING] 연결이 끊겼습니다. 재연결 중...")
                try:
                    conn.close()
                except:
                    pass

                # 재연결
                try:
                    conn = psycopg2.connect(**DB_CONFIG)
                    conn.autocommit = False
                    cursor = conn.cursor()
                    print(f"  [OK] 재연결 성공")
                except Exception as reconnect_error:
                    print(f"  [ERROR] 재연결 실패: {reconnect_error}")
                    return inserted_count, cursor

            # 에러 발생 시 개별 삽입 시도
            for chunk in batch:
                try:
                    # 커서가 다시 닫혔는지 재확인
                    if cursor.closed:
                        print(f"  [WARNING] 커서가 닫혔습니다. 건너뜁니다.")
                        break

                    cursor.execute(insert_query, chunk)
                    inserted_count += 1
                except Exception as chunk_error:
                    print(f"    [ERROR] 청크 삽입 실패 (chunk_id: {chunk.get('chunk_id')}): {chunk_error}")

    return inserted_count, cursor


def main():
    """메인 실행 함수"""
    print("=" * 80)
    print("B_case 데이터 삽입 시작")
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
        for file_info in EMBEDDING_FILES:
            file_path = file_info["path"]
            data_type = file_info["type"]
            description = file_info["description"]

            if not file_path.exists():
                print(f"[WARNING]  파일을 찾을 수 없습니다: {file_path}")
                continue

            print(f"[FILE] {file_path.name} 처리 중 ({description})...")

            # JSONL 파일 로드
            raw_chunks = load_jsonl_file(file_path)
            print(f"  [OK] {len(raw_chunks):,}개 청크 로드 완료")

            # 청크 변환
            print(f"  [PROCESS] 청크 변환 중...")
            transformed_chunks = []
            for chunk in raw_chunks:
                try:
                    transformed_chunk = transform_case_chunk(chunk, data_type)
                    transformed_chunks.append(transformed_chunk)
                except Exception as e:
                    print(f"    [WARNING]  청크 변환 에러 (chunk_id: {chunk.get('chunk_id')}): {e}")

            print(f"  [OK] {len(transformed_chunks):,}개 청크 변환 완료")

            # 청크 삽입
            print(f"  [INSERT] 데이터베이스 삽입 중...")
            inserted, cursor = insert_chunks_batch(conn, cursor, transformed_chunks)

            total_chunks += len(raw_chunks)
            total_inserted += inserted

            # 중간 커밋
            try:
                conn.commit()
                print(f"  [OK] {file_path.name} 처리 완료 ({inserted:,}건 삽입)\n")
            except Exception as commit_error:
                print(f"  [ERROR] 커밋 실패: {commit_error}")
                conn.rollback()

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
                COUNT(DISTINCT category) as unique_categories,
                AVG(LENGTH(text))::int as avg_text_length
            FROM vector_chunks
            WHERE dataset_type = 'case'
        """)

        stats = cursor.fetchone()
        print(f"  - 총 청크 수: {stats[0]:,}개")
        print(f"  - 고유 카테고리 수: {stats[1]:,}개")
        print(f"  - 평균 텍스트 길이: {stats[2]:,}자")
        print()

        # 카테고리별 통계
        print("[INFO] 카테고리별 청크 수:")
        cursor.execute("""
            SELECT
                category,
                COUNT(*) as chunk_count
            FROM vector_chunks
            WHERE dataset_type = 'case' AND category IS NOT NULL
            GROUP BY category
            ORDER BY chunk_count DESC
        """)

        for category, count in cursor.fetchall():
            print(f"  - {category}: {count:,}개")
        print()

        # 출처별 통계 (크롤링 vs PDF)
        print("[INFO] 출처별 청크 수:")
        cursor.execute("""
            SELECT
                CASE
                    WHEN source_url IS NOT NULL THEN 'Crawling'
                    WHEN source_file IS NOT NULL THEN 'PDF'
                    ELSE 'Unknown'
                END as source_type,
                COUNT(*) as chunk_count
            FROM vector_chunks
            WHERE dataset_type = 'case'
            GROUP BY source_type
            ORDER BY chunk_count DESC
        """)

        for source_type, count in cursor.fetchall():
            print(f"  - {source_type}: {count:,}개")
        print()

        # PDF 파일별 통계 (상위 10개)
        print("[INFO] PDF 파일별 청크 수 (상위 10개):")
        cursor.execute("""
            SELECT
                source_file,
                COUNT(*) as chunk_count
            FROM vector_chunks
            WHERE dataset_type = 'case' AND source_file IS NOT NULL
            GROUP BY source_file
            ORDER BY chunk_count DESC
            LIMIT 10
        """)

        for source_file, count in cursor.fetchall():
            print(f"  - {source_file}: {count:,}개")
        print()

        # 연도별 통계
        print("[INFO] 연도별 청크 수:")
        cursor.execute("""
            SELECT
                source_year,
                COUNT(*) as chunk_count
            FROM vector_chunks
            WHERE dataset_type = 'case' AND source_year IS NOT NULL
            GROUP BY source_year
            ORDER BY source_year DESC
        """)

        for year, count in cursor.fetchall():
            print(f"  - {year}년: {count:,}개")
        print()

        print("[SUCCESS] B_case 데이터 삽입 완료!")

    except Exception as e:
        print(f"\n[ERROR] 에러 발생: {e}")
        conn.rollback()
        print("  [ROLLBACK]  롤백 완료")

    finally:
        cursor.close()
        conn.close()
        print("\n[INFO] 데이터베이스 연결 종료")


if __name__ == "__main__":
    start_time = datetime.now()
    print(f"[TIME] 시작 시간: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    main()

    end_time = datetime.now()
    elapsed_time = (end_time - start_time).total_seconds()
    print(f"\n[TIME] 종료 시간: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[TIME]  소요 시간: {elapsed_time:.2f}초 ({elapsed_time/60:.2f}분)")
