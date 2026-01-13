import json
from pathlib import Path

# scripts/preprocess/metadata/prune_metadata_114.py
BASE_DIR = Path(__file__).resolve().parents[3]  # -> ism/

IN_PATH = BASE_DIR / "data" / "cnslt" / "processed" / "cnslt_cases_114_full.processed.clean.jsonl"
OUT_PATH = BASE_DIR / "data" / "cnslt" / "processed" / "cnslt_cases_114_full.processed.clean.pruned.jsonl"

# ✅ 114 상담사례 metadata에서 제거할 키들
DROP_KEYS = {
    "site",              # ⬅️ 추가
    "source_list",
    "doc_type_std",
    "category_raw",
    "field",
    "item",
    "taxonomy_version",
}

def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(f"Input not found: {IN_PATH}")

    n = 0
    removed_counts = {k: 0 for k in DROP_KEYS}

    with IN_PATH.open("r", encoding="utf-8") as fin, OUT_PATH.open("w", encoding="utf-8") as fout:
        for line in fin:
            obj = json.loads(line)

            meta = obj.get("metadata")
            if isinstance(meta, dict):
                for k in DROP_KEYS:
                    if k in meta:
                        meta.pop(k, None)
                        removed_counts[k] += 1

            fout.write(json.dumps(obj, ensure_ascii=False) + "\n")
            n += 1

    print(f"[OK] {IN_PATH} -> {OUT_PATH} ({n} lines)")
    print("[Removed counts]")
    for k in sorted(removed_counts.keys()):
        print(f"  - {k}: {removed_counts[k]}")

if __name__ == "__main__":
    main()
