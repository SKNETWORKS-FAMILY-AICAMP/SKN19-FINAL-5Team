import json
from pathlib import Path

# ===============================
# 설정
# ===============================
BASE_DIR = Path(__file__).resolve().parents[3]  # ism/

IN_PATH = BASE_DIR / "data" / "trubl_mdat" / "processed" / "trubl_mdat_cases_116_full.processed.clean.jsonl"
OUT_PATH = BASE_DIR / "data" / "trubl_mdat" / "processed" / "trubl_mdat_cases_116_full.processed.clean.pruned.jsonl"

# ❌ metadata에서 제거할 category 관련 키들
DROP_META_KEYS = {
    "category_raw",   # 표시용 문자열
    "category",       # category_path[0]과 중복
    "taxonomy_version",
    "doc_type_std",
    "source_list",
    "site",
}

def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(f"Input not found: {IN_PATH}")

    removed_counts = {k: 0 for k in DROP_META_KEYS}
    n = 0

    with IN_PATH.open("r", encoding="utf-8") as fin, OUT_PATH.open("w", encoding="utf-8") as fout:
        for line in fin:
            obj = json.loads(line)

            meta = obj.get("metadata")
            if isinstance(meta, dict):
                for k in DROP_META_KEYS:
                    if k in meta:
                        meta.pop(k, None)
                        removed_counts[k] += 1

            fout.write(json.dumps(obj, ensure_ascii=False) + "\n")
            n += 1

    print(f"[OK] {IN_PATH.name} -> {OUT_PATH.name} ({n} lines)")
    print("[Removed metadata keys]")
    for k, v in removed_counts.items():
        print(f"  - {k}: {v}")

if __name__ == "__main__":
    main()
