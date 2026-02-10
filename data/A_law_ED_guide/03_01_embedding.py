"""
법령 및 가이드 데이터 임베딩 스크립트

OpenAI text-embedding-3-large 모델을 사용하여 청킹된 법령 데이터를 임베딩합니다.
MRL(Matryoshka Representation Learning) 기법으로 차원을 1536으로 축소하여
높은 성능을 유지하면서도 효율적인 벡터 크기를 달성합니다.
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
from tqdm import tqdm
import openai
from openai import OpenAI
import time

# 설정
CHUNKED_DIR = Path(r"C:\Users\Playdata\Desktop\project\05_5th_project\data_n_db\A_law_ED_guide\02_A_chunked")
EMBEDDED_DIR = Path(r"C:\Users\Playdata\Desktop\project\05_5th_project\data_n_db\A_law_ED_guide\03_A_embedded")

# OpenAI 설정
EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSIONS = 1536  # text-embedding-3-small과 동일한 차원 (MRL 적용)
BATCH_SIZE = 100  # API 효율성을 위한 배치 크기
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


def load_jsonl(file_path: Path) -> List[Dict[str, Any]]:
    """JSONL 파일을 읽어 리스트로 반환"""
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data


def save_jsonl(data: List[Dict[str, Any]], file_path: Path) -> None:
    """데이터를 JSONL 파일로 저장"""
    with open(file_path, 'w', encoding='utf-8') as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')


def get_embeddings_batch(texts: List[str], client: OpenAI) -> List[List[float]]:
    """
    텍스트 배치를 임베딩으로 변환 (재시도 로직 포함)

    MRL 기법: dimensions 파라미터를 사용하여 3072차원을 1536차원으로 축소
    이는 모델 학습 시 임베딩이 계층적으로 구성되어 있어 앞부분만 사용해도
    의미를 유지하는 MRL 방식으로 구현됩니다.
    """
    for attempt in range(MAX_RETRIES):
        try:
            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=texts,
                dimensions=EMBEDDING_DIMENSIONS  # MRL 차원 축소
            )
            return [data.embedding for data in response.data]

        except openai.RateLimitError as e:
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY * (2 ** attempt)
                print(f"\nRate limit 도달. {wait_time}초 대기 후 재시도... (시도 {attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait_time)
            else:
                raise e

        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"\n오류 발생: {e}. {RETRY_DELAY}초 대기 후 재시도... (시도 {attempt + 1}/{MAX_RETRIES})")
                time.sleep(RETRY_DELAY)
            else:
                raise e


def embed_chunks(chunks: List[Dict[str, Any]], client: OpenAI) -> List[Dict[str, Any]]:
    """청크 리스트를 배치 단위로 임베딩 처리"""
    embedded_chunks = []

    # 배치 단위로 처리
    for i in tqdm(range(0, len(chunks), BATCH_SIZE), desc="임베딩 진행"):
        batch = chunks[i:i + BATCH_SIZE]
        texts = [chunk['text'] for chunk in batch]

        # 임베딩 생성
        embeddings = get_embeddings_batch(texts, client)

        # 각 청크에 임베딩 추가
        for chunk, embedding in zip(batch, embeddings):
            chunk_with_embedding = chunk.copy()
            chunk_with_embedding['embedding'] = embedding
            chunk_with_embedding['embedding_model'] = EMBEDDING_MODEL
            chunk_with_embedding['embedding_dimensions'] = EMBEDDING_DIMENSIONS
            chunk_with_embedding['embedded_at'] = datetime.now().isoformat()
            embedded_chunks.append(chunk_with_embedding)

    return embedded_chunks


def process_file(input_file: Path, output_file: Path, client: OpenAI) -> Dict[str, Any]:
    """단일 파일을 처리하고 통계 반환"""
    print(f"\n처리 중: {input_file.name}")

    # 청크 로드
    chunks = load_jsonl(input_file)
    print(f"  - 총 청크 수: {len(chunks)}")

    # 임베딩 생성
    start_time = time.time()
    embedded_chunks = embed_chunks(chunks, client)
    elapsed_time = time.time() - start_time

    # 결과 저장
    save_jsonl(embedded_chunks, output_file)
    print(f"  - 저장 완료: {output_file.name}")
    print(f"  - 처리 시간: {elapsed_time:.2f}초")

    # 통계 계산
    total_text_length = sum(len(chunk['text']) for chunk in chunks)
    avg_text_length = total_text_length / len(chunks) if chunks else 0

    return {
        'file_name': input_file.name,
        'output_file': output_file.name,
        'total_chunks': len(chunks),
        'total_text_length': total_text_length,
        'avg_text_length': avg_text_length,
        'processing_time': elapsed_time,
        'chunks_per_second': len(chunks) / elapsed_time if elapsed_time > 0 else 0
    }


def main():
    """메인 실행 함수"""
    print("=" * 80)
    print("법령 및 가이드 데이터 임베딩 프로세스")
    print("=" * 80)
    print(f"모델: {EMBEDDING_MODEL}")
    print(f"차원: {EMBEDDING_DIMENSIONS} (MRL 축소)")
    print(f"배치 크기: {BATCH_SIZE}")
    print("=" * 80)

    # OpenAI 클라이언트 초기화
    client = OpenAI()  # API 키는 환경변수 OPENAI_API_KEY에서 자동으로 로드

    # 출력 디렉토리 확인
    EMBEDDED_DIR.mkdir(parents=True, exist_ok=True)

    # .jsonl 파일만 처리
    jsonl_files = sorted([f for f in CHUNKED_DIR.glob("*.jsonl")])

    if not jsonl_files:
        print("❌ 처리할 JSONL 파일이 없습니다.")
        return

    print(f"\n발견된 파일: {len(jsonl_files)}개")
    for f in jsonl_files:
        print(f"  - {f.name}")

    # 전체 통계
    all_stats = []
    total_start_time = time.time()

    # 각 파일 처리
    for input_file in jsonl_files:
        output_file = EMBEDDED_DIR / f"embedded_{input_file.name}"

        try:
            stats = process_file(input_file, output_file, client)
            all_stats.append(stats)
        except Exception as e:
            print(f"❌ 파일 처리 실패: {input_file.name}")
            print(f"   오류: {e}")
            continue

    total_elapsed_time = time.time() - total_start_time

    # 최종 결과 출력
    print("\n" + "=" * 80)
    print("임베딩 완료!")
    print("=" * 80)

    total_chunks = sum(s['total_chunks'] for s in all_stats)
    total_processing_time = sum(s['processing_time'] for s in all_stats)

    print(f"\n전체 통계:")
    print(f"  - 처리된 파일 수: {len(all_stats)}")
    print(f"  - 총 청크 수: {total_chunks:,}")
    print(f"  - 총 처리 시간: {total_elapsed_time:.2f}초")
    print(f"  - 평균 처리 속도: {total_chunks / total_processing_time:.2f} chunks/sec")

    print(f"\n파일별 상세:")
    for stats in all_stats:
        print(f"\n  [{stats['file_name']}]")
        print(f"    - 청크 수: {stats['total_chunks']:,}")
        print(f"    - 평균 텍스트 길이: {stats['avg_text_length']:.1f}자")
        print(f"    - 처리 시간: {stats['processing_time']:.2f}초")
        print(f"    - 처리 속도: {stats['chunks_per_second']:.2f} chunks/sec")

    # 통계를 JSON으로 저장
    stats_file = EMBEDDED_DIR / "embedding_stats.json"
    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump({
            'embedding_model': EMBEDDING_MODEL,
            'embedding_dimensions': EMBEDDING_DIMENSIONS,
            'batch_size': BATCH_SIZE,
            'total_files': len(all_stats),
            'total_chunks': total_chunks,
            'total_time': total_elapsed_time,
            'files': all_stats,
            'completed_at': datetime.now().isoformat()
        }, f, ensure_ascii=False, indent=2)

    print(f"\n📊 통계 파일 저장: {stats_file}")
    print("\n✅ 모든 임베딩 작업이 완료되었습니다!")


if __name__ == "__main__":
    main()
