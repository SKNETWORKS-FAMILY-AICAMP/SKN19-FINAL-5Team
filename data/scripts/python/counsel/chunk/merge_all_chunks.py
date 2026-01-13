# scripts/preprocess/chunk/merge_all_chunks.py
"""
모든 데이터셋의 청킹 결과를 하나로 통합
"""
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]  # -> ism/

# 입력 파일들
CHUNK_FILES = [
    BASE_DIR / "data" / "cnslt" / "chunks" / "cnslt_cases_114_chunks.jsonl",
    BASE_DIR / "data" / "dmge_rlif" / "chunks" / "dmge_rlif_cases_115_chunks.jsonl",
    BASE_DIR / "data" / "kca_00000006" / "chunks" / "kca_00000006_chunks.jsonl",
    BASE_DIR / "data" / "trubl_mdat" / "chunks" / "trubl_mdat_cases_116_chunks.jsonl",
]

# 출력 파일
OUT_DIR = BASE_DIR / "data" / "preprocess"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = OUT_DIR / "ism_all_chunks.jsonl"

def main():
    total_chunks = 0
    dataset_counts = {}
    
    with OUT_PATH.open("w", encoding="utf-8") as fout:
        for chunk_file in CHUNK_FILES:
            if not chunk_file.exists():
                print(f"Warning: {chunk_file} not found, skipping...")
                continue
            
            dataset = chunk_file.parent.parent.name
            count = 0
            
            with chunk_file.open("r", encoding="utf-8") as fin:
                for line in fin:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        chunk = json.loads(line)
                        fout.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                        count += 1
                        total_chunks += 1
                    except json.JSONDecodeError as e:
                        print(f"JSON decode error in {chunk_file}: {e}")
                        continue
            
            dataset_counts[dataset] = count
            print(f"[{dataset}] {count} chunks")
    
    print("=" * 80)
    print(f"[OUT] {OUT_PATH}")
    print(f"[STATS] Total chunks: {total_chunks}")
    for dataset, count in dataset_counts.items():
        print(f"  - {dataset}: {count} chunks")
    print("=" * 80)

if __name__ == "__main__":
    main()
