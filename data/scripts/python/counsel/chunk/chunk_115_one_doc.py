# scripts/preprocess/chunk/chunk_115_one_doc.py
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]  # -> ism/

# ✅ 115 processed 최종본으로 바꿔서 사용 (너 폴더 구조 기준)
IN_PATH = BASE_DIR / "data" / "dmge_rlif" / "processed" / "dmge_rlif_cases_115_full.processed.clean.pruned.norm.jsonl"

OUT_DIR = BASE_DIR / "data" / "dmge_rlif" / "chunks"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_PATH = OUT_DIR / "dmge_rlif_cases_115_chunks_v2.jsonl"

def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(f"Input not found: {IN_PATH}")

    n_in = 0
    n_out = 0
    n_skip = 0

    with IN_PATH.open("r", encoding="utf-8") as fin, OUT_PATH.open("w", encoding="utf-8") as fout:
        for line in fin:
            n_in += 1
            obj = json.loads(line)

            doc_id = obj.get("doc_id")
            doc_type = obj.get("doc_type")
            title = obj.get("title")
            category_path = obj.get("category_path") or []
            text = obj.get("text_for_embedding") or ""
            content_hash = obj.get("content_hash")
            collected_at = obj.get("collected_at")

            if not doc_id or not text.strip():
                n_skip += 1
                continue

            meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}

            # ✅ 115는 1문서=1청크
            chunk = {
                "chunk_id": f"{doc_id}::chunk0",
                "chunk_index": 0,
                "chunk_total": 1,
                "doc_id": doc_id,
                "doc_type": doc_type,
                "title": title,
                "category_path": category_path,
                "text": text,
                "metadata": {
                    **meta,
                    "content_hash": content_hash,
                    "collected_at": collected_at,
                },
            }

            fout.write(json.dumps(chunk, ensure_ascii=False) + "\n")
            n_out += 1

    print(f"[OK] IN : {IN_PATH}")
    print(f"[OK] OUT: {OUT_PATH}")
    print(f"[STATS] in={n_in} out={n_out} skipped={n_skip}")

if __name__ == "__main__":
    main()
