# chunk_content_guideline_absolute.py
# - 콘텐츠이용자 보호지침(content_guideline.jsonl) 재청킹 (전자거래 지침과 동일 로직)
# - 이번 버전: content 원문 분량에 맞춰 TARGET 범위를 완화
#   (이전 결과: avg ~1637, max ~2038, 마지막 chunk가 796)
#   => TARGET_MIN=900 / TARGET_MAX=2000 로 조정해서
#      - 조문 전환 시 너무 일찍 끊기지 않게 하고
#      - 마지막 chunk가 지나치게 작게 남는 현상 완화 기대

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ====== 절대 경로 (사용자 환경) ======
INPUT_PATH  = r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_jsonl_data\content_guideline.jsonl"
OUTPUT_PATH = r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_data_chunks\content_guideline_chunks.jsonl"


# ====== 튜닝 파라미터 (content 원문 분량에 맞춰 조정) ======
TARGET_MIN = 900
TARGET_MAX = 2000
HARD_MAX = 2400
PATH_HINT_MAXLEN = 80  # 헤딩 문자열 길이 제한(A안)


# ====== 유틸 ======
def _safe_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    return str(x)


def _norm_ws(s: str) -> str:
    s = _safe_str(s)
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _int_or_none(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        return int(x)
    except Exception:
        return None


def _get_body(rec: Dict[str, Any]) -> str:
    payload = rec.get("payload") or {}
    text = rec.get("text") or {}
    body = payload.get("body")
    if body is None:
        body = text.get("normalized")
    return _norm_ws(body)


def _get_article_key(rec: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    payload = rec.get("payload") or {}
    a_no = payload.get("article_no")
    a_title = payload.get("article_title")
    a_no = _safe_str(a_no).strip() or None
    a_title = _safe_str(a_title).strip() or None
    return a_no, a_title


def _make_path_hint(article_no: Optional[str], article_title: Optional[str], fallback: str) -> str:
    if article_no:
        if article_title:
            hint = f"제{article_no}조 {article_title}"
        else:
            hint = f"제{article_no}조"
    else:
        hint = fallback

    hint = _norm_ws(hint)
    if len(hint) > PATH_HINT_MAXLEN:
        hint = hint[: PATH_HINT_MAXLEN - 1].rstrip() + "…"
    return hint or "본문"


# ====== 청킹 상태 ======
@dataclass
class ChunkState:
    chunk_id: int
    texts: List[str]
    pages: List[int]
    element_ids: List[str]
    article_nos: List[Optional[str]]
    article_titles: List[Optional[str]]

    def char_len(self) -> int:
        joined = "\n\n".join([t for t in self.texts if t])
        return len(joined)

    def is_empty(self) -> bool:
        return self.char_len() == 0

    def can_add(self, add_text: str) -> bool:
        if not add_text:
            return True
        cur = self.char_len()
        sep = 2 if cur > 0 else 0  # "\n\n"
        return (cur + sep + len(add_text)) <= HARD_MAX

    def add(self, rec: Dict[str, Any], text: str) -> None:
        self.texts.append(text)

        loc = rec.get("loc") or {}
        page = _int_or_none(loc.get("page"))
        if page is not None:
            self.pages.append(page)

        eid = _safe_str(loc.get("element_id")).strip()
        if eid:
            self.element_ids.append(eid)

        a_no, a_title = _get_article_key(rec)
        self.article_nos.append(a_no)
        self.article_titles.append(a_title)


def _finalize_chunk(state: ChunkState, template_rec: Dict[str, Any]) -> Dict[str, Any]:
    joined = _norm_ws("\n\n".join([t for t in state.texts if t]))

    page_start = min(state.pages) if state.pages else None
    page_end = max(state.pages) if state.pages else None

    eid_start = state.element_ids[0] if state.element_ids else None
    eid_end = state.element_ids[-1] if state.element_ids else None

    first_no = next((x for x in state.article_nos if x), None)
    first_title = next((x for x in state.article_titles if x), None)
    fallback = joined.split("\n", 1)[0] if joined else "본문"
    path_hint = _make_path_hint(first_no, first_title, fallback)

    out = {
        "source": template_rec.get("source"),
        "record_type": "guideline_big_chunk",
        "doc": template_rec.get("doc"),
        "loc": {
            "page_start": page_start,
            "page_end": page_end,
            "element_id_start": eid_start,
            "element_id_end": eid_end,
        },
        "path_hint": path_hint,
        "text": {
            "normalized": joined,
        },
        "chunk_meta": {
            "chunk_id": state.chunk_id,
            "char_len": len(joined),
            "target_min": TARGET_MIN,
            "target_max": TARGET_MAX,
            "hard_max": HARD_MAX,
            "strategy": "big_chunk_v1",
        },
        "payload": {
            "article_nos": sorted({x for x in state.article_nos if x}) or [],
            "article_titles": sorted({x for x in state.article_titles if x}) or [],
            "elements": [
                {"page": p, "element_id": e}
                for p, e in zip(state.pages, state.element_ids)
            ],
        },
        "normalize": {
            "note": "merged_from_guideline_chunk",
        },
    }
    return out


def _soft_split(text: str, hard_max: int) -> List[str]:
    text = _norm_ws(text)
    if len(text) <= hard_max:
        return [text] if text else []

    parts: List[str] = []
    buf = ""

    for seg in re.split(r"(\n\n|\n| )", text):
        if not seg:
            continue
        if len(buf) + len(seg) > hard_max:
            chunk = _norm_ws(buf)
            if chunk:
                parts.append(chunk)
            buf = seg
        else:
            buf += seg

    tail = _norm_ws(buf)
    if tail:
        parts.append(tail)

    return parts


def chunk_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not records:
        return []

    template_rec = records[0]
    out: List[Dict[str, Any]] = []

    chunk_id = 1
    state = ChunkState(chunk_id=chunk_id, texts=[], pages=[], element_ids=[], article_nos=[], article_titles=[])

    prev_article: Optional[Tuple[Optional[str], Optional[str]]] = None

    for rec in records:
        text = _get_body(rec)
        if not text:
            continue

        cur_article = _get_article_key(rec)
        article_changed = (prev_article is not None and cur_article != prev_article)

        # 조문 전환 + 최소 길이 충족이면 마감
        if article_changed and state.char_len() >= TARGET_MIN:
            out.append(_finalize_chunk(state, template_rec))
            chunk_id += 1
            state = ChunkState(chunk_id=chunk_id, texts=[], pages=[], element_ids=[], article_nos=[], article_titles=[])

        # HARD_MAX 초과 위험이면 마감 후 새 청크
        if not state.can_add(text):
            if not state.is_empty():
                out.append(_finalize_chunk(state, template_rec))
                chunk_id += 1
                state = ChunkState(chunk_id=chunk_id, texts=[], pages=[], element_ids=[], article_nos=[], article_titles=[])

            # 단일 레코드가 HARD_MAX를 넘으면 soft split
            if len(text) > HARD_MAX:
                for part in _soft_split(text, HARD_MAX):
                    state.add(rec, part)
                    out.append(_finalize_chunk(state, template_rec))
                    chunk_id += 1
                    state = ChunkState(chunk_id=chunk_id, texts=[], pages=[], element_ids=[], article_nos=[], article_titles=[])
                prev_article = cur_article
                continue

        # 정상 추가
        state.add(rec, text)
        prev_article = cur_article

        # 적정 상한 도달 시 마감
        if state.char_len() >= TARGET_MAX:
            out.append(_finalize_chunk(state, template_rec))
            chunk_id += 1
            state = ChunkState(chunk_id=chunk_id, texts=[], pages=[], element_ids=[], article_nos=[], article_titles=[])

    # 마지막 청크
    if not state.is_empty():
        out.append(_finalize_chunk(state, template_rec))

    return out


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception as e:
                raise RuntimeError(f"[read_jsonl] JSON parse error at line {i}: {e}")
    return records


def write_jsonl(path: str, records: List[Dict[str, Any]]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main() -> None:
    records = read_jsonl(INPUT_PATH)
    chunked = chunk_records(records)
    write_jsonl(OUTPUT_PATH, chunked)

    in_cnt = len(records)
    out_cnt = len(chunked)
    lens = [len((r.get("text") or {}).get("normalized", "")) for r in chunked]
    total_chars = sum(lens)

    print(f"[OK] input_records={in_cnt}, output_chunks={out_cnt}, total_chars={total_chars}")
    if lens:
        print(f"[LEN] min={min(lens)}, max={max(lens)}, avg={sum(lens)//len(lens)}")
        under_min = sum(1 for x in lens if x < TARGET_MIN)
        over_hard = sum(1 for x in lens if x > HARD_MAX)
        print(f"[CHECK] under_target_min={under_min}, over_hard_max={over_hard}")
    print(f"[OUT] {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
