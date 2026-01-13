import json
import re
from pathlib import Path

# =========================
# INPUT / OUTPUT
# =========================
TABLE4_PATH = Path(
    r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_data_chunks\table4_lifespan_chunks.jsonl"
)

TABLE1_CHUNKS_PATH = Path(
    r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_data_chunks\table1_item_chunks.jsonl"
)

OUT_PATH = Path(
    r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_data_chunks\table4_lifespan_chunks_enriched.jsonl"
)

# =========================
# utils
# =========================
def norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "")).strip()

def iter_jsonl(p: Path):
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)

# =========================
# 1) table1 alias index 생성
# =========================
alias_index = {}

for rec in iter_jsonl(TABLE1_CHUNKS_PATH):
    md = rec.get("metadata") or {}
    aliases = md.get("aliases") or []
    for a in aliases:
        key = norm(a)
        if not key:
            continue
        alias_index.setdefault(key, []).append(md)

print(f"[table1] alias keys: {len(alias_index)}")

# =========================
# 2) table4 enrichment
# =========================
matched = 0
total = 0

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

with OUT_PATH.open("w", encoding="utf-8") as w:
    for rec in iter_jsonl(TABLE4_PATH):
        total += 1
        md = rec.setdefault("metadata", {})

        item = (
            rec.get("payload", {}).get("item")
            or md.get("item")
            or ""
        )

        key = norm(item)

        matches = alias_index.get(key)

        if matches:
            m = matches[0]  # 정확 일치 우선 1개
            md["category"] = m.get("category")
            md["industry"] = m.get("industry")
            md["item_group"] = m.get("item_group")
            md["table1_match"] = {
                "item_name": m.get("item_name"),
                "aliases": m.get("aliases"),
                "table_id": m.get("table_id"),
                "row_index": m.get("row_index"),
            }
            matched += 1
        else:
            md["category"] = None
            md["industry"] = None
            md["item_group"] = None
            md["table1_match"] = None

        w.write(json.dumps(rec, ensure_ascii=False) + "\n")

print("[DONE]")
print(f"- total   : {total}")
print(f"- matched : {matched}")
print(f"- output  : {OUT_PATH}")
