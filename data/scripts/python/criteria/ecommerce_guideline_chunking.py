# -*- coding: utf-8 -*-
"""
전자거래 지침(ecommerce_guideline.jsonl) → 의미 보존(큰 덩어리) 청킹 스크립트

요청 반영:
- 665자 같은 짧은 종결 조항 청크는 그대로 둠(마지막 짧은 청크 흡수/병합 금지)
- path_hint는 A안(헤딩 문자열 길이 제한) 적용
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


# =========================
# 사용자 지정 경로
# =========================
INPUT_PATH = r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_jsonl_data\ecommerce_guideline.jsonl"
OUTPUT_PATH = r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_data_chunks\ecommerce_guideline_chunks.jsonl"


# =========================
# 청킹 파라미터 (큰 덩어리 기준)
# =========================
TARGET_MIN = 800
TARGET_MAX = 1600
HARD_MAX = 2400

# 긴 청크를 분할할 때 다음 청크에 가져갈 겹침(overlap) 길이 (문맥 유지용)
OVERLAP_CHARS = 200

# path_hint A안: 헤딩 문자열 최대 길이 제한
PATH_HINT_MAX_LEN = 80


# =========================
# 헤딩(구조) 감지 정규식
# =========================
ROMAN_RE = r"[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+"
HEADING_PATTERNS = [
    rf"^제\s*\d+\s*조",                # 제1조
    rf"^{ROMAN_RE}\s*[\.．]?\s*$",     # Ⅰ
    rf"^{ROMAN_RE}\s*[\.．]\s*",       # Ⅰ.
    r"^\d+\s*[\.．]\s*",              # 1.
    r"^[가-힣]\s*[\.．]\s*",           # 가.
    r"^\(\s*\d+\s*\)\s*",             # (1)
]
HEADING_RE = re.compile("|".join(f"(?:{p})" for p in HEADING_PATTERNS))


def _truncate_heading(s: str, max_len: int = PATH_HINT_MAX_LEN) -> str:
    """A안: path_hint용 헤딩 문자열 길이 제한."""
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def _safe_get_text(rec: Dict[str, Any]) -> str:
    """
    레코드에서 본문 텍스트를 최대한 안전하게 추출.
    - 우선순위: rec["text"] → rec["payload"]["body"] → rec["doc"] 문자열화
    """
    t = rec.get("text")
    if isinstance(t, str) and t.strip():
        return t.strip()

    payload = rec.get("payload")
    if isinstance(payload, dict):
        body = payload.get("body")
        if isinstance(body, str) and body.strip():
            return body.strip()

    doc = rec.get("doc")
    if isinstance(doc, str) and doc.strip():
        return doc.strip()

    return ""


def _detect_heading(line: str) -> Optional[str]:
    s = line.strip()
    if not s:
        return None
    if HEADING_RE.search(s):
        return s
    return None


def _normalize_ws(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_soft(text: str, hard_max: int, overlap: int) -> List[str]:
    """
    HARD_MAX 초과 시 문장/줄바꿈 경계로 자연스럽게 나누는 soft split.
    - 가능한 경계: '\n\n' → '\n' → 마침표/물음표/느낌표 뒤 공백 → 마지막으로 hard cut
    - overlap: 이전 청크 끝 일부를 다음 청크 앞에 붙여 문맥 유지
    """
    t = _normalize_ws(text)
    if len(t) <= hard_max:
        return [t]

    parts: List[str] = []
    cur = t

    sent_boundary = re.compile(r"(?<=[\.!?。])\s+")
    while len(cur) > hard_max:
        window = cur[:hard_max]

        cut = -1
        for sep in ["\n\n", "\n"]:
            cut = window.rfind(sep)
            if cut >= int(hard_max * 0.55):
                cut = cut + len(sep)
                break
        else:
            m = None
            for mm in sent_boundary.finditer(window):
                m = mm
            if m and m.start() >= int(hard_max * 0.55):
                cut = m.start()
            else:
                cut = hard_max

        chunk = _normalize_ws(cur[:cut])
        if chunk:
            parts.append(chunk)

        tail = chunk[-overlap:] if overlap > 0 and len(chunk) > overlap else chunk
        rest = cur[cut:].lstrip()
        if rest:
            cur = _normalize_ws((tail + "\n" + rest).strip())
        else:
            cur = ""

    if cur.strip():
        parts.append(_normalize_ws(cur))

    # overlap으로 인해 마지막이 지나치게 짧아지면 흡수
    if len(parts) >= 2 and len(parts[-1]) < 300:
        parts[-2] = _normalize_ws(parts[-2] + "\n" + parts[-1])
        parts.pop()

    return parts


@dataclass
class Buffer:
    texts: List[str] = field(default_factory=list)
    pages: List[int] = field(default_factory=list)
    element_ids: List[str] = field(default_factory=list)
    path_hint: List[str] = field(default_factory=list)

    def add(self, text: str, page: Optional[int], element_id: Optional[str]):
        if text:
            self.texts.append(text)
        if isinstance(page, int):
            self.pages.append(page)
        if isinstance(element_id, str) and element_id:
            self.element_ids.append(element_id)

    def clear(self):
        self.texts.clear()
        self.pages.clear()
        self.element_ids.clear()

    def merged_text(self) -> str:
        return _normalize_ws("\n".join(self.texts))

    def length(self) -> int:
        return len(self.merged_text())


def _read_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except json.JSONDecodeError as e:
                raise ValueError(f"JSON 파싱 실패: {path} (line {line_no}) -> {e}") from e
            if isinstance(obj, dict):
                yield obj


def _write_jsonl(path: str, rows: List[Dict[str, Any]]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _update_path_stack(path_stack: List[str], heading: str):
    """
    헤딩 스택 갱신 + A안 적용(헤딩 문자열 길이 제한)
    """
    h = _truncate_heading(heading, PATH_HINT_MAX_LEN)

    is_article = bool(re.match(r"^제\s*\d+\s*조", h))
    is_roman = bool(re.match(rf"^{ROMAN_RE}\s*[\.．]?", h))
    is_num = bool(re.match(r"^\d+\s*[\.．]", h))
    is_kor = bool(re.match(r"^[가-힣]\s*[\.．]", h))
    is_paren = bool(re.match(r"^\(\s*\d+\s*\)", h))

    if is_article:
        path_stack[:] = [h]
        return
    if is_roman:
        if path_stack:
            if re.match(r"^제\s*\d+\s*조", path_stack[0]):
                path_stack[:] = [path_stack[0], h]
            else:
                path_stack[:] = [h]
        else:
            path_stack[:] = [h]
        return
    if is_num:
        if len(path_stack) >= 2:
            path_stack[:] = path_stack[:2] + [h]
        else:
            path_stack.append(h)
        return
    if is_kor:
        if len(path_stack) >= 3:
            path_stack[:] = path_stack[:3] + [h]
        else:
            path_stack.append(h)
        return
    if is_paren:
        path_stack.append(h)
        return

    path_stack.append(h)


def chunk_ecommerce_guideline(
    input_path: str,
    output_path: str,
    target_min: int = TARGET_MIN,
    target_max: int = TARGET_MAX,
    hard_max: int = HARD_MAX,
    overlap_chars: int = OVERLAP_CHARS,
):
    records = list(_read_jsonl(input_path))
    if not records:
        raise ValueError("입력 JSONL이 비어있습니다.")

    doc_id = None
    for r in records:
        d = r.get("doc")
        if isinstance(d, str) and d.strip():
            doc_id = d.strip()
            break
    if not doc_id:
        doc_id = os.path.basename(input_path)

    out_rows: List[Dict[str, Any]] = []

    buf = Buffer()
    path_stack: List[str] = []

    def flush_buffer(force: bool = False):
        nonlocal out_rows, buf
        merged = buf.merged_text()
        if not merged:
            buf.clear()
            return

        # 너무 짧고(force 아님) 다음과 합쳐야 할 상황이면 보류
        if not force and len(merged) < target_min:
            return

        chunks = _split_soft(merged, hard_max=hard_max, overlap=overlap_chars)
        for ch in chunks:
            pages_sorted = sorted(set(buf.pages)) if buf.pages else []

            uniq_eids = []
            seen = set()
            for eid in buf.element_ids:
                if eid not in seen:
                    uniq_eids.append(eid)
                    seen.add(eid)
                if len(uniq_eids) >= 50:
                    break

            out_rows.append({
                "source": "ecommerce_guideline",
                "record_type": "chunk",
                "doc": doc_id,
                "loc": {
                    "page": pages_sorted[0] if pages_sorted else None,
                    "pages": pages_sorted if pages_sorted else None,
                    "element_ids": uniq_eids if uniq_eids else None,
                },
                "text": ch,
                "normalize": {
                    "chunking": {
                        "target_min": target_min,
                        "target_max": target_max,
                        "hard_max": hard_max,
                        "overlap_chars": overlap_chars,
                        "heading_first": True,
                        "path_hint_truncate": PATH_HINT_MAX_LEN,
                    }
                },
                "payload": {
                    "path_hint": " > ".join(buf.path_hint) if buf.path_hint else None,
                    "doc_type": "guideline",
                }
            })

        buf.clear()

    for rec in records:
        text = _safe_get_text(rec)
        if not text:
            continue

        loc = rec.get("loc") if isinstance(rec.get("loc"), dict) else {}
        page = loc.get("page")
        element_id = loc.get("element_id")

        first_line = text.strip().split("\n", 1)[0]
        heading = _detect_heading(first_line)
        if heading:
            _update_path_stack(path_stack, heading)
            if buf.length() >= target_min:
                flush_buffer(force=True)

        # path_hint는 스택 그대로(단, 스택에 넣을 때 이미 truncate 적용됨)
        buf.path_hint = list(path_stack)

        buf.add(
            text=text,
            page=page if isinstance(page, int) else None,
            element_id=element_id if isinstance(element_id, str) else None,
        )

        if buf.length() >= target_max:
            flush_buffer(force=True)

    flush_buffer(force=True)

    # ===== 요청 반영 =====
    # 665자 같은 종결 조항 청크를 그대로 두기 위해:
    # - "300자 미만 청크를 앞에 합치는" 후처리를 제거함
    # - 즉, out_rows 그대로 저장
    # ====================

    _write_jsonl(output_path, out_rows)

    print(f"[OK] input records : {len(records)}")
    print(f"[OK] output chunks : {len(out_rows)}")
    print(f"[OK] saved to      : {output_path}")


if __name__ == "__main__":
    chunk_ecommerce_guideline(
        input_path=INPUT_PATH,
        output_path=OUTPUT_PATH,
        target_min=TARGET_MIN,
        target_max=TARGET_MAX,
        hard_max=HARD_MAX,
        overlap_chars=OVERLAP_CHARS,
    )
