import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]  # -> ism/

# ====== 설정 ======
KEEP_COLLECTED_AT = True  # 실험만이면 False로 바꿔서 top-level에서도 제거 가능

TARGETS = [
    # 114
    (
        BASE_DIR / "data" / "cnslt" / "processed" / "cnslt_cases_114_full.processed.clean.pruned.jsonl",
        BASE_DIR / "data" / "cnslt" / "processed" / "cnslt_cases_114_full.processed.clean.pruned.norm.jsonl",
    ),
    # 115
    (
        BASE_DIR / "data" / "dmge_rlif" / "processed" / "dmge_rlif_cases_115_full.processed.clean.pruned.jsonl",
        BASE_DIR / "data" / "dmge_rlif" / "processed" / "dmge_rlif_cases_115_full.processed.clean.pruned.norm.jsonl",
    ),
    # 116
    (
        BASE_DIR / "data" / "trubl_mdat" / "processed" / "trubl_mdat_cases_116_full.processed.clean.pruned.jsonl",
        BASE_DIR / "data" / "trubl_mdat" / "processed" / "trubl_mdat_cases_116_full.processed.clean.pruned.norm.jsonl",
    ),
    # KCA
    (
        BASE_DIR / "data" / "kca_00000006" / "processed" / "kca_00000006_full.processed.clean.fixed.jsonl",
        BASE_DIR / "data" / "kca_00000006" / "processed" / "kca_00000006_full.processed.clean.pruned.norm.jsonl",
    ),
]

DROP_META_KEYS = {
    "doc_type",       # ✅ 중복 제거
    "content_hash",   # ✅ top-level로 올릴 거라 metadata에서 제거
    "collected_at",   # ✅ top-level로 올릴 거라 metadata에서 제거
}

def normalize_one(in_path: Path, out_path: Path):
    if not in_path.exists():
        print(f"[SKIP] not found: {in_path}")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)

    n_in = 0
    n_out = 0
    moved_hash = 0
    moved_collected = 0
    removed_meta = {k: 0 for k in DROP_META_KEYS}

    with in_path.open("r", encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            n_in += 1
            obj = json.loads(line)

            meta = obj.get("metadata")
            if not isinstance(meta, dict):
                meta = {}
                obj["metadata"] = meta

            # (A) metadata 중복키 제거 + (B) hash/date 승격 준비
            # content_hash / collected_at을 metadata에만 갖고 있는 경우도 대비
            if "content_hash" not in obj and "content_hash" in meta:
                obj["content_hash"] = meta.get("content_hash")
                moved_hash += 1

            if "collected_at" not in obj and "collected_at" in meta:
                obj["collected_at"] = meta.get("collected_at")
                moved_collected += 1

            # metadata에서 DROP_META_KEYS 제거
            for k in list(DROP_META_KEYS):
                if k in meta:
                    meta.pop(k, None)
                    removed_meta[k] += 1

            # collected_at 정책: 실험용이면 top-level에서도 제거 가능
            if not KEEP_COLLECTED_AT:
                if "collected_at" in obj:
                    obj.pop("collected_at", None)

            # metadata가 비면 깔끔하게 제거(선택)
            if meta == {}:
                obj.pop("metadata", None)

            fout.write(json.dumps(obj, ensure_ascii=False) + "\n")
            n_out += 1

    print(f"[OK] {in_path} -> {out_path} ({n_out} lines)")
    print(f"     moved content_hash to top-level: {moved_hash}")
    print(f"     moved collected_at to top-level : {moved_collected}")
    print("     removed from metadata:")
    for k in sorted(removed_meta.keys()):
        print(f"       - {k}: {removed_meta[k]}")

def main():
    for in_path, out_path in TARGETS:
        normalize_one(in_path, out_path)

if __name__ == "__main__":
    main()
