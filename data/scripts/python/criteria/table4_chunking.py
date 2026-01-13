import json
import re
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

# =========================
# INPUT / OUTPUT (Windows 고정 경로)
# =========================
TABLE1_CHUNKS_PATH = Path(r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_data_chunks\table1_item_chunks_fixed.jsonl")
TABLE4_CHUNKS_PATH = Path(r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_data_chunks\table4_lifespan_chunks.jsonl")

OUT_PATH = Path(r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_data_chunks\table4_lifespan_chunks_enriched.jsonl")

# =========================
# utils
# =========================
WS_RE = re.compile(r"\s+")
PUNCT_RE = re.compile(r"[^\w가-힣]+")  # 한글/영숫자/_ 외 제거(대부분의 기호 제거)

def norm_spaces(s: str) -> str:
    return WS_RE.sub(" ", (s or "")).strip()

def canon_key(s: str) -> str:
    """
    매칭용 정규화 키:
    - 공백 제거
    - 특수기호 제거(대부분)
    - 한글/영숫자 중심으로 남김
    """
    s = norm_spaces(s)
    s = s.replace(" ", "")
    s = PUNCT_RE.sub("", s)
    return s

def drop_paren(s: str) -> str:
    """
    괄호 내용 제거 버전:
    - "퍼스널 컴퓨터(완성품)" -> "퍼스널 컴퓨터"
    """
    s = norm_spaces(s)
    s = re.sub(r"\([^)]*\)", "", s).strip()
    s = re.sub(r"\[[^\]]*\]", "", s).strip()
    return s

def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)

# =========================
# table1 index builder
# =========================
def build_table1_index(table1_path: Path) -> Dict[str, Dict[str, Any]]:
    """
    table1_item_chunks.jsonl을 읽어서 alias 기반 인덱스 생성.
    key -> table1 metadata(필요 필드만)
    """
    idx: Dict[str, Dict[str, Any]] = {}

    for rec in iter_jsonl(table1_path):
        md = rec.get("metadata") or {}

        category = md.get("category")
        industry = md.get("industry")
        item_group = md.get("item_group")
        division = md.get("division")

        item_name = md.get("item_name") or md.get("item") or md.get("item_name_raw")
        aliases = md.get("aliases") or []
        if item_name:
            aliases = [item_name] + list(aliases)

        # table1에서 우리가 주입할 “대표 분류”
        # - category: "상품(재화)" 등
        # - item_group: table4용으로는 "industry / item_group" 형태가 실전에서 유용
        merged_group = None
        if industry and item_group:
            merged_group = f"{industry} / {item_group}"
        elif industry:
            merged_group = industry
        elif item_group:
            merged_group = item_group

        payload = {
            "table1_category": category,
            "table1_industry": industry,
            "table1_item_group": item_group,
            "table1_division": division,
            "table1_group_merged": merged_group,
            "table1_source_stable_id": rec.get("stable_id"),
        }

        for a in aliases:
            a = norm_spaces(str(a))
            if not a:
                continue

            keys = [
                a,                              # 원문 그대로
                canon_key(a),                   # 기호/공백 제거
                canon_key(drop_paren(a)),       # 괄호 제거 후 canon
            ]

            for k in keys:
                if not k:
                    continue
                # 이미 등록되어 있으면 덮어쓰지 않음(첫 매핑 유지)
                if k not in idx:
                    idx[k] = payload

    return idx

def find_table1_meta(idx: Dict[str, Dict[str, Any]], item: str) -> Optional[Dict[str, Any]]:
    item = norm_spaces(item)
    if not item:
        return None

    keys = [
        item,
        canon_key(item),
        canon_key(drop_paren(item)),
    ]
    for k in keys:
        if k in idx:
            return idx[k]
    return None

# =========================
# main
# =========================
def main():
    if not TABLE1_CHUNKS_PATH.exists():
        raise FileNotFoundError(f"Input not found: {TABLE1_CHUNKS_PATH}")
    if not TABLE4_CHUNKS_PATH.exists():
        raise FileNotFoundError(f"Input not found: {TABLE4_CHUNKS_PATH}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    idx = build_table1_index(TABLE1_CHUNKS_PATH)

    n_in = 0
    n_out = 0
    n_matched = 0
    n_unmatched = 0
    n_already = 0

    with TABLE4_CHUNKS_PATH.open("r", encoding="utf-8") as r, OUT_PATH.open("w", encoding="utf-8") as w:
        for line in r:
            line = line.strip()
            if not line:
                continue
            n_in += 1
            rec = json.loads(line)

            md = rec.get("metadata") or {}
            item = md.get("item")

            # 이미 category/item_group가 채워져 있으면 그대로 두기
            if md.get("category") or md.get("item_group"):
                n_already += 1
                w.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_out += 1
                continue

            t1 = find_table1_meta(idx, item or "")

            if t1:
                # table4 메타 주입 규칙:
                # - category: table1_category
                # - item_group: table1_group_merged (industry/item_group 결합)
                md["category"] = t1.get("table1_category")
                md["item_group"] = t1.get("table1_group_merged")

                # 추적용(나중에 디버깅/검수 편하게)
                md["table1_match"] = {
                    "stable_id": t1.get("table1_source_stable_id"),
                    "industry": t1.get("table1_industry"),
                    "item_group": t1.get("table1_item_group"),
                    "division": t1.get("table1_division"),
                }

                rec["metadata"] = md
                n_matched += 1
            else:
                md["table1_match"] = None
                rec["metadata"] = md
                n_unmatched += 1

            w.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_out += 1

    print("[DONE]")
    print(f"- table4_in_rows        : {n_in}")
    print(f"- table4_out_rows       : {n_out}")
    print(f"- matched_injected      : {n_matched}")
    print(f"- unmatched             : {n_unmatched}")
    print(f"- already_had_category  : {n_already}")
    print(f"[OUT] {OUT_PATH}")

if __name__ == "__main__":
    main()
