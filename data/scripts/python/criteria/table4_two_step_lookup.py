import json
import re
from pathlib import Path
from typing import Dict, List, Optional

# =========================
# PATHS (너 폴더 기준)
# =========================
TABLE1_CHUNKS_PATH = Path(r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_data_chunks\table1_item_chunks.jsonl")
TABLE4_CHUNKS_PATH = Path(r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_data_chunks\table4_lifespan_chunks.jsonl")

# 결과(테스트용): table4에 classification만 덧붙여서 저장
OUT_PATH = Path(r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_data_chunks\table4_lifespan_two_step_preview.jsonl")

# =========================
# utils
# =========================
def norm(s: str) -> str:
    # 공백 제거 수준의 "정확 일치" 정규화
    return re.sub(r"\s+", "", (s or "")).strip()

def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)

# =========================
# 1) table1 alias index 만들기
# =========================
def build_table1_alias_index(table1_path: Path) -> Dict[str, dict]:
    index: Dict[str, dict] = {}
    for rec in iter_jsonl(table1_path):
        md = rec.get("metadata") or {}
        aliases = md.get("aliases") or []
        for a in aliases:
            key = norm(a)
            if not key:
                continue
            # 첫 매칭 우선
            if key not in index:
                index[key] = md
    return index

# =========================
# 2) table1에서 분류 조회
# =========================
def lookup_classification(item: str, index: Dict[str, dict]) -> Optional[dict]:
    md = index.get(norm(item))
    if not md:
        return None
    return {
        "category": md.get("category"),
        "industry": md.get("industry"),
        "item_group": md.get("item_group"),
        "division": md.get("division"),
        "table_id": md.get("table_id"),
        "row_index": md.get("row_index"),
    }

# =========================
# main
# =========================
def main():
    if not TABLE1_CHUNKS_PATH.exists():
        raise FileNotFoundError(f"missing: {TABLE1_CHUNKS_PATH}")
    if not TABLE4_CHUNKS_PATH.exists():
        raise FileNotFoundError(f"missing: {TABLE4_CHUNKS_PATH}")

    index = build_table1_alias_index(TABLE1_CHUNKS_PATH)
    print(f"[table1] alias keys = {len(index)}")

    total = 0
    matched = 0
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUT_PATH.open("w", encoding="utf-8") as w:
        for rec in iter_jsonl(TABLE4_CHUNKS_PATH):
            total += 1
            payload = rec.get("payload") or {}
            item = payload.get("item") or ""

            cls = lookup_classification(item, index)
            if cls:
                matched += 1

            # ✅ 원본 table4는 유지하고, preview 필드만 추가
            rec["two_step"] = {
                "item": item,
                "classification": cls,  # 없으면 None
            }

            w.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print("[DONE]")
    print(f"- total   : {total}")
    print(f"- matched : {matched}")
    print(f"- out     : {OUT_PATH}")

if __name__ == "__main__":
    main()
