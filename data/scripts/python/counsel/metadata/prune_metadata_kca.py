import json
from pathlib import Path

# scripts/preprocess/metadata/prune_metadata_kca.py
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
    / "kca_00000006_full.processed.clean.pruned.jsonl"
)

# ✅ KCA metadata에서 제거할 키들
DROP_KEYS = {
    "site",
    "source_list",
    "doc_type_std",
    "taxonomy_version",
}

def ensure_source_in_text(text: str, source_value: str | None) -> str:
    """
    KCA는 text_for_embedding에 [출처] 라인이 없는 케이스가 있어 보이므로,
    없으면 [출처] 라인을 추가해준다.
    """
    if not isinstance(text, str) or not text.strip():
        return text

    # 이미 있으면 그대로
    if "[출처]" in text:
        return text

    if not source_value:
        # 출처값도 없으면 굳이 추가하지 않음(빈 출처 라인 방지)
        return text

    lines = text.splitlines()

    # [제목] 다음에 [출처] 넣는 게 가장 자연스러움
    out = []
    inserted = False
    for i, line in enumerate(lines):
        out.append(line)
        if (not inserted) and line.startswith("[제목]"):
            out.append(f"[출처] {source_value}")
            inserted = True

    # 혹시 [제목] 자체가 없으면 상단에 붙이기
    if not inserted:
        out = [f"[출처] {source_value}"] + out

    return "\n".join(out)

def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(f"Input not found: {IN_PATH}")

    total = 0
    removed_counts = {k: 0 for k in DROP_KEYS}
    injected_source_cnt = 0

    with IN_PATH.open("r", encoding="utf-8") as fin, OUT_PATH.open("w", encoding="utf-8") as fout:
        for line in fin:
            obj = json.loads(line)

            meta = obj.get("metadata")
            meta_source = None
            if isinstance(meta, dict):
                meta_source = meta.get("source_list")

                # metadata prune
                for k in DROP_KEYS:
                    if k in meta:
                        meta.pop(k, None)
                        removed_counts[k] += 1

            # text_for_embedding에 출처 없으면 보강
            # (top-level source 우선, 없으면 metadata.source_list)
            source_value = obj.get("source") or meta_source
            text = obj.get("text_for_embedding")
            new_text = ensure_source_in_text(text, source_value)
            if isinstance(text, str) and isinstance(new_text, str) and new_text != text:
                obj["text_for_embedding"] = new_text
                injected_source_cnt += 1

            fout.write(json.dumps(obj, ensure_ascii=False) + "\n")
            total += 1

    print(f"[OK] {IN_PATH.name} -> {OUT_PATH.name} ({total} lines)")
    print(f"[INFO] injected [출처] into text_for_embedding: {injected_source_cnt} lines")
    print("[Removed counts]")
    for k in sorted(removed_counts):
        print(f"  - {k}: {removed_counts[k]}")

if __name__ == "__main__":
    main()
