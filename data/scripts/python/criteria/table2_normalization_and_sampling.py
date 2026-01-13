# table2_stage2_extract_laws_v2.py
# Stage2 v2: reference_block.jsonl -> law_candidates_v2.jsonl
# - ref_kind 분리(law / notice / terms)
# - law_map 매칭 전 단계까지 담당

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# --------------------
# 정규식 패턴
# --------------------

QUOTE_PAT = re.compile(r"[「『](.+?)[」』]")

UNQUOTED_LAW_PAT = re.compile(
    r"([가-힣0-9ㆍ·\-\s()]{4,}?(?:법률|법|시행령|시행규칙))"
)

TAIL_NOISE_PAT = re.compile(
    r"\s*(제\s*\d+\s*조(?:의\s*\d+)?"
    r"|제\s*\d+\s*항|제\s*\d+\s*호"
    r"|별표\s*\d+|부칙)\b.*$"
)

BRACKET_META_PAT = re.compile(r"\[[^\]]+\]")

# --------------------
# 키워드 분류 기준
# --------------------

NOTICE_KEYWORDS = ["고시", "훈령", "예규", "지침"]
TERMS_KEYWORDS = ["표준약관", "약관"]

DERIVED_HINTS = {
    "시행령": "시행령",
    "시행규칙": "시행규칙",
}


# --------------------
# 유틸 함수
# --------------------

def classify_ref_kind(name: str) -> str:
    for k in TERMS_KEYWORDS:
        if k in name:
            return "terms"
    for k in NOTICE_KEYWORDS:
        if k in name:
            return "notice"
    return "law"


def canonicalize_law_name(name: str) -> str:
    s = (name or "").strip()
    if not s:
        return ""

    s = s.rstrip(" ,.;:·")
    s = BRACKET_META_PAT.sub("", s).strip()
    s = TAIL_NOISE_PAT.sub("", s).strip()
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+등$", "", s).strip()

    return s


# --------------------
# 핵심 로직
# --------------------

def extract_law_candidates(text: str) -> List[Dict[str, Any]]:
    text = text or ""
    candidates: List[Dict[str, Any]] = []

    quoted_laws: List[str] = []

    # (A) quoted 추출
    for m in QUOTE_PAT.finditer(text):
        raw = (m.group(1) or "").strip()
        if not raw:
            continue

        ref_kind = classify_ref_kind(raw)
        canon = canonicalize_law_name(raw)

        candidates.append({
            "name_raw": raw,
            "name_canonical": canon,
            "ref_kind": ref_kind,
            "source": "quoted",
            "type_hint": None,
            "derived_from": None,
        })

        if ref_kind == "law":
            quoted_laws.append(raw)

    # (B) derived 생성 (law인 base만 허용)
    base = quoted_laws[-1] if quoted_laws else None
    if base:
        for key, hint in DERIVED_HINTS.items():
            if key in text:
                derived = f"{base} {key}"
                candidates.append({
                    "name_raw": derived,
                    "name_canonical": canonicalize_law_name(derived),
                    "ref_kind": "law",
                    "source": "derived",
                    "type_hint": hint,
                    "derived_from": base,
                })

    # (C) unquoted 보조 추출 (law만)
    for m in UNQUOTED_LAW_PAT.finditer(text):
        raw = (m.group(1) or "").strip()
        if not raw:
            continue

        # notice / terms는 unquoted에서 제외
        if classify_ref_kind(raw) != "law":
            continue

        canon = canonicalize_law_name(raw)
        if canon:
            candidates.append({
                "name_raw": raw,
                "name_canonical": canon,
                "ref_kind": "law",
                "source": "unquoted",
                "type_hint": None,
                "derived_from": None,
            })

    # (D) canonical 기준 중복 제거
    uniq: Dict[str, Dict[str, Any]] = {}
    prio = {"quoted": 3, "derived": 2, "unquoted": 1}

    for c in candidates:
        key = c["name_canonical"]
        if not key:
            continue
        if key not in uniq:
            uniq[key] = c
        else:
            if prio[c["source"]] > prio[uniq[key]["source"]]:
                uniq[key] = c

    return list(uniq.values())


def stringify_block(obj: Dict[str, Any]) -> str:
    parts: List[str] = []

    refs_raw = obj.get("refs_raw")
    if isinstance(refs_raw, list):
        for r in refs_raw:
            if isinstance(r, dict):
                for k in ("text", "raw", "line", "value"):
                    v = r.get(k)
                    if isinstance(v, str) and v.strip():
                        parts.append(v.strip())
                        break
            elif isinstance(r, str) and r.strip():
                parts.append(r.strip())

    raw_lines = obj.get("raw_lines")
    if isinstance(raw_lines, list):
        for line in raw_lines:
            if isinstance(line, str) and line.strip():
                parts.append(line.strip())

    for k in ("raw_text", "raw", "text", "body"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())

    seen = set()
    dedup = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            dedup.append(p)

    return "\n".join(dedup).strip()


# --------------------
# 실행부
# --------------------

def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            yield i, json.loads(line)


def main(in_path: str, out_path: str):
    in_file = Path(in_path)
    out_file = Path(out_path)

    if not in_file.exists():
        raise FileNotFoundError(in_file)

    out_file.parent.mkdir(parents=True, exist_ok=True)

    total = 0

    with out_file.open("w", encoding="utf-8") as w:
        for line_no, obj in read_jsonl(in_file):
            total += 1

            ref_id = obj.get("ref_id") or obj.get("id") or f"line:{line_no}"
            page = obj.get("page")

            raw_text = stringify_block(obj)
            candidates = extract_law_candidates(raw_text)

            w.write(json.dumps({
                "ref_id": ref_id,
                "page": page,
                "raw_text": raw_text,
                "candidates": candidates,
            }, ensure_ascii=False) + "\n")

    print(f"[Stage2 v2 완료] rows={total}")
    print(f"- output: {out_file}")


if __name__ == "__main__":
    INPUT_PATH = r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_jsonl_data\consumer_dispute_resolution_criteria_table2_resolutions_reference_block.jsonl"
    OUTPUT_PATH = r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_jsonl_data\consumer_dispute_resolution_criteria_table2_law_candidates_v2.jsonl"

    main(INPUT_PATH, OUTPUT_PATH)
