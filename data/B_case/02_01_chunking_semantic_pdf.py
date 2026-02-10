# -*- coding: utf-8 -*-
"""
PDF 데이터 의미 기반 청킹 스크립트
- 해결사례, 조정사례: 모두 의미 기반 청킹 (SemanticChunker + text-embedding-3-small)
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
    "해결PDF1": INPUT_DIR / "02_01_SolutionCase" / "kca_p_solution_case_1.json",
    "해결PDF2": INPUT_DIR / "02_01_SolutionCase" / "kca_p_solution_case_2.json",
    "조정PDF1": INPUT_DIR / "02_02_AdjustmentCase" / "kca_p_adjustment_case.json",
    "조정PDF2": INPUT_DIR / "02_02_AdjustmentCase" / "kisa_p_adjustment_case.json",
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
    return f"pdf_semantic_{category}_{safe_number}_{field_name}_{chunk_index}"


def process_solution_pdf_1(data: Dict) -> List[Dict]:
    """해결사례 PDF 1 처리 (의미 기반 청킹)"""
    chunks = []

    if 'cases' not in data:
        return chunks

    for case_idx, case in enumerate(data['cases'], 1):
        source_pdf = case.get('source_pdf', '')
        year = case.get('year', '')

        if 'items' not in case:
            continue

        for item in case['items']:
            item_name = item.get('item_name', '')

            if 'cases' not in item:
                continue

            for sub_case_idx, sub_case in enumerate(item['cases'], 1):
                title = sub_case.get('title', '')
                sections = sub_case.get('sections', {})
                source = sub_case.get('source', {})
                printed_page_no = source.get('printed_page_no', '') if isinstance(source, dict) else ''

                # 청킹 대상 필드
                chunking_fields = {
                    '사건개요': sections.get('사건개요', ''),
                    '쟁점사항': sections.get('쟁점사항', ''),
                    '판단경위': sections.get('판단경위', ''),
                    '처리결과': sections.get('처리결과', '')
                }

                case_number = f"{year}_{case_idx}_{sub_case_idx}"

                for field_name, field_value in chunking_fields.items():
                    if not field_value:
                        continue

                    print(f"    해결PDF1 {case_number} - {field_name} 청킹 중...", end=" ")

                    field_chunks = chunk_text_field_semantic(field_value, field_name)

                    print(f"({len(field_chunks)} 청크)")

                    for chunk_idx, chunk_content in enumerate(field_chunks, 1):
                        chunk = {
                            "chunk_id": create_chunk_id("해결", case_number, field_name, chunk_idx),
                            "data_source": "pdf",
                            "category": "해결",
                            "original_number": case_number,
                            "field_name": field_name,
                            "chunk_index": chunk_idx,
                            "total_chunks": len(field_chunks),
                            "content": chunk_content,
                            "metadata": {
                                "source_pdf": source_pdf,
                                "year": year,
                                "item_name": item_name,
                                "title": title,
                                "printed_page_no": printed_page_no
                            }
                        }
                        chunks.append(chunk)

    return chunks


def process_solution_pdf_2(data: Dict) -> List[Dict]:
    """해결사례 PDF 2 처리 (의미 기반 청킹)"""
    chunks = []

    if 'cases' not in data:
        return chunks

    for case_idx, case in enumerate(data['cases'], 1):
        연도 = case.get('연도', '')
        파일명 = case.get('파일명', '')

        if '사례' not in case:
            continue

        for sub_case in case['사례']:
            번호 = sub_case.get('번호', '')
            제목 = sub_case.get('제목', '')

            # 청킹 대상 필드
            chunking_fields = {
                '신청_내용': sub_case.get('신청 내용', ''),
                '처리_과정': sub_case.get('처리 과정', ''),
                '처리_결과': sub_case.get('처리 결과', '')
            }

            case_number = f"{연도}_{번호}"

            for field_name, field_value in chunking_fields.items():
                if not field_value:
                    continue

                print(f"    해결PDF2 {case_number} - {field_name} 청킹 중...", end=" ")

                field_chunks = chunk_text_field_semantic(field_value, field_name)

                print(f"({len(field_chunks)} 청크)")

                for chunk_idx, chunk_content in enumerate(field_chunks, 1):
                    chunk = {
                        "chunk_id": create_chunk_id("해결", case_number, field_name, chunk_idx),
                        "data_source": "pdf",
                        "category": "해결",
                        "original_number": case_number,
                        "field_name": field_name,
                        "chunk_index": chunk_idx,
                        "total_chunks": len(field_chunks),
                        "content": chunk_content,
                        "metadata": {
                            "연도": 연도,
                            "파일명": 파일명,
                            "번호": str(번호),
                            "제목": 제목
                        }
                    }
                    chunks.append(chunk)

    return chunks


def process_adjustment_pdf_1(data: Dict) -> List[Dict]:
    """조정사례 PDF 1 처리 (의미 기반 청킹)"""
    chunks = []

    if 'cases' not in data:
        return chunks

    for case in data['cases']:
        case_number = case.get('case_number', '')
        title = case.get('title', '')
        case_type = case.get('case_type', '')
        printed_page_number = case.get('printed_page_number', '')
        source = case.get('source', '')

        # 청킹 대상 필드
        chunking_fields = {
            'overview': case.get('overview', ''),
            'judgement_reason': case.get('judgement', {}).get('reason', '') if isinstance(case.get('judgement'), dict) else '',
            'judgement_order': case.get('judgement', {}).get('order', '') if isinstance(case.get('judgement'), dict) else ''
        }

        for field_name, field_value in chunking_fields.items():
            if not field_value:
                continue

            print(f"    조정PDF1 {case_number} - {field_name} 청킹 중...", end=" ")

            field_chunks = chunk_text_field_semantic(field_value, field_name)

            print(f"({len(field_chunks)} 청크)")

            for chunk_idx, chunk_content in enumerate(field_chunks, 1):
                chunk = {
                    "chunk_id": create_chunk_id("조정", case_number, field_name, chunk_idx),
                    "data_source": "pdf",
                    "category": "조정",
                    "original_number": case_number,
                    "field_name": field_name,
                    "chunk_index": chunk_idx,
                    "total_chunks": len(field_chunks),
                    "content": chunk_content,
                    "metadata": {
                        "case_number": case_number,
                        "title": title,
                        "case_type": case_type,
                        "printed_page_number": printed_page_number,
                        "source": source
                    }
                }
                chunks.append(chunk)

    return chunks


def process_adjustment_pdf_2(data: Dict) -> List[Dict]:
    """조정사례 PDF 2 처리 (의미 기반 청킹)"""
    chunks = []

    if 'cases' not in data:
        return chunks

    for case in data['cases']:
        case_number = case.get('case_number', '')
        title = case.get('title', '')
        case_type = case.get('case_type', '')
        printed_page_number = case.get('printed_page_number', '')
        source_file = case.get('source_file', '')

        # claims 처리 (리스트 → 문자열)
        claims = case.get('claims', {})
        claims_applicant = ''
        claims_respondent = ''

        if isinstance(claims, dict):
            applicant_list = claims.get('applicant', [])
            respondent_list = claims.get('respondent', [])

            if isinstance(applicant_list, list):
                claims_applicant = '\n'.join(applicant_list)
            elif isinstance(applicant_list, str):
                claims_applicant = applicant_list

            if isinstance(respondent_list, list):
                claims_respondent = '\n'.join(respondent_list)
            elif isinstance(respondent_list, str):
                claims_respondent = respondent_list

        # judgement 처리
        judgement = case.get('judgement', {})
        judgement_order = ''
        judgement_reason = ''

        if isinstance(judgement, dict):
            judgement_order = judgement.get('order', '')
            judgement_reason = judgement.get('reason', '')

        # 청킹 대상 필드
        chunking_fields = {
            'overview': case.get('overview', ''),
            'claims_applicant': claims_applicant,
            'claims_respondent': claims_respondent,
            'judgement_order': judgement_order,
            'judgement_reason': judgement_reason
        }

        for field_name, field_value in chunking_fields.items():
            if not field_value:
                continue

            print(f"    조정PDF2 {case_number} - {field_name} 청킹 중...", end=" ")

            field_chunks = chunk_text_field_semantic(field_value, field_name)

            print(f"({len(field_chunks)} 청크)")

            for chunk_idx, chunk_content in enumerate(field_chunks, 1):
                chunk = {
                    "chunk_id": create_chunk_id("조정", case_number, field_name, chunk_idx),
                    "data_source": "pdf",
                    "category": "조정",
                    "original_number": case_number,
                    "field_name": field_name,
                    "chunk_index": chunk_idx,
                    "total_chunks": len(field_chunks),
                    "content": chunk_content,
                    "metadata": {
                        "case_number": case_number,
                        "title": title,
                        "case_type": case_type,
                        "printed_page_number": printed_page_number,
                        "source_file": source_file
                    }
                }
                chunks.append(chunk)

    return chunks


def main():
    """메인 실행 함수"""
    print("=" * 80)
    print("PDF 데이터 의미 기반 청킹 시작")
    print("모델: text-embedding-3-small (의미 기반)")
    print("=" * 80)

    all_chunks = []
    total_original_cases = 0
    stats = {}
    start_time = time.time()

    # 1. 해결사례 PDF 1 처리
    print("\n[1/4] 해결사례 PDF 1 처리 중 (의미 기반 청킹)...")
    with open(FILES["해결PDF1"], 'r', encoding='utf-8') as f:
        data = json.load(f)

    solution1_chunks = process_solution_pdf_1(data)
    all_chunks.extend(solution1_chunks)

    # 원본 개수 계산
    original_count = 0
    if 'cases' in data:
        for case in data['cases']:
            if 'items' in case:
                for item in case['items']:
                    if 'cases' in item:
                        original_count += len(item['cases'])

    stats["해결PDF1"] = {
        "원본": original_count,
        "청크": len(solution1_chunks)
    }
    total_original_cases += original_count
    print(f"   → 원본: {original_count:,}개, 청크: {len(solution1_chunks):,}개")

    # 2. 해결사례 PDF 2 처리
    print("\n[2/4] 해결사례 PDF 2 처리 중 (의미 기반 청킹)...")
    with open(FILES["해결PDF2"], 'r', encoding='utf-8') as f:
        data = json.load(f)

    solution2_chunks = process_solution_pdf_2(data)
    all_chunks.extend(solution2_chunks)

    # 원본 개수 계산
    original_count = 0
    if 'cases' in data:
        for case in data['cases']:
            if '사례' in case:
                original_count += len(case['사례'])

    stats["해결PDF2"] = {
        "원본": original_count,
        "청크": len(solution2_chunks)
    }
    total_original_cases += original_count
    print(f"   → 원본: {original_count:,}개, 청크: {len(solution2_chunks):,}개")

    # 3. 조정사례 PDF 1 처리
    print("\n[3/4] 조정사례 PDF 1 처리 중 (의미 기반 청킹)...")
    with open(FILES["조정PDF1"], 'r', encoding='utf-8') as f:
        data = json.load(f)

    adjustment1_chunks = process_adjustment_pdf_1(data)
    all_chunks.extend(adjustment1_chunks)

    original_count = len(data.get('cases', []))
    stats["조정PDF1"] = {
        "원본": original_count,
        "청크": len(adjustment1_chunks)
    }
    total_original_cases += original_count
    print(f"   → 원본: {original_count:,}개, 청크: {len(adjustment1_chunks):,}개")

    # 4. 조정사례 PDF 2 처리
    print("\n[4/4] 조정사례 PDF 2 처리 중 (의미 기반 청킹)...")
    with open(FILES["조정PDF2"], 'r', encoding='utf-8') as f:
        data = json.load(f)

    adjustment2_chunks = process_adjustment_pdf_2(data)
    all_chunks.extend(adjustment2_chunks)

    original_count = len(data.get('cases', []))
    stats["조정PDF2"] = {
        "원본": original_count,
        "청크": len(adjustment2_chunks)
    }
    total_original_cases += original_count
    print(f"   → 원본: {original_count:,}개, 청크: {len(adjustment2_chunks):,}개")

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

    json_path = OUTPUT_DIR / "chunks_semantic_pdf.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(output_json, f, ensure_ascii=False, indent=2)

    print(f"[OK] JSON 저장 완료: {json_path}")
    print(f"  파일 크기: {os.path.getsize(json_path) / 1024 / 1024:.2f} MB")

    # JSONL 파일 저장
    print("\nJSONL 파일 저장 중...")
    jsonl_path = OUTPUT_DIR / "chunks_semantic_pdf.jsonl"
    with open(jsonl_path, 'w', encoding='utf-8') as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + '\n')

    print(f"[OK] JSONL 저장 완료: {jsonl_path}")
    print(f"  파일 크기: {os.path.getsize(jsonl_path) / 1024 / 1024:.2f} MB")

    # 샘플 출력
    if all_chunks:
        print("\n" + "=" * 80)
        print("샘플 청크 (의미 기반 청킹)")
        print("=" * 80)
        for chunk in all_chunks:
            if chunk['total_chunks'] > 1:
                print(json.dumps(chunk, ensure_ascii=False, indent=2)[:500] + "...")
                break

    print("\n" + "=" * 80)
    print("[OK] PDF 데이터 의미 기반 청킹 완료!")
    print("=" * 80)


if __name__ == "__main__":
    main()
