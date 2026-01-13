#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
KCDRC merged_elements.txt -> structured JSONL (kca format style)

Parse KCDRC cases from merged_elements.txt and convert to structured format similar to kca_final_cases.json

KCDRC Structure:
  (N) Title
  ▶ 사건번호 : YYYY-NNNNN
  ▶ 조정방법 : 대면/서면
  1. 사건개요
  2. 당사자의 주장
    1) 신청인
    2) 피신청인
  3. 조정회의 (or 조정회의 결과)
    1) 조정안
    2) 이유
  4. 조정결과

Usage:
  conda activate crawling
  python kjw/scripts/parse_kcdrc_cases.py --input kjw/data/preprocess/kcdrc_merged_elements.txt --output-dir kjw/data/preprocess
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


# -------------------------
# Regex patterns for KCDRC
# -------------------------
# Match case titles: "(1) Title" or "1. Title" at start of line
# More robust pattern to catch both formats
CASE_SPLIT_RE = re.compile(
    r"(?m)^(?:\([0-9]+\)|[0-9]+\.)\s+.+?(?=\n▶\s*사건번호)"
)
# 2020+ format: "N. Title" or "가. Title" followed by "사건개요"
CASE_SPLIT_2020_RE = re.compile(
    r"(?m)^(?:[0-9]+|[가-힣])\.\s+.+?(?=\n(?:사건\s*개요|사건개요))"
)

# Extract case number - support both formats:
# - Old format: ▶ 사건번호 : 2017-03188
# - New format: 사건번호 : 2018-04511 2018-04511 : 사건번호
CASE_NO_RE = re.compile(
    r"(?:▶\s*)?사건\s*번호\s*[:：]\s*([0-9]{4}[-‐-–—][0-9]+)"
)

# Section headers - looking for numbered sections
SECTION_OVERVIEW_RE = re.compile(r"(?m)^\d+\.\s*사건\s*개요")
SECTION_PARTIES_RE = re.compile(r"(?m)^\d+\.\s*당사자의?\s*주장")
SECTION_MEDIATION_RE = re.compile(r"(?m)^\d+\.\s*조정\s*회의\s*(?:결과)?")
SECTION_RESULT_RE = re.compile(r"(?m)^\d+\.\s*조정\s*결과")
# 2020+ unnumbered sections (allow leading letter/roman marker like "E 조정회의 결과")
SECTION_PREFIX_RE = r"(?:[A-Z]|[IVX]+|[가-힣])\.?\s*"
SECTION_OVERVIEW_UNNUM_RE = re.compile(
    rf"(?m)^(?:{SECTION_PREFIX_RE})?(?:사건\s*개요|사건개요)"
)
SECTION_PARTIES_UNNUM_RE = re.compile(
    rf"(?m)^(?:{SECTION_PREFIX_RE})?(?:당사자의?\s*주장|당사자\s*주장)"
)
SECTION_MEDIATION_UNNUM_RE = re.compile(
    rf"(?m)^(?:{SECTION_PREFIX_RE})?조정회의\s*(?:결과)?"
)
SECTION_RESULT_UNNUM_RE = re.compile(
    rf"(?m)^(?:{SECTION_PREFIX_RE})?조정\s*결과"
)

# Subsection patterns within "조정회의"
SUBSECTION_MEDIATION_PLAN_RE = re.compile(r"(?m)^\d+\)\s*조정안")
SUBSECTION_REASON_RE = re.compile(r"(?m)^\d+\)\s*이유")


def _slice_between(text: str, start_pat: re.Pattern, end_pat: Optional[re.Pattern]) -> str:
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
    Split merged text into individual cases.

    KCDRC cases start with "(N) Title" followed by "▶ 사건번호"
    We'll use a simple approach: split by "=== PAGE" boundaries and case number patterns
    """
    # Find all case starts: "(N) ... ▶ 사건번호" or 2020+ "N. Title" + 사건개요
    # More robust: find all "사건번호" and title anchors

    case_no_matches = list(CASE_NO_RE.finditer(merged_text))
    if not case_no_matches:
        case_no_matches = []

    # For each case_no match, backtrack to find the title
    # Title pattern: "(N) Title" before "▶ 사건번호"
    case_starts: List[int] = []

    for m in case_no_matches:
        # Look backward for title pattern "(N) Title" or "N. Title"
        # Search within 500 chars before case_no
        search_start = max(0, m.start() - 500)
        segment = merged_text[search_start:m.start()]

        # Find last occurrence of title patterns
        title_match = None
        best_pos = -1

        # Try both patterns: "(N) Title" and "N. Title"
        for pattern in [r"\n\([0-9]+\)\s+[^\n]+", r"\n[0-9]+\.\s+[^\n]+"]:
            for title_m in re.finditer(pattern, segment):
                if title_m.start() > best_pos:
                    best_pos = title_m.start()
                    title_match = title_m

        if title_match:
            # Actual position in full text
            actual_pos = search_start + title_match.start() + 1  # +1 to skip newline
            case_starts.append(actual_pos)
        else:
            # Fallback: go back a bit from case_no to include context
            fallback_start = max(0, m.start() - 100)
            case_starts.append(fallback_start)

    # Add 2020+ case starts (title + 사건개요)
    for m in CASE_SPLIT_2020_RE.finditer(merged_text):
        case_starts.append(m.start())

    # Remove duplicates and sort
    case_starts = sorted(set(case_starts))

    if not case_starts:
        return [merged_text.strip()] if merged_text.strip() else []

    # Split into chunks
    cases = []
    for i in range(len(case_starts)):
        start = case_starts[i]
        end = case_starts[i + 1] if i + 1 < len(case_starts) else len(merged_text)
        chunk = merged_text[start:end].strip()
        if chunk:
            cases.append(chunk)

    return cases


def extract_title(case_text: str) -> str:
    """
    Extract title from case text.
    Title should be immediately before "사건번호" line.
    """
    # Find "사건번호" position (with or without ▶)
    case_no_match = re.search(r"(?:▶\s*)?사건\s*번호", case_text)
    if not case_no_match:
        return ""

    # Look backward from case_no position for title patterns
    # Search within 300 chars before case_no
    search_end = case_no_match.start()
    search_start = max(0, search_end - 300)
    segment = case_text[search_start:search_end]

    # Find the LAST occurrence of title pattern (closest to case_no)
    # Patterns: "(N) Title" or "N. Title"
    # Use (?:^|\n) to match both line start and newline
    patterns = [
        r"(?:^|\n)\([0-9]+\)\s+([^\n▶]+)",  # (1) Title
        r"(?:^|\n)([0-9]+)\.\s+([^\n▶]+)",  # 1. Title (capture number + title)
        r"(?:^|\n)([가-힣])\.\s+([^\n▶]+)",  # 가. Title
    ]

    best_match = None
    best_pos = -1

    for pattern in patterns:
        for m in re.finditer(pattern, segment, re.MULTILINE):
            # Keep the match closest to case_no (highest position)
            if m.start() > best_pos:
                best_pos = m.start()
                best_match = m

    if best_match:
        # Handle different group structures
        # Pattern 1: group(1) is the title
        # Pattern 2: group(1) is number, group(2) is title
        if len(best_match.groups()) == 2 and best_match.group(2):
            title = best_match.group(2).strip()
        else:
            title = best_match.group(1).strip()
        # Clean up: remove extra whitespace
        title = re.sub(r'\s+', ' ', title)
        # Filter out non-title patterns (섹션 헤더들)
        # Skip if it looks like a section header
        section_patterns = [
            r"^\d+\.\s*사건\s*개요",
            r"^\d+\.\s*당사자",
            r"^\d+\.\s*조정",
            r"^\d+\.\s*합의",
            r"^조정회의",
            r"^사건개요",
        ]
        for sec_pat in section_patterns:
            if re.match(sec_pat, title, re.IGNORECASE):
                return ""
        return title

    return ""


def parse_case_fields(case_text: str) -> Dict[str, Any]:
    """
    Parse KCDRC case fields to match kca_final_cases.json structure

    Returns dict with:
    - title: Case title
    - case_no: Case number (사건번호)
    - decision_date: Not available in KCDRC format (set to None)
    - decision: "조정안" from 조정회의
    - parties_claim: Content from "당사자의 주장"
    - judgment: "이유" from 조정회의 + "조정결과"
    """
    # Extract title
    title = extract_title(case_text)

    # Extract case number
    case_no = None
    m = CASE_NO_RE.search(case_text)
    if m:
        case_no = m.group(1).strip()

    # Extract year from case_no for decision_date (KCDRC only has year info)
    decision_date = None
    if case_no:
        year_match = re.match(r"(\d{4})", case_no)
        if year_match:
            decision_date = year_match.group(1)

    # Extract sections
    # 1. 사건개요
    overview = _slice_between(case_text, SECTION_OVERVIEW_RE, SECTION_PARTIES_RE)
    if not overview:
        overview = _slice_between(case_text, SECTION_OVERVIEW_UNNUM_RE, SECTION_PARTIES_UNNUM_RE)

    # 2. 당사자의 주장 (until 조정회의)
    parties_claim = _slice_between(case_text, SECTION_PARTIES_RE, SECTION_MEDIATION_RE)
    if not parties_claim:
        parties_claim = _slice_between(case_text, SECTION_PARTIES_UNNUM_RE, SECTION_MEDIATION_UNNUM_RE)

    # 3. 조정회의 -> extract "조정안" and "이유"
    # Find mediation section
    mediation_section = ""
    m_med = SECTION_MEDIATION_RE.search(case_text)
    if m_med:
        # Extract from "조정회의" to "조정결과"
        m_result = SECTION_RESULT_RE.search(case_text, m_med.end())
        if m_result:
            mediation_section = case_text[m_med.end():m_result.start()].strip()
        else:
            mediation_section = case_text[m_med.end():].strip()
    else:
        m_med = SECTION_MEDIATION_UNNUM_RE.search(case_text)
        if m_med:
            m_result = SECTION_RESULT_UNNUM_RE.search(case_text, m_med.end())
            if m_result:
                mediation_section = case_text[m_med.end():m_result.start()].strip()
            else:
                mediation_section = case_text[m_med.end():].strip()

    # Extract "조정안" and "이유" from mediation section
    # Two patterns:
    # 1. With subsections: "1) 조정안" and "2) 이유"
    # 2. Without subsections: direct content
    decision = ""
    mediation_reason = ""

    if SUBSECTION_MEDIATION_PLAN_RE.search(mediation_section):
        # Pattern 1: Has "1) 조정안" subsection
        decision = _slice_between(mediation_section, SUBSECTION_MEDIATION_PLAN_RE, SUBSECTION_REASON_RE)
        mediation_reason = _slice_between(mediation_section, SUBSECTION_REASON_RE, None)
    else:
        # Pattern 2: No subsections - treat whole mediation section as mediation_reason
        mediation_reason = mediation_section

    # 4. 조정결과
    result = _slice_between(case_text, SECTION_RESULT_RE, None)
    if not result:
        result = _slice_between(case_text, SECTION_RESULT_UNNUM_RE, None)

    # Combine judgment: "이유" + "조정결과"
    judgment_parts = []
    if mediation_reason:
        judgment_parts.append(mediation_reason)
    if result:
        judgment_parts.append(f"[조정결과]\n{result}")
    judgment = "\n\n".join(judgment_parts)

    # Combine parties_claim with overview context
    if overview:
        parties_claim = f"[사건개요]\n{overview}\n\n[당사자의 주장]\n{parties_claim}"

    return {
        "title": title,
        "case_no": case_no,
        "decision_date": decision_date,  # Year only from case_no
        "decision": decision,
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
    text = re.sub(r'제\d+편\s+[\|│]\s+주요\s+사례\s*[:：]\s*분쟁조정', '', text)

    # Normalize multiple newlines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def sanitize_masked_text(text: str) -> str:
    return re.sub(r'(?:\x1a|\\u001a|\\x1a)+', '[MASKED]', text)


def main():
    ap = argparse.ArgumentParser(
        description="Parse KCDRC merged_elements.txt to structured JSONL (kca format style)",
        epilog="""
Examples:
  # Parse with RAG preprocessing
  python %(prog)s --input kjw/data/preprocess/kcdrc_merged_elements.txt --output-dir kjw/data/preprocess --preprocess=rag

  # Parse without preprocessing
  python %(prog)s --input kjw/data/preprocess/kcdrc_merged_elements.txt --output-dir kjw/data/preprocess --preprocess=none
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    ap.add_argument("--input", required=True, help="Path to kcdrc_merged_elements.txt")
    ap.add_argument("--output-dir", default="kjw/data/preprocess", help="Output directory")
    ap.add_argument("--output-prefix", default="kcdrc_final", help="Output filename prefix")
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
    print(f"[SPLIT] Found {len(cases)} cases")

    # Parse and write
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cases_path = output_dir / f"{args.output_prefix}_cases.jsonl"
    chunks_path = output_dir / f"{args.output_prefix}_chunks.jsonl"

    with cases_path.open("w", encoding="utf-8") as f_cases, \
         chunks_path.open("w", encoding="utf-8") as f_chunks:

        for idx, case_text in enumerate(cases, start=1):
            fields = parse_case_fields(case_text)
            case_text = sanitize_masked_text(case_text)
            for key in ("title", "decision", "parties_claim", "judgment"):
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

            # Build record matching kca format (no mediation_method field)
            record = {
                "source": "kcdrc_merged",
                "agency": "kcdrc",
                "case_index": idx,
                "title": fields.get("title"),
                "case_no": fields.get("case_no"),
                "decision_date": fields.get("decision_date"),  # Year only
                "decision": fields.get("decision", ""),
                "parties_claim": fields.get("parties_claim", ""),
                "judgment": fields.get("judgment", ""),
                "raw_text": preprocessed_raw,
            }
            f_cases.write(json.dumps(record, ensure_ascii=False) + "\n")

            # Write chunks for RAG
            shared = {
                "source": "kcdrc_merged",
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
