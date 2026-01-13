#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Merge all KCDRC year files into final combined files

Combines:
- kcdrc_final_cases.jsonl (2015-2019)
- kcdrc_2021_final_cases.jsonl (2020)
- kcdrc_2023_final_cases.jsonl (2022)
- kcdrc_2024_final_cases.jsonl (2023)

Usage:
  python kjw/scripts/merge_kcdrc_all_years.py
"""

import json
from pathlib import Path

def main():
    preprocess_dir = Path("kjw/data/preprocess")

    # Input files in chronological order
    input_files = [
        "kcdrc_final_cases.jsonl",      # 2015-2019
        "kcdrc_2021_final_cases.jsonl", # 2020
        "kcdrc_2023_final_cases.jsonl", # 2022
        "kcdrc_2024_final_cases.jsonl", # 2023
    ]

    chunk_files = [
        "kcdrc_final_chunks.jsonl",      # 2015-2019
        "kcdrc_2021_final_chunks.jsonl", # 2020
        "kcdrc_2023_final_chunks.jsonl", # 2022
        "kcdrc_2024_final_chunks.jsonl", # 2023
    ]

    # Output files
    output_cases = preprocess_dir / "kcdrc_all_years_cases.jsonl"
    output_chunks = preprocess_dir / "kcdrc_all_years_chunks.jsonl"

    print("[MERGING CASES]")
    total_cases = 0
    with output_cases.open("w", encoding="utf-8") as f_out:
        for input_file in input_files:
            input_path = preprocess_dir / input_file
            if not input_path.exists():
                print(f"  [SKIP] {input_file} (not found)")
                continue

            count = 0
            with input_path.open("r", encoding="utf-8") as f_in:
                for line in f_in:
                    if line.strip():
                        record = json.loads(line)
                        # Re-index globally
                        record["case_index"] = total_cases + 1
                        # Update source to indicate merged
                        record["source"] = "kcdrc_all_years"
                        f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
                        count += 1
                        total_cases += 1

            print(f"  [ADDED] {input_file}: {count} cases")

    print(f"[SAVED] {output_cases} (total: {total_cases} cases)\n")

    print("[MERGING CHUNKS]")
    total_chunks = 0
    with output_chunks.open("w", encoding="utf-8") as f_out:
        for chunk_file in chunk_files:
            chunk_path = preprocess_dir / chunk_file
            if not chunk_path.exists():
                print(f"  [SKIP] {chunk_file} (not found)")
                continue

            count = 0
            with chunk_path.open("r", encoding="utf-8") as f_in:
                for line in f_in:
                    if line.strip():
                        record = json.loads(line)
                        # Update source to indicate merged
                        record["source"] = "kcdrc_all_years"
                        f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
                        count += 1
                        total_chunks += 1

            print(f"  [ADDED] {chunk_file}: {count} chunks")

    print(f"[SAVED] {output_chunks} (total: {total_chunks} chunks)\n")
    print("[DONE]")

if __name__ == "__main__":
    main()
