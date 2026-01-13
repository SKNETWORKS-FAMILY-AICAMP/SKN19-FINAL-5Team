#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
KCDRC 2020+ format parser (no case_no field)

2020+ format has no case number field, uses different structure:
  N. Title
  사건 개요
  ▶ content...
  당사자 주장
  | 신청인 |
  | 피신청인 |
  조정회의 결과
  ● content...

Usage:
  python kjw/scripts/parse_kcdrc_2020plus.py --year 2021 --input kjw/data/raw/parsed/kcdrc/kcdrc_2021_part1_p1-26/merged_elements.txt
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List


# -------------------------
# Regex patterns for 2020+ format
# -------------------------
# Title pattern: Support both "N. Title" and "가. Title" formats
# Followed by either "사건 개요" or "1) 사건개요"
CASE_SPLIT_RE = re.compile(
    r"(?m)^(?:[0-9]+|[가-힣])\.\s+.+?(?=\n(?:사건\s*개요|[0-9]+\)\s*사건개요))"
)

# Section patterns - support both formats and leading markers
SECTION_PREFIX_RE = r"(?:[A-Z]|[IVX]+|[가-힣])\.?\s*"
SECTION_OVERVIEW_RE = re.compile(
    rf"(?m)^(?:{SECTION_PREFIX_RE})?(?:사건\s*개요|[0-9]+\)\s*사건개요)"
)
SECTION_PARTIES_RE = re.compile(
    rf"(?m)^(?:{SECTION_PREFIX_RE})?(?:당사자\s*주장|[0-9]+\)\s*당사자\s*주장)"
)
SECTION_RESULT_RE = re.compile(
    rf"(?m)^(?:{SECTION_PREFIX_RE})?(?:조정회의\s*결과|[0-9]+\)\s*조정회의\s*결과)"
)


def _slice_between(text: str, start_pat: re.Pattern, end_pat: re.Pattern | None) -> str:
    """Extract text between two regex patterns"""
    m1 = start_pat.search(text)
    if not m1:
        return ""
    start = m1.end()

    if end_pat:
        m2 = end_pat.search(text, start)
        if m2:
            return text[start:m2.start()].strip()
    return text[start:].strip()


def split_into_cases(merged_text: str) -> List[str]:
    """
    Split merged text into individual cases using title pattern.
    2020+ format: "N. Title" followed by "사건 개요"
    """
    matches = list(CASE_SPLIT_RE.finditer(merged_text))
    if not matches:
        return []

    idxs = [m.start() for m in matches]
    idxs.append(len(merged_text))

    cases = []
    for i in range(len(idxs) - 1):
        chunk = merged_text[idxs[i]:idxs[i + 1]].strip()
        if chunk:
            cases.append(chunk)
    return cases


def extract_title(case_text: str) -> str:
    """Extract title from case text (supports both "N. Title" and "가. Title" patterns)"""
    # Try "N. Title" pattern first
    m = re.search(r"^([0-9]+)\.\s+(.+?)(?=\n)", case_text, re.MULTILINE)
    if m:
        title = m.group(2).strip()
        # Clean up: remove extra whitespace
        title = re.sub(r'\s+', ' ', title)
        return title

    # Try "가. Title" pattern (Korean letter)
    m = re.search(r"^([가-힣])\.\s+(.+?)(?=\n)", case_text, re.MULTILINE)
    if m:
        title = m.group(2).strip()
        # Clean up: remove extra whitespace
        title = re.sub(r'\s+', ' ', title)
        return title

    return ""


def parse_case_fields(case_text: str, year: int) -> Dict[str, Any]:
    """
    Parse 2020+ KCDRC case fields

    Returns dict with:
    - title: Case title
    - case_no: None (no case number in 2020+ format)
    - decision_date: year - 1 (사례집 발행년도 - 1)
    - decision: Not available in new format (set to empty)
    - parties_claim: Content from "당사자 주장"
    - judgment: Content from "조정회의 결과"
    """
    # Extract title
    title = extract_title(case_text)

    # decision_date = 사례집 발행년도 - 1
    decision_date = str(year - 1) if year else None

    # Extract sections
    # 1. 사건 개요 (overview)
    overview = _slice_between(case_text, SECTION_OVERVIEW_RE, SECTION_PARTIES_RE)

    # 2. 당사자 주장 (parties claim)
    parties_claim = _slice_between(case_text, SECTION_PARTIES_RE, SECTION_RESULT_RE)

    # 3. 조정회의 결과 (mediation result)
    judgment = _slice_between(case_text, SECTION_RESULT_RE, None)

    # Combine parties_claim with overview context
    if overview:
        parties_claim = f"[사건 개요]\n{overview}\n\n[당사자 주장]\n{parties_claim}"

    return {
        "title": title,
        "case_no": None,  # No case number in 2020+ format
        "decision_date": decision_date,
        "decision": "",  # No separate decision section in new format
        "parties_claim": parties_claim,
        "judgment": judgment,
    }


def preprocess_for_rag(text: str) -> str:
    """RAG 시스템에 최적화된 텍스트 전처리"""
    # Replace tabs with spaces (important for 2020+ data)
    text = text.replace('\t', ' ')

    # Replace masked control characters with a readable placeholder
    text = re.sub(r'(?:\x1a|\\u001a|\\x1a)+', '[MASKED]', text)

    # Remove page markers
    text = re.sub(r'\n*=== PAGE \d+ ===\n*', '\n', text)

    # Remove page numbers
    text = re.sub(r'\d+\s+\d{4}\s+콘텐츠분쟁조정사례집', '', text)

    # Normalize multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Normalize multiple spaces
    text = re.sub(r' {2,}', ' ', text)

    # Clean up lines
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(line for line in lines if line)

    return text.strip()


def preprocess_light(text: str) -> str:
    """경량 전처리: 노이즈만 제거"""
    # Replace tabs with spaces
    text = text.replace('\t', ' ')

    # Replace masked control characters with a readable placeholder
    text = re.sub(r'(?:\x1a|\\u001a|\\x1a)+', '[MASKED]', text)

    # Remove page markers
    text = re.sub(r'\n*=== PAGE \d+ ===\n*', '\n', text)

    # Remove page numbers
    text = re.sub(r'\d+\s+\d{4}\s+콘텐츠분쟁조정사례집', '', text)

    # Normalize multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def sanitize_masked_text(text: str) -> str:
    return re.sub(r'(?:\x1a|\\u001a|\\x1a)+', '[MASKED]', text)


def main():
    ap = argparse.ArgumentParser(
        description="Parse KCDRC 2020+ format (no case_no) to structured JSONL",
        epilog="""
Examples:
  # Parse 2021 사례집 (contains 2020 cases)
  python %(prog)s --year 2021 --input kjw/data/raw/parsed/kcdrc/kcdrc_2021_part1_p1-26/merged_elements.txt

  # Parse with RAG preprocessing
  python %(prog)s --year 2021 --input kjw/data/raw/parsed/kcdrc/kcdrc_2021_part1_p1-26/merged_elements.txt --preprocess=rag
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    ap.add_argument("--year", type=int, required=True, help="사례집 발행년도 (e.g., 2021)")
    ap.add_argument("--input", required=True, help="Path to merged_elements.txt")
    ap.add_argument("--output-dir", default="kjw/data/preprocess", help="Output directory")
    ap.add_argument("--output-prefix", help="Output filename prefix (default: kcdrc_{year}_final)")
    ap.add_argument("--preprocess", choices=["none", "light", "rag"], default="none",
                    help="Preprocessing mode")

    args = ap.parse_args()

    # Read input
    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    merged_text = input_path.read_text(encoding="utf-8")
    print(f"[LOADED] {input_path} ({len(merged_text):,} chars)")

    # Select preprocessing function
    preprocess_func = None
    if args.preprocess == "rag":
        preprocess_func = preprocess_for_rag
        print("[PREPROCESS] RAG mode")
    elif args.preprocess == "light":
        preprocess_func = preprocess_light
        print("[PREPROCESS] Light mode")
    else:
        print("[PREPROCESS] None")

    # Split into cases
    cases = split_into_cases(merged_text)
    print(f"[SPLIT] Found {len(cases)} cases (year: {args.year}, decision_date: {args.year - 1})")

    # Parse and write
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_prefix = args.output_prefix or f"kcdrc_{args.year}_final"
    cases_path = output_dir / f"{output_prefix}_cases.jsonl"
    chunks_path = output_dir / f"{output_prefix}_chunks.jsonl"

    with cases_path.open("w", encoding="utf-8") as f_cases, \
         chunks_path.open("w", encoding="utf-8") as f_chunks:

        for idx, case_text in enumerate(cases, start=1):
            fields = parse_case_fields(case_text, args.year)
            case_text = sanitize_masked_text(case_text)
            for key in ("title", "parties_claim", "judgment"):
                if fields.get(key):
                    fields[key] = sanitize_masked_text(fields[key])

            # Apply preprocessing if enabled
            if preprocess_func:
                fields["decision"] = preprocess_func(fields.get("decision", ""))
                fields["parties_claim"] = preprocess_func(fields.get("parties_claim", ""))
                fields["judgment"] = preprocess_func(fields.get("judgment", ""))
                preprocessed_raw = preprocess_func(case_text)
            else:
                preprocessed_raw = case_text

            # Build record matching kca format
            record = {
                "source": f"kcdrc_{args.year}",
                "agency": "kcdrc",
                "case_index": idx,
                "title": fields.get("title"),
                "case_no": fields.get("case_no"),  # None for 2020+
                "decision_date": fields.get("decision_date"),  # year - 1
                "decision": fields.get("decision", ""),
                "parties_claim": fields.get("parties_claim", ""),
                "judgment": fields.get("judgment", ""),
                "raw_text": preprocessed_raw,
            }
            f_cases.write(json.dumps(record, ensure_ascii=False) + "\n")

            # Write chunks for RAG
            shared = {
                "source": f"kcdrc_{args.year}",
                "agency": "kcdrc",
                "case_index": idx,
                "case_no": fields.get("case_no"),
                "decision_date": fields.get("decision_date"),
            }

            for chunk_type in ("decision", "parties_claim", "judgment"):
                txt = fields.get(chunk_type) or ""
                txt = txt.strip()
                if not txt:
                    continue
                f_chunks.write(json.dumps(
                    {**shared, "chunk_type": chunk_type, "text": txt},
                    ensure_ascii=False
                ) + "\n")

    print(f"[SAVED] {cases_path}")

    # Count chunks
    with chunks_path.open("r", encoding="utf-8") as f:
        num_chunks = sum(1 for _ in f)
    print(f"[SAVED] {chunks_path} ({num_chunks} chunks)")

    print("\n[DONE]")


if __name__ == "__main__":
    main()
