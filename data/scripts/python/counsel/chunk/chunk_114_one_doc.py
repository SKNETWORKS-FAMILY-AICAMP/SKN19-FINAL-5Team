# scripts/preprocess/chunk/chunk_114_one_doc.py
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]  # -> ism/

# ✅ 입력: pruned가 있으면 우선, 없으면 clean 사용
IN_PRUNED = BASE_DIR / "data" / "cnslt" / "processed" / "cnslt_cases_114_full.processed.clean.pruned.norm.jsonl"
IN_CLEAN  = BASE_DIR / "data" / "cnslt" / "processed" / "cnslt_cases_114_full.processed.clean.jsonl"
IN_PATH = IN_PRUNED if IN_PRUNED.exists() else IN_CLEAN

# ✅ 출력: data/cnslt/chunk/ 아래로
OUT_DIR = BASE_DIR / "data" / "cnslt" / "chunks"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "cnslt_cases_114_chunks_v2.jsonl"

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
            # ✅ 중복 방지: 혹시 metadata에 category_path가 있으면 제거
            meta.pop("category_path", None)

            # ✅ 114는 1문서=1청크
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
    