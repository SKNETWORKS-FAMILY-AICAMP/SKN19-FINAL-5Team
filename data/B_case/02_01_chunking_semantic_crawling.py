# -*- coding: utf-8 -*-
"""
크롤링 데이터 의미 기반 청킹 스크립트
- 상담사례, 해결사례: 청킹 없이 그대로
- 조정사례: 의미 기반 분할 (SemanticChunker + text-embedding-3-small)
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
import time

from langchain_experimental.text_splitter import SemanticChunker
from langchain_openai import OpenAIEmbeddings

# 환경 변수 로드
from dotenv import load_dotenv
load_dotenv()

# 경로 설정
BASE_DIR = Path(r"C:\Users\Playdata\Desktop\project\05_5th_project\data_n_db\B_case")
INPUT_DIR = BASE_DIR / "01_B_parsed"
OUTPUT_DIR = BASE_DIR / "02_B_chunked"

# 출력 디렉토리 생성
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 입력 파일 경로
FILES = {
    "상담사례": INPUT_DIR / "01_ConsultCase" / "consult_case.json",
    "해결사례1": INPUT_DIR / "02_01_SolutionCase" / "solution_case_1.json",
    "해결사례2": INPUT_DIR / "02_01_SolutionCase" / "solution_case_2.json",
    "조정사례1": INPUT_DIR / "02_02_AdjustmentCase" / "adjustment_case_1.json",
    "조정사례2": INPUT_DIR / "02_02_AdjustmentCase" / "adjustment_case_2.json",
}

# OpenAI 임베딩 설정 (text-embedding-3-small)
try:
    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key=os.getenv("OPENAI_API_KEY"),
        dimensions=1536  # small 모델 기본 차원
    )
    print("[OK] OpenAI Embeddings (text-embedding-3-small) 초기화 완료")
except Exception as e:
    print(f"[ERROR] OpenAI 임베딩 초기화 실패: {e}")
    print("OPENAI_API_KEY를 확인해주세요")
    exit(1)

# SemanticChunker 초기화
try:
    semantic_splitter = SemanticChunker(
        embeddings=embeddings,
        breakpoint_threshold_type="percentile",
        breakpoint_threshold_amount=95
    )
    print("[OK] SemanticChunker 초기화 완료")
except Exception as e:
    print(f"[ERROR] SemanticChunker 초기화 실패: {e}")
    exit(1)


def chunk_text_field_semantic(text: str, field_name: str = "unknown") -> List[str]:
    """텍스트 필드를 의미 기반으로 청킹 (API 호출)"""
    if not text or len(text) <= 500:  # 짧은 텍스트는 청킹 안 함
        return [text] if text else [""]

    try:
        chunks = semantic_splitter.split_text(text)
        return chunks if chunks else [text]
    except Exception as e:
        print(f"    [WARN] {field_name} 청킹 실패 (폴백 사용): {str(e)[:100]}")
        # 실패 시 기본 방식으로 폴백
        return [text]


def create_chunk_id(category: str, number: str, field_name: str, chunk_index: int) -> str:
    """청크 ID 생성"""
    safe_number = str(number).replace("/", "_").replace("\\", "_")
    return f"crawl_semantic_{category}_{safe_number}_{field_name}_{chunk_index}"


def process_consult_case(data: List[Dict]) -> List[Dict]:
    """상담사례 처리 (청킹 없음)"""
    chunks = []

    for idx, case in enumerate(data, 1):
        content = f"질문: {case.get('question', '')}\n\n답변: {case.get('answer', '')}"

        chunk = {
            "chunk_id": create_chunk_id("상담", case.get('number', idx), "full", 1),
            "data_source": "crawling",
            "category": "상담",
            "original_number": case.get('number', str(idx)),
            "field_name": "full",
            "chunk_index": 1,
            "total_chunks": 1,
            "content": content,
            "metadata": {
                "number": case.get('number'),
                "url": case.get('url'),
                "title": case.get('title'),
                "category": case.get('category'),
                "source": case.get('source')
            }
        }
        chunks.append(chunk)

    return chunks


def process_solution_case_1(data: List[Dict]) -> List[Dict]:
    """해결사례1 처리 (청킹 없음)"""
    chunks = []

    for idx, case in enumerate(data, 1):
        content = f"질문: {case.get('question', '')}\n\n답변: {case.get('answer', '')}"

        chunk = {
            "chunk_id": create_chunk_id("해결", case.get('number', idx), "full", 1),
            "data_source": "crawling",
            "category": "해결",
            "original_number": case.get('number', str(idx)),
            "field_name": "full",
            "chunk_index": 1,
            "total_chunks": 1,
            "content": content,
            "metadata": {
                "number": case.get('number'),
                "url": case.get('url'),
                "title": case.get('title'),
                "update_date": case.get('update_date'),
                "source": case.get('source')
            }
        }
        chunks.append(chunk)

    return chunks


def process_solution_case_2(data: List[Dict]) -> List[Dict]:
    """해결사례2 처리 (청킹 없음)"""
    chunks = []

    for idx, case in enumerate(data, 1):
        content = f"질문: {case.get('question', '')}\n\n답변: {case.get('answer', '')}"

        chunk = {
            "chunk_id": create_chunk_id("해결", case.get('number', idx), "full", 1),
            "data_source": "crawling",
            "category": "해결",
            "original_number": case.get('number', str(idx)),
            "field_name": "full",
            "chunk_index": 1,
            "total_chunks": 1,
            "content": content,
            "metadata": {
                "number": case.get('number'),
                "url": case.get('url'),
                "title": case.get('title'),
                "category": case.get('category'),
                "source": case.get('source')
            }
        }
        chunks.append(chunk)

    return chunks


def process_adjustment_case(data: List[Dict], case_type: str) -> List[Dict]:
    """조정사례 처리 (의미 기반 청킹)"""
    chunks = []
    chunking_fields = ['case_summary', 'party_claims', 'judgment', 'decision']

    for idx, case in enumerate(data, 1):
        case_number = case.get('number', str(idx))

        # 각 필드별로 청킹
        for field_name in chunking_fields:
            field_value = case.get(field_name, '')

            if not field_value:
                continue

            print(f"    조정사례 {case_number} - {field_name} 청킹 중...", end=" ")

            # 의미 기반 청킹
            field_chunks = chunk_text_field_semantic(field_value, field_name)

            print(f"({len(field_chunks)} 청크)")

            # 청크 생성
            for chunk_idx, chunk_content in enumerate(field_chunks, 1):
                chunk = {
                    "chunk_id": create_chunk_id("조정", case_number, field_name, chunk_idx),
                    "data_source": "crawling",
                    "category": "조정",
                    "original_number": case_number,
                    "field_name": field_name,
                    "chunk_index": chunk_idx,
                    "total_chunks": len(field_chunks),
                    "content": chunk_content,
                    "metadata": {
                        "number": case.get('number'),
                        "url": case.get('url'),
                        "title": case.get('title'),
                        "update_date": case.get('update_date'),
                        "source": case.get('source'),
                        "category": case.get('category'),
                        "related_laws": case.get('related_laws')
                    }
                }
                chunks.append(chunk)

    return chunks


def main():
    """메인 실행 함수"""
    print("=" * 80)
    print("크롤링 데이터 의미 기반 청킹 시작")
    print("모델: text-embedding-3-small (의미 기반)")
    print("=" * 80)

    all_chunks = []
    total_original_cases = 0
    stats = {}
    start_time = time.time()

    # 1. 상담사례 처리
    print("\n[1/5] 상담사례 처리 중...")
    with open(FILES["상담사례"], 'r', encoding='utf-8') as f:
        data = json.load(f)

    consult_chunks = process_consult_case(data)
    all_chunks.extend(consult_chunks)
    stats["상담사례"] = {
        "원본": len(data),
        "청크": len(consult_chunks)
    }
    total_original_cases += len(data)
    print(f"   → 원본: {len(data):,}개, 청크: {len(consult_chunks):,}개")

    # 2. 해결사례1 처리
    print("\n[2/5] 해결사례1 처리 중...")
    with open(FILES["해결사례1"], 'r', encoding='utf-8') as f:
        data = json.load(f)

    solution1_chunks = process_solution_case_1(data)
    all_chunks.extend(solution1_chunks)
    stats["해결사례1"] = {
        "원본": len(data),
        "청크": len(solution1_chunks)
    }
    total_original_cases += len(data)
    print(f"   → 원본: {len(data):,}개, 청크: {len(solution1_chunks):,}개")

    # 3. 해결사례2 처리
    print("\n[3/5] 해결사례2 처리 중...")
    with open(FILES["해결사례2"], 'r', encoding='utf-8') as f:
        data = json.load(f)

    solution2_chunks = process_solution_case_2(data)
    all_chunks.extend(solution2_chunks)
    stats["해결사례2"] = {
        "원본": len(data),
        "청크": len(solution2_chunks)
    }
    total_original_cases += len(data)
    print(f"   → 원본: {len(data):,}개, 청크: {len(solution2_chunks):,}개")

    # 4. 조정사례1 처리
    print("\n[4/5] 조정사례1 처리 중 (의미 기반 청킹)...")
    with open(FILES["조정사례1"], 'r', encoding='utf-8') as f:
        data = json.load(f)

    adjustment1_chunks = process_adjustment_case(data, "조정1")
    all_chunks.extend(adjustment1_chunks)
    stats["조정사례1"] = {
        "원본": len(data),
        "청크": len(adjustment1_chunks)
    }
    total_original_cases += len(data)
    print(f"   → 원본: {len(data):,}개, 청크: {len(adjustment1_chunks):,}개")

    # 5. 조정사례2 처리
    print("\n[5/5] 조정사례2 처리 중 (의미 기반 청킹)...")
    with open(FILES["조정사례2"], 'r', encoding='utf-8') as f:
        data = json.load(f)

    adjustment2_chunks = process_adjustment_case(data, "조정2")
    all_chunks.extend(adjustment2_chunks)
    stats["조정사례2"] = {
        "원본": len(data),
        "청크": len(adjustment2_chunks)
    }
    total_original_cases += len(data)
    print(f"   → 원본: {len(data):,}개, 청크: {len(adjustment2_chunks):,}개")

    elapsed_time = time.time() - start_time

    # 통계 출력
    print("\n" + "=" * 80)
    print("청킹 완료 통계")
    print("=" * 80)
    print(f"\n총 원본 케이스: {total_original_cases:,}개")
    print(f"총 청크 수: {len(all_chunks):,}개")
    print(f"증가율: {(len(all_chunks) / total_original_cases - 1) * 100:.1f}%")
    print(f"처리 시간: {elapsed_time:.2f}초 ({elapsed_time/60:.2f}분)")

    print("\n카테고리별 상세:")
    for category, stat in stats.items():
        if stat['원본'] > 0:
            print(f"  {category}: {stat['원본']:,}개 → {stat['청크']:,}개 ({stat['청크']/stat['원본']:.2f}배)")

    # JSON 파일 저장
    print("\n" + "=" * 80)
    print("JSON 파일 저장 중...")
    print("=" * 80)

    output_json = {
        "metadata": {
            "total_chunks": len(all_chunks),
            "total_original_cases": total_original_cases,
            "chunking_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "chunking_strategy": "semantic_chunker (text-embedding-3-small)",
            "embedding_model": "text-embedding-3-small",
            "embedding_dimensions": 1536,
            "processing_time_seconds": round(elapsed_time, 2),
            "statistics": stats
        },
        "chunks": all_chunks
    }

    json_path = OUTPUT_DIR / "chunks_semantic_crawling.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(output_json, f, ensure_ascii=False, indent=2)

    print(f"[OK] JSON 저장 완료: {json_path}")
    print(f"  파일 크기: {os.path.getsize(json_path) / 1024 / 1024:.2f} MB")

    # JSONL 파일 저장
    print("\nJSONL 파일 저장 중...")
    jsonl_path = OUTPUT_DIR / "chunks_semantic_crawling.jsonl"
    with open(jsonl_path, 'w', encoding='utf-8') as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + '\n')

    print(f"[OK] JSONL 저장 완료: {jsonl_path}")
    print(f"  파일 크기: {os.path.getsize(jsonl_path) / 1024 / 1024:.2f} MB")

    # 샘플 출력
    print("\n" + "=" * 80)
    print("샘플 청크 (조정사례 의미 기반 청킹)")
    print("=" * 80)
    for chunk in all_chunks:
        if chunk['category'] == '조정' and chunk['total_chunks'] > 1:
            print(json.dumps(chunk, ensure_ascii=False, indent=2)[:500] + "...")
            break

    print("\n" + "=" * 80)
    print("[OK] 크롤링 데이터 의미 기반 청킹 완료!")
    print("=" * 80)


if __name__ == "__main__":
    main()
