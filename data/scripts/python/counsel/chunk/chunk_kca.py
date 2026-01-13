# scripts/preprocess/chunk/chunk_kca.py
"""
kca (consumer_relief_case) 데이터셋 청킹 스크립트

청크 타입:
- problem: title + category + question (유사 사례 검색용)
- solution: title + answer (답변 근거용)
- full (선택): content (표시용, 검색 가중치 낮춤)
"""
import json
import sys
from pathlib import Path
from typing import Dict, Any, List

# chunk_utils 모듈 import (같은 디렉토리)
sys.path.insert(0, str(Path(__file__).parent))

BASE_DIR = Path(__file__).resolve().parents[3]  # -> ism/

# 입력/출력 경로
IN_PATH = BASE_DIR / "data" / "kca_00000006" / "kca_00000006_full.jsonl"
OUT_DIR = BASE_DIR / "data" / "kca_00000006" / "chunks"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "kca_00000006_chunks.jsonl"

# 청킹 파라미터 (kjw 스크립트와 동일)
from chunk_utils import (
    CHUNK_MIN_TOKENS,
    CHUNK_MAX_TOKENS,
    CHUNK_MIN_CHARS,
    CHUNK_MAX_CHARS,
    CHUNK_OVERLAP_RATIO,
    estimate_tokens,
    split_text_with_overlap,
    merge_short_chunks,
)

# overlap 문자 수 계산
OVERLAP_CHARS = int(CHUNK_MAX_CHARS * CHUNK_OVERLAP_RATIO)


def build_problem_text(title: str, category: str, question: str) -> str:
    """problem 청크 텍스트 생성: title + category + question"""
    parts = []
    if title:
        parts.append(f"제목: {title}")
    if category:
        parts.append(f"분류: {category}")
    if question:
        parts.append(f"질문:\n{question}")
    return "\n\n".join(parts)


def build_solution_text(title: str, answer: str) -> str:
    """solution 청크 텍스트 생성: title + answer"""
    parts = []
    if title:
        parts.append(f"제목: {title}")
    if answer:
        parts.append(f"답변:\n{answer}")
    return "\n\n".join(parts)


def chunk_document(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    단일 문서를 청크로 분할
    
    Returns:
        청크 객체 리스트
    """
    doc_id = doc.get("id")
    if not doc_id:
        return []
    
    # 메타데이터 추출
    title = doc.get("title", "")
    category = doc.get("category", "")
    question = doc.get("question", "")
    answer = doc.get("answer", "")
    content = doc.get("content", "")
    url = doc.get("url", "")
    source = doc.get("source", "")
    updated_at = doc.get("updated_at", "")
    views = doc.get("views", "")
    collected_at = doc.get("collected_at", "")
    metadata = doc.get("metadata", {})
    list_meta = doc.get("list_meta", {})
    
    doc_type = metadata.get("doc_type", "consumer_relief_case")
    dataset = "kca"
    
    chunks = []
    chunk_index = 0
    
    # 1. problem 청크: title + category + question
    problem_text = build_problem_text(title, category, question)
    if problem_text.strip():
        # kjw 스크립트 방식: 토큰 수와 문자 수 모두 확인
        tokens = estimate_tokens(problem_text)
        chars = len(problem_text)
        
        if tokens <= CHUNK_MAX_TOKENS and chars <= CHUNK_MAX_CHARS:
            # 하나의 청크로 충분
            problem_chunks = [problem_text]
        else:
            # 분할 필요
            problem_chunks = split_text_with_overlap(problem_text, CHUNK_MAX_CHARS, OVERLAP_CHARS)
            problem_chunks = merge_short_chunks(problem_chunks, CHUNK_MIN_CHARS)
        
        for idx, chunk_text in enumerate(problem_chunks):
            chunk_id = f"{doc_id}:problem:{chunk_index:04d}"
            chunk = {
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "chunk_type": "problem",
                "chunk_index": chunk_index,
                "dataset": dataset,
                "doc_type": doc_type,
                "title": title,
                "url": url,
                "source": source,
                "category": category,
                "collected_at": collected_at,
                "updated_at": updated_at,
                "views": views,
                "text": chunk_text,
                "metadata": metadata,
                "list_meta": list_meta,
            }
            chunks.append(chunk)
            chunk_index += 1
    
    # 2. solution 청크: title + answer
    solution_text = build_solution_text(title, answer)
    if solution_text.strip():
        # kjw 스크립트 방식: 토큰 수와 문자 수 모두 확인
        tokens = estimate_tokens(solution_text)
        chars = len(solution_text)
        
        if tokens <= CHUNK_MAX_TOKENS and chars <= CHUNK_MAX_CHARS:
            # 하나의 청크로 충분
            solution_chunks = [solution_text]
        else:
            # 분할 필요
            solution_chunks = split_text_with_overlap(solution_text, CHUNK_MAX_CHARS, OVERLAP_CHARS)
            solution_chunks = merge_short_chunks(solution_chunks, CHUNK_MIN_CHARS)
        
        for idx, chunk_text in enumerate(solution_chunks):
            chunk_id = f"{doc_id}:solution:{chunk_index:04d}"
            chunk = {
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "chunk_type": "solution",
                "chunk_index": chunk_index,
                "dataset": dataset,
                "doc_type": doc_type,
                "title": title,
                "url": url,
                "source": source,
                "category": category,
                "collected_at": collected_at,
                "updated_at": updated_at,
                "views": views,
                "text": chunk_text,
                "metadata": metadata,
                "list_meta": list_meta,
            }
            chunks.append(chunk)
            chunk_index += 1
    
    # 3. full 청크 (선택): content 전체 (표시용)
    if content.strip():
        # kjw 스크립트 방식: 토큰 수와 문자 수 모두 확인
        tokens = estimate_tokens(content)
        chars = len(content)
        
        if tokens <= CHUNK_MAX_TOKENS and chars <= CHUNK_MAX_CHARS:
            # 하나의 청크로 충분
            full_chunks = [content]
        else:
            # 분할 필요
            full_chunks = split_text_with_overlap(content, CHUNK_MAX_CHARS, OVERLAP_CHARS)
            full_chunks = merge_short_chunks(full_chunks, CHUNK_MIN_CHARS)
        
        for idx, chunk_text in enumerate(full_chunks):
            chunk_id = f"{doc_id}:full:{chunk_index:04d}"
            chunk = {
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "chunk_type": "full",
                "chunk_index": chunk_index,
                "dataset": dataset,
                "doc_type": doc_type,
                "title": title,
                "url": url,
                "source": source,
                "category": category,
                "collected_at": collected_at,
                "updated_at": updated_at,
                "views": views,
                "text": chunk_text,
                "metadata": metadata,
                "list_meta": list_meta,
            }
            chunks.append(chunk)
            chunk_index += 1
    
    return chunks


def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(f"Input not found: {IN_PATH}")
    
    n_in = 0
    n_out = 0
    n_skip = 0
    
    with IN_PATH.open("r", encoding="utf-8") as fin, OUT_PATH.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            
            n_in += 1
            try:
                doc = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"JSON decode error at line {n_in}: {e}")
                n_skip += 1
                continue
            
            chunks = chunk_document(doc)
            
            if not chunks:
                n_skip += 1
                continue
            
            for chunk in chunks:
                fout.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                n_out += 1
    
    print("=" * 80)
    print(f"[IN ] {IN_PATH}")
    print(f"[OUT] {OUT_PATH}")
    print(f"[STATS] in_docs={n_in} out_chunks={n_out} skipped_docs={n_skip}")
    print("=" * 80)


if __name__ == "__main__":
    main()
