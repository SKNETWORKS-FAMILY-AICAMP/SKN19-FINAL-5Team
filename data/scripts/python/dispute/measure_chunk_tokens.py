#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Measure token counts in KCA chunks using KURE-v1 tokenizer.

Finds the longest chunk by token count in a JSONL file.
"""

import json
from pathlib import Path
from transformers import AutoTokenizer


def measure_chunks(jsonl_path: Path, model_name: str = "upskyy/kf-deberta-multitask"):
    """
    Measure token counts for all chunks and find the longest.

    Args:
        jsonl_path: Path to JSONL file
        model_name: HuggingFace model name for tokenizer (default: Korean sentence embedding model)

    Note: Using Korean sentence embedding model tokenizer as proxy for KURE-v1
    """
    print(f"Loading tokenizer: {model_name}")
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_name)
    except Exception as e:
        print(f"Failed to load {model_name}, trying alternative...")
        # Try alternative Korean tokenizers
        alternatives = [
            "klue/bert-base",
            "monologg/kobert",
            "snunlp/KR-SBERT-V40K-klueNLI-augSTS"
        ]
        for alt in alternatives:
            try:
                print(f"Trying {alt}...")
                tokenizer = AutoTokenizer.from_pretrained(alt)
                model_name = alt
                break
            except:
                continue
        else:
            raise Exception("Could not load any Korean tokenizer")

    print(f"\nReading chunks from {jsonl_path}...")
    chunks = []
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            chunks.append(json.loads(line))

    print(f"Found {len(chunks)} chunks\n")

    # Measure token counts
    max_tokens = 0
    max_chunk = None
    token_counts = []

    for i, chunk in enumerate(chunks):
        text = chunk.get('text', '')
        tokens = tokenizer.encode(text, add_special_tokens=True)
        token_count = len(tokens)
        token_counts.append(token_count)

        if token_count > max_tokens:
            max_tokens = token_count
            max_chunk = chunk
            max_chunk_idx = i

    # Statistics
    avg_tokens = sum(token_counts) / len(token_counts)
    sorted_counts = sorted(token_counts, reverse=True)

    print("=" * 80)
    print("TOKEN COUNT STATISTICS")
    print("=" * 80)
    print(f"Total chunks: {len(chunks)}")
    print(f"Average tokens: {avg_tokens:.1f}")
    print(f"Min tokens: {min(token_counts)}")
    print(f"Max tokens: {max_tokens}")
    print(f"\nTop 10 longest chunks:")
    for i in range(min(10, len(sorted_counts))):
        print(f"  {i+1}. {sorted_counts[i]} tokens")

    print("\n" + "=" * 80)
    print("LONGEST CHUNK DETAILS")
    print("=" * 80)
    print(f"Chunk index: {max_chunk_idx}")
    print(f"Token count: {max_tokens}")
    print(f"Case number: {max_chunk.get('case_no', 'N/A')}")
    print(f"Decision date: {max_chunk.get('decision_date', 'N/A')}")
    print(f"Chunk type: {max_chunk.get('chunk_type', 'N/A')}")
    print(f"Case index: {max_chunk.get('case_index', 'N/A')}")
    print(f"\nText preview (first 500 chars):")
    print("-" * 80)
    print(max_chunk.get('text', '')[:500])
    print("-" * 80)

    return {
        'max_tokens': max_tokens,
        'max_chunk': max_chunk,
        'avg_tokens': avg_tokens,
        'token_counts': token_counts
    }


if __name__ == '__main__':
    jsonl_path = Path('kjw/data/preprocess/kca_final_chunks copy.jsonl')
    results = measure_chunks(jsonl_path)
