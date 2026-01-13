# scripts/preprocess/metadata/prune_metadata_kca.py
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]  # -> ism/

IN_PATH = (
    BASE_DIR
    / "data"
    / "kca_00000006"
    / "processed"
    / "kca_00000006_full.processed.clean.jsonl"
)

OUT_PATH = (
    BASE_DIR
    / "data"
    / "kca_00000006"
    / "processed"
    / "kca_00000006_full.processed.clean.fixed.jsonl"
)

# ✅ metadata에서 제거할 키들
DROP_META_KEYS = {
    "site",
    "source_list",
    "doc_type_std",
    "taxonomy_version",
    "category_path",  # top-level에만 두기
}

# ✅ top-level에서 제거할 키들
DROP_TOP_LEVEL_KEYS = {
    "source",  # ❗ 핵심: 보험의료팀 제거
}

DEFAULT_CATEGORY_PATH = ["미분류"]


def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(f"Input not found: {IN_PATH}")

    n = 0
    removed_meta = {k: 0 for k in DROP_META_KEYS}
    removed_top = {k: 0 for k in DROP_TOP_LEVEL_KEYS}
    filled_category = 0

    with IN_PATH.open("r", encoding="utf-8") as fin, OUT_PATH.open("w", encoding="utf-8") as fout:
        for line in fin:
            if not line.strip():
                continue

            obj = json.loads(line)

            # -------------------------
            # 1) top-level category_path 보정
            # -------------------------
            cat = obj.get("category_path")
            if not isinstance(cat, list) or len(cat) == 0:
                obj["category_path"] = DEFAULT_CATEGORY_PATH
                filled_category += 1

            # -------------------------
            # 2) top-level prune
            # -------------------------
            for k in DROP_TOP_LEVEL_KEYS:
                if k in obj:
                    obj.pop(k, None)
                    removed_top[k] += 1

            # -------------------------
            # 3) metadata prune
            # -------------------------
            meta = obj.get("metadata")
            if isinstance(meta, dict):
                for k in DROP_META_KEYS:
                    if k in meta:
                        meta.pop(k, None)
                        removed_meta[k] += 1

            fout.write(json.dumps(obj, ensure_ascii=False) + "\n")
            n += 1

    print(f"[OK] {IN_PATH} -> {OUT_PATH} ({n} lines)")
    print(f"[Filled category_path]: {filled_category}")

    print("[Removed top-level keys]")
    for k, v in removed_top.items():
        print(f"  - {k}: {v}")

    print("[Removed metadata keys]")
    for k, v in removed_meta.items():
        print(f"  - {k}: {v}")


if __name__ == "__main__":
    main()
