import json
from pathlib import Path

# scripts/preprocess/metadata/prune_metadata_116.py
BASE_DIR = Path(__file__).resolve().parents[3]  # -> ism/

IN_PATH = (
    BASE_DIR
    / "data"
    / "trubl_mdat"
    / "processed"
    / "trubl_mdat_cases_116_full.processed.clean.jsonl"
)

OUT_PATH = (
    BASE_DIR
    / "data"
    / "trubl_mdat"
    / "processed"
    / "trubl_mdat_cases_116_full.processed.clean.pruned.jsonl"
)

# ✅ 116 분쟁조정 사례 metadata에서 제거할 키들
DROP_KEYS = {
    "site",
    "source_list",
    "doc_type_std",
    "category_raw",
    "category",
    "taxonomy_version",
}

def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(f"Input not found: {IN_PATH}")

    total = 0
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
            total += 1

    print(f"[OK] {IN_PATH.name} -> {OUT_PATH.name} ({total} lines)")
    print("[Removed counts]")
    for k in sorted(removed_counts):
        print(f"  - {k}: {removed_counts[k]}")

if __name__ == "__main__":
    main()
