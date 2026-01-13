# scripts/preprocess/chunk/chunk_trubl_mdat_116.py
"""
trubl_mdat (consumer_mediation_case) 데이터셋 청킹 스크립트

청크 타입:
- overview: title + category + summary (유사도 핵심)
- claims: claims를 상단 섹션 기준 분할 (가./나. 또는 당사자 구분 라인)
- reasoning: reasoning를 대문단(가./나./다.) → 소문단((1)(2)) 단위로 분할
- decision: decision (전체)
"""
import json
import re
import sys
from pathlib import Path
from typing import Dict, Any, List

# chunk_utils 모듈 import (같은 디렉토리)
sys.path.insert(0, str(Path(__file__).parent))

BASE_DIR = Path(__file__).resolve().parents[3]  # -> ism/

# 입력/출력 경로
IN_PATH = BASE_DIR / "data" / "trubl_mdat" / "trubl_mdat_cases_116_full.jsonl"
OUT_DIR = BASE_DIR / "data" / "trubl_mdat" / "chunks"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "trubl_mdat_cases_116_chunks.jsonl"

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
    split_reasoning_by_structure,
)

# overlap 문자 수 계산
OVERLAP_CHARS = int(CHUNK_MAX_CHARS * CHUNK_OVERLAP_RATIO)


def build_overview_text(title: str, category: str, summary: str) -> str:
    """overview 청크 텍스트 생성: title + category + summary"""
    parts = []
    if title:
        parts.append(f"제목: {title}")
    if category:
        parts.append(f"분류: {category}")
    if summary:
        parts.append(f"사건개요:\n{summary}")
    return "\n\n".join(parts)


def split_claims_by_sections(claims: str) -> List[str]:
    """
    claims 텍스트를 상단 섹션 기준으로 분할
    - 가./나./다. 같은 마커 기준
    - 또는 "신청인(소비자)", "피신청인(사업자)" 같은 당사자 구분 라인 기준
    """
    if not claims or not claims.strip():
        return []
    
    # 당사자 구분 패턴: "가. 신청인(소비자)", "나. 피신청인(사업자)" 등
    party_pattern = re.compile(
        r"^(가|나|다|라|마|바|사|아|자|차|카|타|파|하)\.\s*(신청인|피신청인|청구인|피청구인)",
        re.M
    )
    
    # 대문단 마커: 가., 나., 다. 등
    major_markers = [
        r"^가\.\s*",
        r"^나\.\s*",
        r"^다\.\s*",
        r"^라\.\s*",
        r"^마\.\s*",
        r"^바\.\s*",
        r"^사\.\s*",
        r"^아\.\s*",
        r"^자\.\s*",
        r"^차\.\s*",
        r"^카\.\s*",
        r"^타\.\s*",
        r"^파\.\s*",
        r"^하\.\s*",
    ]
    
    major_pattern = re.compile("|".join(major_markers), re.M)
    lines = claims.splitlines()
    
    sections = []
    current_section = []
    current_header = None
    
    for line in lines:
        line_stripped = line.strip()
        major_match = major_pattern.match(line_stripped)
        
        if major_match:
            # 이전 섹션 저장
            if current_section:
                sections.append("\n".join(current_section))
            # 새 섹션 시작
            current_header = line_stripped
            current_section = [line]
        else:
            current_section.append(line)
    
    # 마지막 섹션 저장
    if current_section:
        sections.append("\n".join(current_section))
    
    # 섹션이 없으면 전체를 하나로
    if not sections:
        return [claims]
    
    return sections


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
    summary = doc.get("summary", "")
    claims = doc.get("claims", "")
    reasoning = doc.get("reasoning", "")
    decision = doc.get("decision", "")
    content = doc.get("content", "")
    url = doc.get("url", "")
    source = doc.get("source", "")
    views = doc.get("views", "")
    collected_at = doc.get("collected_at", "")
    metadata = doc.get("metadata", {})
    list_meta = doc.get("list_meta", {})
    
    doc_type = metadata.get("doc_type", "consumer_mediation_case")
    dataset = "trubl_mdat"
    
    chunks = []
    chunk_index = 0
    
    # 1. overview 청크: title + category + summary
    overview_text = build_overview_text(title, category, summary)
    if overview_text.strip():
        # kjw 스크립트 방식: 토큰 수와 문자 수 모두 확인
        tokens = estimate_tokens(overview_text)
        chars = len(overview_text)
        
        if tokens <= CHUNK_MAX_TOKENS and chars <= CHUNK_MAX_CHARS:
            # 하나의 청크로 충분
            overview_chunks = [overview_text]
        else:
            # 분할 필요
            overview_chunks = split_text_with_overlap(overview_text, CHUNK_MAX_CHARS, OVERLAP_CHARS)
            overview_chunks = merge_short_chunks(overview_chunks, CHUNK_MIN_CHARS)
        
        for idx, chunk_text in enumerate(overview_chunks):
            chunk_id = f"{doc_id}:overview:{chunk_index:04d}"
            chunk = {
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "chunk_type": "overview",
                "chunk_index": chunk_index,
                "dataset": dataset,
                "doc_type": doc_type,
                "title": title,
                "url": url,
                "source": source,
                "category": category,
                "collected_at": collected_at,
                "views": views,
                "text": chunk_text,
                "metadata": metadata,
                "list_meta": list_meta,
            }
            chunks.append(chunk)
            chunk_index += 1
    
    # 2. claims 청크: claims를 섹션 기준으로 분할
    if claims and claims.strip():
        claims_sections = split_claims_by_sections(claims)
        
        for section_text in claims_sections:
            if not section_text.strip():
                continue
            
            # kjw 스크립트 방식: 토큰 수와 문자 수 모두 확인
            tokens = estimate_tokens(section_text)
            chars = len(section_text)
            
            if tokens <= CHUNK_MAX_TOKENS and chars <= CHUNK_MAX_CHARS:
                # 하나의 청크로 충분
                section_chunks = [section_text]
            else:
                # 분할 필요
                section_chunks = split_text_with_overlap(section_text, CHUNK_MAX_CHARS, OVERLAP_CHARS)
                section_chunks = merge_short_chunks(section_chunks, CHUNK_MIN_CHARS)
            
            for chunk_text in section_chunks:
                chunk_id = f"{doc_id}:claims:{chunk_index:04d}"
                chunk = {
                    "doc_id": doc_id,
                    "chunk_id": chunk_id,
                    "chunk_type": "claims",
                    "chunk_index": chunk_index,
                    "dataset": dataset,
                    "doc_type": doc_type,
                    "title": title,
                    "url": url,
                    "source": source,
                    "category": category,
                    "collected_at": collected_at,
                    "views": views,
                    "text": chunk_text,
                    "metadata": metadata,
                    "list_meta": list_meta,
                }
                chunks.append(chunk)
                chunk_index += 1
    
    # 3. reasoning 청크: 대문단 → 소문단 단위로 분할
    if reasoning and reasoning.strip():
        # 먼저 구조 기반 분할 (대문단 → 소문단)
        reasoning_sections = split_reasoning_by_structure(reasoning)
        
        # 구조 분할 결과가 없으면 전체를 하나로
        if not reasoning_sections:
            reasoning_sections = [reasoning]
        
        for section_text in reasoning_sections:
            if not section_text.strip():
                continue
            
            # kjw 스크립트 방식: 토큰 수와 문자 수 모두 확인
            tokens = estimate_tokens(section_text)
            chars = len(section_text)
            
            if tokens <= CHUNK_MAX_TOKENS and chars <= CHUNK_MAX_CHARS:
                # 하나의 청크로 충분
                section_chunks = [section_text]
            else:
                # 분할 필요
                section_chunks = split_text_with_overlap(section_text, CHUNK_MAX_CHARS, OVERLAP_CHARS)
                section_chunks = merge_short_chunks(section_chunks, CHUNK_MIN_CHARS)
            
            for chunk_text in section_chunks:
                chunk_id = f"{doc_id}:reasoning:{chunk_index:04d}"
                chunk = {
                    "doc_id": doc_id,
                    "chunk_id": chunk_id,
                    "chunk_type": "reasoning",
                    "chunk_index": chunk_index,
                    "dataset": dataset,
                    "doc_type": doc_type,
                    "title": title,
                    "url": url,
                    "source": source,
                    "category": category,
                    "collected_at": collected_at,
                    "views": views,
                    "text": chunk_text,
                    "metadata": metadata,
                    "list_meta": list_meta,
                }
                chunks.append(chunk)
                chunk_index += 1
    
    # 4. decision 청크: decision 전체
    if decision and decision.strip():
        # kjw 스크립트 방식: 토큰 수와 문자 수 모두 확인
        tokens = estimate_tokens(decision)
        chars = len(decision)
        
        if tokens <= CHUNK_MAX_TOKENS and chars <= CHUNK_MAX_CHARS:
            # 하나의 청크로 충분
            decision_chunks = [decision]
        else:
            # 분할 필요
            decision_chunks = split_text_with_overlap(decision, CHUNK_MAX_CHARS, OVERLAP_CHARS)
            decision_chunks = merge_short_chunks(decision_chunks, CHUNK_MIN_CHARS)
        
        for idx, chunk_text in enumerate(decision_chunks):
            chunk_id = f"{doc_id}:decision:{chunk_index:04d}"
            chunk = {
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "chunk_type": "decision",
                "chunk_index": chunk_index,
                "dataset": dataset,
                "doc_type": doc_type,
                "title": title,
                "url": url,
                "source": source,
                "category": category,
                "collected_at": collected_at,
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
