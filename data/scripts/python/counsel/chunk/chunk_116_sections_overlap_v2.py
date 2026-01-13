# scripts/preprocess/chunk/chunk_116_sections_overlap_v2.py
import json
import re
from pathlib import Path
from typing import List, Tuple

BASE_DIR = Path(__file__).resolve().parents[3]  # -> ism/

# -------------------------
# Input / Output
# -------------------------
IN_PRUNED = BASE_DIR / "data" / "trubl_mdat" / "processed" / "trubl_mdat_cases_116_full.processed.clean.pruned.norm.jsonl"
IN_CLEAN  = BASE_DIR / "data" / "trubl_mdat" / "processed" / "trubl_mdat_cases_116_full.processed.clean.jsonl"
IN_PATH = IN_PRUNED if IN_PRUNED.exists() else IN_CLEAN

OUT_DIR = BASE_DIR / "data" / "trubl_mdat" / "chunks"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "trubl_mdat_cases_116_chunks_v2.jsonl"

# -------------------------
# Chunking knobs
# -------------------------
MAX_CHARS = 1800        # 헤더 제외한 body 기준 권장 (너무 길면 검색/비용 불리)
OVERLAP_CHARS = 200     # 인접 청크 문맥 연결용
MIN_CHARS = 250         # 이보다 짧으면 앞 청크에 합침 (문장 잘림/조사 잘림 방지)

# 섹션 헤더 후보(116 본문에서 자주 나오는 구조)
SECTION_HEADINGS = [
    "사건개요",
    "당사자 주장",
    "판단",
    "관련 법규",
    "관련 법규 및 고시",
    "관련 판례",
    "책임 유무",
    "책임 유무 및 범위",
    "책임 범위",
    "결 론",
    "결정사항",
]
SECTION_RE = re.compile(r"^\[(?P<h>" + "|".join(map(re.escape, SECTION_HEADINGS)) + r")\]\s*$", re.M)

def build_header(doc_type: str, title: str, category_path: List[str]) -> str:
    cat = " > ".join(category_path) if category_path else "미분류"
    # 출처는 팀 요구사항(출력에서 숨김) 때문에 여기엔 넣지 않음
    return f"[문서유형] {doc_type}\n[제목] {title}\n[분류] {cat}\n\n"

def split_by_sections(body: str) -> List[Tuple[str, str]]:
    """
    return list of (section_title, section_text_including_heading)
    섹션 헤더가 없으면 전체를 하나로 반환
    """
    lines = body.splitlines()
    hits = []
    for i, line in enumerate(lines):
        m = SECTION_RE.match(line.strip())
        if m:
            hits.append((i, m.group("h")))

    if not hits:
        return [("본문", body.strip())]

    # 섹션 단위로 자르기
    out = []
    for idx, (start_i, h) in enumerate(hits):
        end_i = hits[idx + 1][0] if idx + 1 < len(hits) else len(lines)
        chunk_lines = lines[start_i:end_i]
        text = "\n".join(chunk_lines).strip()
        out.append((h, text))
    return out

def smart_cut(text: str, limit: int) -> int:
    """
    limit 근처에서 자연스럽게 끊을 위치(줄바꿈 우선) 찾기
    """
    if len(text) <= limit:
        return len(text)

    window = text[:limit]
    # 가장 마지막 줄바꿈에서 자르기
    nl = window.rfind("\n")
    if nl >= int(limit * 0.6):
        return nl

    # 그게 너무 앞이면, 문장 끝(마침표/다.) 같은 데서 자르기(간단 버전)
    punct = max(window.rfind(". "), window.rfind("다."), window.rfind("함."))
    if punct >= int(limit * 0.6):
        return punct + 2  # 대충 뒤로 조금

    return limit

def split_with_overlap(text: str, max_chars: int, overlap_chars: int) -> List[str]:
    """
    긴 텍스트를 max_chars로 자르되, overlap_chars 만큼 겹치게 분할
    """
    text = text.strip()
    if not text:
        return []

    parts = []
    start = 0
    n = len(text)

    while start < n:
        end = start + max_chars
        if end >= n:
            parts.append(text[start:].strip())
            break

        cut = start + smart_cut(text[start:], max_chars)
        part = text[start:cut].strip()
        if part:
            parts.append(part)

        # overlap 적용
        start = max(0, cut - overlap_chars)

        # 무한루프 방지: 진전이 없으면 강제로 이동
        if parts and len(parts) > 1 and parts[-1] == parts[-2]:
            start = cut

    # 혹시 완전 중복이 생기면 제거(안전장치)
    dedup = []
    prev = None
    for p in parts:
        if p != prev:
            dedup.append(p)
        prev = p
    return dedup

def merge_short_chunks(chunks: List[str], min_chars: int) -> List[str]:
    """
    너무 짧은 청크는 앞 청크에 합쳐서 "조사 잘림/문장 파편" 방지
    """
    if not chunks:
        return []

    merged = []
    for c in chunks:
        c = c.strip()
        if not c:
            continue

        if len(c) < min_chars and merged:
            merged[-1] = (merged[-1].rstrip() + "\n" + c).strip()
        else:
            merged.append(c)

    # 첫 청크가 너무 짧으면 뒤와 합치기
    if len(merged) >= 2 and len(merged[0]) < min_chars:
        merged[1] = (merged[0].rstrip() + "\n" + merged[1]).strip()
        merged = merged[1:]

    return merged

def extract_body(text_for_embedding: str) -> str:
    """
    text_for_embedding에서 [본문] 이후만 우선 사용.
    없으면 전체 사용.
    """
    if not text_for_embedding:
        return ""
    t = text_for_embedding.strip()

    # [본문] 이후를 우선으로
    marker = "[본문]"
    pos = t.find(marker)
    if pos != -1:
        return t[pos + len(marker):].strip()

    return t

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
            obj = json.loads(line)

            doc_id = obj.get("doc_id")
            title = obj.get("title") or ""
            category_path = obj.get("category_path") or []
            content_hash = obj.get("content_hash")
            collected_at = obj.get("collected_at")
            text_for_embedding = obj.get("text_for_embedding") or ""

            if not doc_id or not text_for_embedding.strip():
                n_skip += 1
                continue

            # doc_type 통일: 116은 top-level을 mediation_case로 고정
            doc_type = "mediation_case"

            # metadata 최소화 + 중복 제거
            meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
            meta = dict(meta)  # copy
            meta.pop("doc_type", None)
            meta.pop("category_path", None)

            # 본문 추출 -> 섹션 단위 -> (너무 길면) overlap 분할
            body = extract_body(text_for_embedding)
            sections = split_by_sections(body)

            # 섹션별 청크 텍스트를 만든 뒤, 길이 기준으로 추가 분할
            header = build_header(doc_type=doc_type, title=title, category_path=category_path)

            all_piece_texts: List[str] = []
            for _, sec_text in sections:
                if not sec_text.strip():
                    continue
                # sec_text 자체가 길면 overlap로 자르기
                pieces = split_with_overlap(sec_text, MAX_CHARS, OVERLAP_CHARS)
                all_piece_texts.extend(pieces)

            # 너무 짧은 조각 합치기
            all_piece_texts = merge_short_chunks(all_piece_texts, MIN_CHARS)

            if not all_piece_texts:
                n_skip += 1
                continue

            total = len(all_piece_texts)
            for idx, piece in enumerate(all_piece_texts):
                chunk_text = header + piece.strip()

                chunk = {
                    "chunk_id": f"{doc_id}::chunk{idx}",
                    "chunk_index": idx,
                    "chunk_total": total,
                    "doc_id": doc_id,
                    "doc_type": doc_type,
                    "title": title,
                    "category_path": category_path,
                    "text": chunk_text,
                    "metadata": {
                        **meta,
                        "content_hash": content_hash,
                        "collected_at": collected_at,
                    },
                }
                fout.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                n_out += 1

    print("================================================================================")
    print(f"[IN ] {IN_PATH}")
    print(f"[OUT] {OUT_PATH}")
    print(f"[STATS] in_docs={n_in} out_chunks={n_out} skipped_docs={n_skip}")
    print("================================================================================")

if __name__ == "__main__":
    main()
