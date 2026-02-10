# -*- coding: utf-8 -*-
"""
크롤링 데이터 임베딩 생성 스크립트 (의미 기반 청킹)
- OpenAI text-embedding-3-large 사용
- Matryoshka 차원 축소 (3072 → 1536)
- 배치 처리 및 에러 핸들링
- PostgreSQL + pgvector 저장 (옵션)
"""

import json
import os
import time
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
import logging

from openai import OpenAI
from tqdm import tqdm
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

# 경로 설정
BASE_DIR = Path(r"C:\Users\Playdata\Desktop\project\05_5th_project\data_n_db\B_case")
INPUT_FILE = BASE_DIR / "02_B_chunked" / "chunks_semantic_crawling.jsonl"
OUTPUT_DIR = BASE_DIR / "03_B_embedded"
OUTPUT_FILE = OUTPUT_DIR / "embeddings_semantic_crawling.jsonl"
CHECKPOINT_FILE = OUTPUT_DIR / "checkpoint_semantic_crawling.json"

# 출력 디렉토리 생성
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 로깅 설정
logging.basicConfig(
    filename=OUTPUT_DIR / 'embedding_semantic_crawling_errors.log',
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# OpenAI 클라이언트 초기화
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 설정
BATCH_SIZE = 100  # 한 번에 처리할 청크 수
DELAY_BETWEEN_BATCHES = 2.0  # 배치 간 대기 시간 (초)
EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSIONS = 1536  # Matryoshka


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)
def create_embedding(text: str) -> List[float]:
    """
    텍스트에 대한 임베딩 생성 (재시도 로직 포함)
    """
    try:
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text,
            dimensions=EMBEDDING_DIMENSIONS,
            encoding_format="float"
        )
        return response.data[0].embedding
    except Exception as e:
        logging.error(f"Embedding creation failed: {e}")
        raise


def create_embeddings_batch(chunks: List[Dict]) -> List[List[float]]:
    """
    여러 청크에 대한 임베딩 일괄 생성
    """
    texts = [chunk['content'] for chunk in chunks]

    try:
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts,
            dimensions=EMBEDDING_DIMENSIONS,
            encoding_format="float"
        )
        return [data.embedding for data in response.data]
    except Exception as e:
        logging.error(f"Batch embedding failed: {e}")
        # 배치 실패 시 개별 처리로 폴백
        print(f"\n  Batch failed, processing individually...")
        embeddings = []
        for chunk in chunks:
            try:
                emb = create_embedding(chunk['content'])
                embeddings.append(emb)
            except Exception as e2:
                logging.error(f"Individual embedding failed for {chunk['chunk_id']}: {e2}")
                # 실패한 경우 제로 벡터 삽입 (나중에 재처리 가능)
                embeddings.append([0.0] * EMBEDDING_DIMENSIONS)
        return embeddings


def load_checkpoint() -> Dict:
    """
    체크포인트 로드
    """
    if CHECKPOINT_FILE.exists():
        with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"last_processed_index": -1, "processed_count": 0}


def save_checkpoint(checkpoint: Dict):
    """
    체크포인트 저장
    """
    with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)


def load_chunks() -> List[Dict]:
    """
    JSONL 파일에서 청크 로드
    """
    chunks = []
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                chunks.append(json.loads(line))
    return chunks


def save_embedded_chunk(chunk: Dict):
    """
    임베딩이 추가된 청크를 JSONL 파일에 추가
    """
    with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(chunk, ensure_ascii=False) + '\n')


def insert_to_postgres(chunks_with_embeddings: List[Dict]):
    """
    PostgreSQL에 임베딩 데이터 삽입 (옵션)
    """
    try:
        import psycopg2
        from psycopg2.extras import execute_values

        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=os.getenv("POSTGRES_PORT", "5432"),
            database=os.getenv("POSTGRES_DB", "consumer_cases"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD")
        )

        cursor = conn.cursor()

        # 데이터 준비
        data = [
            (
                chunk['chunk_id'],
                chunk['data_source'],
                chunk['category'],
                chunk['original_number'],
                chunk['field_name'],
                chunk['chunk_index'],
                chunk['total_chunks'],
                chunk['content'],
                chunk['embedding'],
                json.dumps(chunk['metadata'])
            )
            for chunk in chunks_with_embeddings
        ]

        # 배치 삽입
        execute_values(
            cursor,
            """
            INSERT INTO consumer_case_chunks
            (chunk_id, data_source, category, original_number, field_name,
             chunk_index, total_chunks, content, embedding, metadata)
            VALUES %s
            ON CONFLICT (chunk_id) DO NOTHING
            """,
            data
        )

        conn.commit()
        cursor.close()
        conn.close()

        return True
    except ImportError:
        print("\n[WARNING] psycopg2 not installed. Skipping PostgreSQL insertion.")
        return False
    except Exception as e:
        logging.error(f"PostgreSQL insertion failed: {e}")
        print(f"\n[WARNING] PostgreSQL insertion failed: {e}")
        return False


def main():
    """
    메인 실행 함수
    """
    print("=" * 80)
    print("크롤링 데이터 임베딩 생성 시작 (의미 기반 청킹)")
    print("=" * 80)

    # 체크포인트 로드
    checkpoint = load_checkpoint()
    start_index = checkpoint['last_processed_index'] + 1

    if start_index > 0:
        print(f"\n[INFO] Resuming from checkpoint: index {start_index}")

    # 청크 로드
    print(f"\n[1/5] 청크 데이터 로딩 중...")
    chunks = load_chunks()
    total_chunks = len(chunks)
    print(f"   -> 총 청크 수: {total_chunks:,}개")

    if start_index >= total_chunks:
        print("\n[INFO] All chunks already processed!")
        return

    # 처리할 청크
    chunks_to_process = chunks[start_index:]
    print(f"   -> 처리할 청크 수: {len(chunks_to_process):,}개")

    # 통계 초기화
    total_batches = (len(chunks_to_process) + BATCH_SIZE - 1) // BATCH_SIZE
    processed_count = checkpoint['processed_count']
    start_time = time.time()
    total_tokens = 0

    print(f"\n[2/5] 임베딩 생성 중...")
    print(f"   -> 배치 크기: {BATCH_SIZE}개")
    print(f"   -> 총 배치 수: {total_batches:,}개")
    print(f"   -> 모델: {EMBEDDING_MODEL}")
    print(f"   -> 차원: {EMBEDDING_DIMENSIONS} (Matryoshka)")

    # 배치 처리
    for i in tqdm(range(0, len(chunks_to_process), BATCH_SIZE), desc="Processing batches"):
        batch = chunks_to_process[i:i+BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1

        try:
            # 임베딩 생성
            embeddings = create_embeddings_batch(batch)

            # 각 청크에 임베딩 추가
            for chunk, embedding in zip(batch, embeddings):
                chunk['embedding'] = embedding

                # JSONL 파일에 저장
                save_embedded_chunk(chunk)

                processed_count += 1

            # 토큰 수 추정 (한글 1자 ≈ 2.5 tokens)
            batch_tokens = sum(len(chunk['content']) * 2.5 for chunk in batch)
            total_tokens += batch_tokens

            # 체크포인트 저장 (10 배치마다)
            if batch_num % 10 == 0:
                save_checkpoint({
                    'last_processed_index': start_index + i + len(batch) - 1,
                    'processed_count': processed_count,
                    'timestamp': datetime.now().isoformat()
                })

            # Rate limit 방지
            time.sleep(DELAY_BETWEEN_BATCHES)

        except Exception as e:
            logging.error(f"Batch {batch_num} failed: {e}")
            print(f"\n[ERROR] Batch {batch_num} failed: {e}")
            # 체크포인트 저장하고 종료
            save_checkpoint({
                'last_processed_index': start_index + i - 1,
                'processed_count': processed_count,
                'timestamp': datetime.now().isoformat()
            })
            print("\n[INFO] Checkpoint saved. You can resume later.")
            return

    # 처리 시간 계산
    elapsed_time = time.time() - start_time
    elapsed_minutes = elapsed_time / 60

    # 최종 체크포인트 저장
    save_checkpoint({
        'last_processed_index': total_chunks - 1,
        'processed_count': processed_count,
        'timestamp': datetime.now().isoformat()
    })

    print("\n" + "=" * 80)
    print("임베딩 생성 완료")
    print("=" * 80)
    print(f"\n총 처리된 청크: {processed_count:,}개")
    print(f"예상 토큰 수: {int(total_tokens):,} tokens")
    print(f"예상 비용: ${total_tokens / 1_000_000 * 0.13:.2f}")
    print(f"처리 시간: {elapsed_minutes:.1f}분")
    print(f"\n출력 파일: {OUTPUT_FILE}")
    print(f"파일 크기: {os.path.getsize(OUTPUT_FILE) / 1024 / 1024:.2f} MB")

    # PostgreSQL 삽입 (옵션)
    print("\n[3/5] PostgreSQL 삽입 시도 중...")
    if os.getenv("POSTGRES_PASSWORD"):
        print("   -> PostgreSQL 설정 감지됨")
        # 파일에서 임베딩된 청크 다시 로드
        embedded_chunks = []
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    embedded_chunks.append(json.loads(line))

        # 배치로 삽입
        batch_size_pg = 1000
        for i in range(0, len(embedded_chunks), batch_size_pg):
            batch = embedded_chunks[i:i+batch_size_pg]
            success = insert_to_postgres(batch)
            if success:
                print(f"   -> Inserted batch {i//batch_size_pg + 1}/{(len(embedded_chunks) + batch_size_pg - 1)//batch_size_pg}")
            else:
                break
    else:
        print("   -> PostgreSQL 설정 없음, 건너뜀")

    # 메타데이터 저장
    print("\n[4/5] 메타데이터 저장 중...")
    metadata = {
        "embedding_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": EMBEDDING_MODEL,
        "dimensions": EMBEDDING_DIMENSIONS,
        "chunking_strategy": "semantic_chunker",
        "data_source": "crawling",
        "total_chunks": processed_count,
        "estimated_tokens": int(total_tokens),
        "estimated_cost_usd": round(total_tokens / 1_000_000 * 0.13, 2),
        "processing_time_seconds": int(elapsed_time),
        "processing_time_minutes": round(elapsed_minutes, 1)
    }

    metadata_file = OUTPUT_DIR / "metadata_semantic_crawling.json"
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"   -> 메타데이터 저장: {metadata_file}")

    print("\n[5/5] 검증 중...")
    # 첫 번째 임베딩 검증
    with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
        first_chunk = json.loads(f.readline())
        embedding = first_chunk['embedding']

        print(f"   -> 임베딩 차원: {len(embedding)}")
        assert len(embedding) == EMBEDDING_DIMENSIONS, "차원 오류!"

        # L2 노름 확인
        import math
        norm = math.sqrt(sum(x**2 for x in embedding))
        print(f"   -> L2 노름: {norm:.4f} (정규화 확인)")

    print("\n" + "=" * 80)
    print("[OK] 크롤링 데이터 임베딩 완료! (의미 기반 청킹)")
    print("=" * 80)

    # 체크포인트 파일 삭제
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        print("\n[INFO] Checkpoint file removed.")


if __name__ == "__main__":
    main()
