#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Parse ECMC (전기통신분쟁조정위원회) case data from merged text file

ECMC case structure:

Format 1 (CA## cases):
- Case separator: "● 사건번호: CAXX-XXXXX" or "• 사건번호 : CA14-00120"
- Case name: "· 사건명칭: ..." or "● 사건명칭:"
- Sections:
  - "1. 사건 개요" - case overview
  - "2. 당사자 주장" - parties' claims
  - "3. 조정부의 판단" - committee's judgment
    - "주 문" - decision
    - "이 유" - reasoning
  - "4. 조정안 권고결과" - recommendation result (optional)

Format 2 (사례 N cases, after line 26660):
- Case separator: "사례 N" or "사례 N [title]"
- Case name: "사건명칭 : ..." (before "사례 N") or inline in "사례 N [title]"
- Year extracted from footer: "YYYY 전자거래분쟁조정 사례집"
- Generated case_no: "YEAR-N"

Usage:
  conda activate crawling
  python kjw/scripts/parse_ecmc_cases.py --input kjw/data/preprocess/ecmc_merged_elements.txt --output kjw/data/preprocess/ecmc_final_cases.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


# Format 1: Case separator with explicit case number
# "● 사건번호: CA09-02073" or "• 사건번호 : CA14-00120" or "· 사건번호: CA10-01003"
# Some headers include a page title prefix like "전자거래분쟁조정사례집 | · 사건번호: ..."
CASE_SPLIT_RE = re.compile(
    r"^[^\n]*[●•·]\s*사건번호\s*[:：]\s*",
    re.MULTILINE,
)

# Case number extraction from Format 1
CASE_NO_RE = re.compile(r"[●•·]\s*사건번호\s*[:：]\s*([A-Za-z0-9\-가-힣 ]+(?:호)?)")

# Format 2: Case separator with case number only (사례 N format)
# Matches "사례 1", "사례1", "사례 1 타이틀..."
# Use [ \t]* (zero or more spaces/tabs) to allow "사례1" or "사례 1"
# Don't use \s to avoid matching newlines
CASE_NUM_SPLIT_RE = re.compile(r"^사례[ \t]*(\d+)(?:[ \t]+(.*))?$", re.MULTILINE)
# Format 3: "N.\n[title]\n가. 사건 개요" style (detected via line scan)

# Case name extraction: "· 사건명칭: 물품대금반환" or "● 사건명칭:" or "사건명칭 [title]"
# Note: Can use ● (U+25CF), • (U+2022), · (U+00B7), or no bullet
# Colon is optional (2017 has ":", 2018+ often don't have it)
CASE_NAME_RE = re.compile(r"(?:[●•·]\s*)?사건명칭\s*[:：]?\s*(.+?)(?:\n|$)")

# Year extraction from footer: "2017 전자거래분쟁조정 사례집"
YEAR_FOOTER_RE = re.compile(r"(\d{4})\s*전자거래\s*분?쟁조정\s*사례집")

# Section markers
SECTION_OVERVIEW_RE = re.compile(r"(?:^|\n|\s)\s*1\s*(?:[.)])\s*사건\s*개요", re.MULTILINE)
SECTION_PARTIES_RE = re.compile(r"(?:^|\n|\s)\s*2\s*(?:[.)])\s*당사자\s*주장", re.MULTILINE)
SECTION_JUDGMENT_RE = re.compile(
    r"(?:^|\n|\s)\s*3\s*\.\s*(?:조정부\s*(?:의\s*)?판단|사무국\s*(?:판단|권고|합의\s*권고)|합의\s*권고|합의권고)",
    re.MULTILINE,
)
SECTION_RESULT_RE = re.compile(
    r"(?:^|\n|\s)\s*4\s*\.\s*(?:조정안\s*권고결과|처리\s*결과|처리결과|조정\s*결과)",
    re.MULTILINE,
)
SECTION_OVERVIEW_KOR_RE = re.compile(r"(?:^|\n|\s)\s*가\s*\.\s*사건\s*개요", re.MULTILINE)
SECTION_PARTIES_KOR_RE = re.compile(r"(?:^|\n|\s)\s*나\s*\.\s*(?:양\s*)?당사자\s*주장", re.MULTILINE)
SECTION_JUDGMENT_KOR_RE = re.compile(
    r"(?:^|\n|\s)\s*다\s*\.\s*(?:조정부\s*판단|조정\s*결정|조정\s*결과)",
    re.MULTILINE,
)
SECTION_RESULT_KOR_RE = re.compile(r"(?:^|\n|\s)\s*라\s*\.\s*조정\s*결과", re.MULTILINE)

# Decision and reasoning subsections
DECISION_MARKER_RE = re.compile(r"(?:^|\n)\s*주\s*문\s*(?:\n|$)|\s주\s*문\s", re.MULTILINE)
REASONING_MARKER_RE = re.compile(r"(?:^|\n)\s*이\s*유\s*(?:\n|$)|\s이\s*유\s", re.MULTILINE)


def preprocess_light(text: str) -> str:
    """경량 전처리: 페이지 마커 및 노이즈 제거"""
    # Replace masked control characters with a readable placeholder
    text = re.sub(r'(?:\x1a|\\u001a|\\x1a)+', '[MASKED]', text)

    # Remove page markers
    text = re.sub(r'\n*=== PAGE \d+ ===\n*', '\n', text)

    # Remove common footer patterns
    text = re.sub(r'\d{4}년\s*\d+\s*전자거래분쟁조정사례집', '', text)
    text = re.sub(r'제\d+편\s+[^\n]*\n', '', text)
    text = re.sub(r'^\s*[머리말|발간사|개요|상담|합의권고|조정|부록]\s*$', '', text, flags=re.MULTILINE)

    # Normalize whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)

    return text.strip()


def sanitize_masked_text(text: str) -> str:
    return re.sub(r'(?:\x1a|\\u001a|\\x1a)+', '[MASKED]', text)


def split_into_cases(merged_text: str) -> List[Tuple[str, str]]:
    """Split merged text into individual cases

    Returns:
        List of tuples (case_text, case_type) where case_type is 'format1' or 'format2'
    """
    def _find_format3_matches(text: str) -> List[Tuple[int, int, str]]:
        lines = text.splitlines(keepends=True)
        offsets: List[int] = []
        pos = 0
        for line in lines:
            offsets.append(pos)
            pos += len(line)
        matches: List[Tuple[int, int, str]] = []
        num_re = re.compile(r"^\s*\d{1,2}\.\s*$")
        overview_re = re.compile(r"^\s*가\s*\.\s*사건\s*개요")
        for i, line in enumerate(lines):
            if not num_re.match(line):
                continue
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j >= len(lines):
                continue
            # Look ahead a few lines for "가. 사건 개요" (allow intervening headers)
            found = False
            for k in range(j + 1, min(len(lines), j + 9)):
                if overview_re.search(lines[k]):
                    found = True
                    break
            if found:
                matches.append((offsets[i], offsets[i] + len(lines[i]), "format3"))
        return matches

    # Find all case separator positions for both formats
    format1_matches = [(m.start(), m.end(), 'format1') for m in CASE_SPLIT_RE.finditer(merged_text)]
    format2_raw_matches = list(CASE_NUM_SPLIT_RE.finditer(merged_text))
    format2_matches = [(m.start(), m.end(), 'format2') for m in format2_raw_matches]
    format3_matches = _find_format3_matches(merged_text)

    # For format2 cases, pull in the nearest "사건명칭" line before "사례 N"
    adjusted_format2_matches = []
    title_pattern = re.compile(r"(?:[●•·]\s*)?사건명칭\s*[:：]?\s*[^\n]+\n")
    skip_title_re = re.compile(
        r"^(?:제\s*\d+편|[ⅠⅡⅢIVX]+|합의권고사례|분쟁조정\s*사례|주요사례|분석|===\s*PAGE\s*\d+\s*===)$"
    )
    for i, (start, end, case_type) in enumerate(format2_matches):
        # Search back to the previous "사례" marker so we don't grab a prior case's title
        search_start = format2_raw_matches[i - 1].start() if i > 0 else 0
        preceding_text = merged_text[search_start:start]
        title_matches = list(title_pattern.finditer(preceding_text))

        if title_matches:
            last_match = title_matches[-1]
            adjusted_start = search_start + last_match.start()
            adjusted_format2_matches.append((adjusted_start, end, case_type))
        else:
            # Try to capture a standalone title line immediately before "사례 N"
            lines = [line.strip() for line in preceding_text.splitlines() if line.strip()]
            candidate = None
            for line in reversed(lines[-5:]):
                if skip_title_re.match(line):
                    continue
                if line.startswith("사례"):
                    continue
                candidate = line
                break
            if candidate:
                adjusted_start = start - (len(preceding_text) - preceding_text.rfind(candidate))
                adjusted_format2_matches.append((adjusted_start, end, case_type))
            else:
                adjusted_format2_matches.append((start, end, case_type))

    # Combine and sort by position
    all_matches = sorted(format1_matches + adjusted_format2_matches + format3_matches, key=lambda x: x[0])

    if not all_matches:
        return []

    cases = []
    for i, (start, end, case_type) in enumerate(all_matches):
        # Find end position (start of next case or end of text)
        if i + 1 < len(all_matches):
            case_end = all_matches[i + 1][0]
        else:
            case_end = len(merged_text)

        case_text = merged_text[start:case_end].strip()
        if case_text:
            cases.append((case_text, case_type))

    return cases


def extract_section(text: str, start_pattern: re.Pattern, end_pattern: re.Pattern = None) -> str:
    """Extract text between two section markers"""
    start_match = start_pattern.search(text)
    if not start_match:
        return ""

    start_pos = start_match.end()

    if end_pattern:
        end_match = end_pattern.search(text, start_pos)
        if end_match:
            return text[start_pos:end_match.start()].strip()

    return text[start_pos:].strip()


def extract_year_from_text(case_text: str) -> str | None:
    """Extract year from footer pattern like '2017 전자거래분쟁조정 사례집'"""
    m = YEAR_FOOTER_RE.search(case_text)
    if m:
        return m.group(1)
    return None


def _normalize_case_no(case_no: str) -> str:
    case_no = re.sub(r"\s+", "", case_no).upper()
    m = re.match(r"^CA([A-Z0-9]{2})(-.+)?$", case_no)
    if not m:
        return case_no
    yy_raw = m.group(1)
    yy = yy_raw.replace("I", "1").replace("O", "0").replace("L", "1")
    if not yy.isdigit():
        yy = yy_raw
    suffix = m.group(2) or ""
    return f"CA{yy}{suffix}"


def parse_case_fields(case_text: str, case_type: str = 'format1',
                      year_override: str = None, case_num_override: int = None) -> Dict[str, Any]:
    """Parse individual ECMC case fields

    Args:
        case_text: The case text to parse
        case_type: 'format1' (사건번호:) or 'format2' (사례 N)
        year_override: For format2, the year to use for case_no generation
        case_num_override: For format2, the case number from "사례 N"
    """

    if case_type == 'format2':
        # Format 2: "사례 N" format
        # Extract case number from "사례 N" pattern
        case_num = case_num_override
        title = None

        m = CASE_NUM_SPLIT_RE.search(case_text)
        if m:
            # Extract case_num if not provided
            if not case_num:
                case_num = int(m.group(1))

            # Check if title is inline with "사례 N [title]"
            inline_title = m.group(2)
            if inline_title and inline_title.strip():
                title = inline_title.strip()

        # If no inline title found, try to extract from "사건명칭 :" pattern
        if not title:
            title_m = CASE_NAME_RE.search(case_text)
            if title_m:
                title = title_m.group(1).strip()
        # If still missing, try a leading title line before "사례 N"
        if not title:
            lead_title_re = re.compile(r"^([^\n]+)\n\s*사례[ \t]*\d+", re.MULTILINE)
            lead_m = lead_title_re.search(case_text)
            if lead_m:
                candidate = lead_m.group(1).strip()
                if candidate and not re.match(r"^(?:제\s*\d+편|[ⅠⅡⅢIVX]+|합의권고사례|분쟁조정\s*사례|주요사례|분석)$", candidate):
                    title = candidate

        # Extract or use provided year
        year = year_override or extract_year_from_text(case_text)

        # Generate case_no as "YEAR-N"
        if year and case_num:
            case_no = f"{year}-{case_num}"
            decision_date = year
        else:
            case_no = None
            decision_date = year

    elif case_type == 'format3':
        # Format 3: "N.\n[title]\n가. 사건 개요" format
        case_num = None
        title = None
        m = re.search(r"^\s*(\d{1,2})\.\s*\n\s*([^\n]+)", case_text, re.MULTILINE)
        if m:
            case_num = int(m.group(1))
            title = m.group(2).strip()

        year = year_override or extract_year_from_text(case_text)
        if year and case_num:
            case_no = f"{year}-{case_num}"
            decision_date = year
        else:
            case_no = None
            decision_date = year
    else:
        # Format 1: Original "● 사건번호: CA##-#####" format
        # Extract case number
        case_no = None
        m = CASE_NO_RE.search(case_text)
        if m:
            case_no = _normalize_case_no(m.group(1).strip())

        # Extract case name (title)
        title = None
        m = CASE_NAME_RE.search(case_text)
        if m:
            title = m.group(1).strip()

        decision_date = None
        # Try to infer year from case_no when explicit decision date is missing
        if case_no:
            year_m = re.match(r"CA([0-9I]{2})", case_no)
            if year_m:
                yy = year_m.group(1).replace("I", "1")
                if yy.isdigit():
                    decision_date = f"20{yy}"
        if not decision_date:
            decision_date = extract_year_from_text(case_text)

    # Extract sections (common to both formats)
    # 1. Case overview (사건 개요 or 사건개요 or 분쟁개요)
    overview = extract_section(case_text, SECTION_OVERVIEW_RE, SECTION_PARTIES_RE)
    if not overview:
        # Try alternative: overview might be combined with parties section
        overview = extract_section(case_text, SECTION_OVERVIEW_RE, SECTION_JUDGMENT_RE)
        # Also try "분쟁개요" or "1 분쟁개요" pattern for format2
        if not overview:
            alt_overview_re = re.compile(r"(?:^|\n|\s)\s*(?:1\s*[.)]?\s*)?분쟁개요", re.MULTILINE)
            overview = extract_section(case_text, alt_overview_re, SECTION_PARTIES_RE)
    if not overview and case_type == 'format3':
        overview = extract_section(case_text, SECTION_OVERVIEW_KOR_RE, SECTION_PARTIES_KOR_RE)

    # 2. Parties' claims (당사자 주장 or 양 당사자 주장)
    parties_claim = extract_section(case_text, SECTION_PARTIES_RE, SECTION_JUDGMENT_RE)
    if not parties_claim:
        # Try "양 당사자 주장" or "2. 당사자 주장"
        alt_parties_re = re.compile(r"(?:^|\n|\s)\s*(?:2\s*(?:[.)])\s*)?양?\s*당사자\s*주장", re.MULTILINE)
        parties_claim = extract_section(case_text, alt_parties_re, SECTION_JUDGMENT_RE)
        # Try "2. 조정결정" or "3. 조정결정" for format2
        if not parties_claim:
            alt_judgment_re = re.compile(
                r"(?:^|\n|\s)\s*(?:2|3|4)\s*(?:[.)])\s*(?:조정결정|조정\s*결과|합의\s*권고|합의권고|사무국\s*권고)",
                re.MULTILINE,
            )
            parties_claim = extract_section(case_text, alt_parties_re, alt_judgment_re)
    if not parties_claim and case_type == 'format3':
        parties_claim = extract_section(case_text, SECTION_PARTIES_KOR_RE, SECTION_JUDGMENT_KOR_RE)

    # If parties_claim is empty, use overview
    if not parties_claim and overview:
        parties_claim = overview

    # 3. Judgment section (조정부의 판단 or 조정결정 or 합의 권고)
    judgment_section = extract_section(case_text, SECTION_JUDGMENT_RE, SECTION_RESULT_RE)
    if not judgment_section:
        # Try "조정결정" or "합의 권고" for format2
        alt_judgment_re = re.compile(
            r"(?:^|\n|\s)\s*(?:2|3|4)\s*(?:[.)])\s*(?:조정결정|조정\s*결과|합의\s*권고|합의권고|사무국\s*권고)",
            re.MULTILINE,
        )
        judgment_section = extract_section(case_text, alt_judgment_re, SECTION_RESULT_RE)
    if not judgment_section and case_type == 'format3':
        judgment_section = extract_section(case_text, SECTION_JUDGMENT_KOR_RE, SECTION_RESULT_KOR_RE)

    # Extract law section if present (optional for ECMC)
    law_section = ""
    if judgment_section:
        law_start_re = re.compile(
            r"(?:^|\n|\s)\s*(?:가\s*\.\s*)?(적용법조|관련\s*법령|관련\s*법률)",
            re.MULTILINE,
        )
        law_end_re = re.compile(r"(?:^|\n)\s*[나-하]\s*\.", re.MULTILINE)
        start_m = law_start_re.search(judgment_section)
        if start_m:
            end_m = law_end_re.search(judgment_section, start_m.end())
            if end_m:
                law_section = judgment_section[start_m.end():end_m.start()].strip()
                judgment_section = (
                    judgment_section[:start_m.start()] + "\n" + judgment_section[end_m.start():]
                ).strip()
            else:
                law_section = judgment_section[start_m.end():].strip()
                judgment_section = judgment_section[:start_m.start()].strip()
        if not law_section:
            law_section = extract_section(case_text, law_start_re, law_end_re)

    # Extract decision (주 문) and reasoning (이 유 or 가. 이유) from judgment section
    decision = ""
    reasoning = ""

    if judgment_section:
        # Decision is between "주 문" and "이 유"
        decision = extract_section(judgment_section, DECISION_MARKER_RE, REASONING_MARKER_RE)
        # Also try finding just the judgment section content as decision for format2
        if not decision:
            # For format2, the judgment section itself might be the decision
            decision = judgment_section

        # Reasoning is after "이 유" or "가. 이유"
        reasoning = extract_section(judgment_section, REASONING_MARKER_RE)
        if not reasoning:
            # Try "가. 이유" pattern for format2
            alt_reasoning_re = re.compile(r"(?:^|\n|\s)\s*가\s*\.\s*이유", re.MULTILINE)
            reasoning = extract_section(judgment_section, alt_reasoning_re)
        if not reasoning:
            # Some cases use "판 단" instead of "이 유"
            alt_reasoning_re = re.compile(r"(?:^|\n|\s)\s*판\s*단\s*(?:\n|$)|\s판\s*단\s", re.MULTILINE)
            reasoning = extract_section(judgment_section, alt_reasoning_re)
        if not reasoning:
            # Fallback: include the whole judgment section when no explicit marker exists.
            reasoning = judgment_section
    else:
        # Fallback when explicit judgment section is missing but markers exist
        decision = extract_section(case_text, DECISION_MARKER_RE, REASONING_MARKER_RE)
        reasoning = extract_section(case_text, REASONING_MARKER_RE)
        if not reasoning:
            alt_reasoning_re = re.compile(r"(?:^|\n|\s)\s*판\s*단\s*(?:\n|$)|\s판\s*단\s", re.MULTILINE)
            reasoning = extract_section(case_text, alt_reasoning_re)
        if decision or reasoning:
            judgment_section = case_text

    if not reasoning and decision:
        reasoning = decision

    return {
        "title": title,
        "case_no": case_no,
        "decision_date": decision_date,
        "decision": decision,
        "parties_claim": parties_claim,
        "judgment": reasoning,  # ECMC "이 유" maps to KCA "judgment"
        "law": law_section or "",  # ECMC law sections are optional
    }


def main():
    ap = argparse.ArgumentParser(
        description="Parse ECMC case data from merged text file",
        epilog="""
Examples:
  # Parse ECMC merged text
  python %(prog)s --input kjw/data/preprocess/ecmc_merged_elements.txt --output kjw/data/preprocess/ecmc_final_cases.jsonl

  # With light preprocessing
  python %(prog)s --input kjw/data/preprocess/ecmc_merged_elements.txt --output kjw/data/preprocess/ecmc_final_cases.jsonl --preprocess
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--input", required=True, help="Input merged text file")
    ap.add_argument("--output", required=True, help="Output JSONL file")
    ap.add_argument("--preprocess", action="store_true", help="Apply light preprocessing")
    ap.add_argument("--chunks", help="Optional output file for chunks")
    args = ap.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        return

    # Read input
    print(f"\n[PARSING ECMC CASES]")
    print(f"  Input: {input_path}")
    merged_text = input_path.read_text(encoding="utf-8")
    merged_text = sanitize_masked_text(merged_text)
    print(f"  Loaded: {len(merged_text):,} characters")

    # Apply preprocessing if requested
    if args.preprocess:
        print(f"  Applying light preprocessing...")
        merged_text = preprocess_light(merged_text)

    # Split into cases
    cases = split_into_cases(merged_text)
    print(f"  Found {len(cases)} cases")

    # Parse each case
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Track year and case number for format2 cases
    current_year = None
    last_case_num = {}  # year -> last_case_num

    with output_path.open("w", encoding="utf-8") as f_cases:
        for idx, (case_text, case_type) in enumerate(cases, 1):
            # For format2, extract year and case number
            year_override = None
            case_num_override = None

            if case_type == 'format2':
                # Extract case number from "사례 N"
                m = CASE_NUM_SPLIT_RE.search(case_text)
                if m:
                    case_num_from_text = int(m.group(1))

                    # Extract year from text
                    year_from_text = extract_year_from_text(case_text)

                    # If we found a year, use it
                    if year_from_text:
                        current_year = year_from_text

                    # Detect year change: if case number resets to 1, year likely changed
                    if current_year and case_num_from_text == 1:
                        # Check if we had a previous case in this year
                        if current_year in last_case_num:
                            # Year likely changed, but we need to detect new year from text
                            if year_from_text and year_from_text != current_year:
                                current_year = year_from_text

                    # Update tracking
                    if current_year:
                        last_case_num[current_year] = case_num_from_text

                    year_override = current_year
                    case_num_override = case_num_from_text

            fields = parse_case_fields(case_text, case_type, year_override, case_num_override)
            case_text = sanitize_masked_text(case_text)
            for key in ("title", "decision", "parties_claim", "judgment", "law"):
                if fields.get(key):
                    fields[key] = sanitize_masked_text(fields[key])

            # Apply preprocessing to fields if requested
            if args.preprocess:
                for key in ["decision", "parties_claim", "judgment"]:
                    if fields.get(key):
                        fields[key] = preprocess_light(fields[key])

            record = {
                "source": "ecmc_merged",
                "agency": "ecmc",
                "case_index": idx,
                **fields,
                "raw_text": case_text,
            }

            f_cases.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"  ✓ Generated: {output_path.name} ({len(cases)} cases)")

    # Generate chunks if requested
    if args.chunks:
        chunks_path = Path(args.chunks)

        # Reset year tracking for chunks generation
        current_year = None
        last_case_num = {}

        with chunks_path.open("w", encoding="utf-8") as f_chunks:
            for idx, (case_text, case_type) in enumerate(cases, 1):
                # For format2, extract year and case number (same logic as above)
                year_override = None
                case_num_override = None

                if case_type == 'format2':
                    m = CASE_NUM_SPLIT_RE.search(case_text)
                    if m:
                        case_num_from_text = int(m.group(1))
                        year_from_text = extract_year_from_text(case_text)

                        if year_from_text:
                            current_year = year_from_text

                        if current_year and case_num_from_text == 1:
                            if current_year in last_case_num:
                                if year_from_text and year_from_text != current_year:
                                    current_year = year_from_text

                        if current_year:
                            last_case_num[current_year] = case_num_from_text

                        year_override = current_year
                        case_num_override = case_num_from_text

                fields = parse_case_fields(case_text, case_type, year_override, case_num_override)
                case_text = sanitize_masked_text(case_text)
                for key in ("title", "decision", "parties_claim", "judgment", "law"):
                    if fields.get(key):
                        fields[key] = sanitize_masked_text(fields[key])

                shared = {
                    "source": "ecmc_merged",
                    "agency": "ecmc",
                    "case_index": idx,
                    "case_no": fields.get("case_no"),
                    "decision_date": fields.get("decision_date"),
                }

                # Create chunks for decision, parties_claim, judgment, and law (when present)
                for chunk_type in ["decision", "parties_claim", "judgment", "law"]:
                    text = fields.get(chunk_type) or ""
                    if args.preprocess:
                        text = preprocess_light(text)
                    text = text.strip()

                    if not text:
                        continue

                    chunk = {
                        **shared,
                        "chunk_type": chunk_type,
                        "text": text,
                    }
                    f_chunks.write(json.dumps(chunk, ensure_ascii=False) + "\n")

        # Count chunks
        with chunks_path.open("r", encoding="utf-8") as f:
            num_chunks = sum(1 for _ in f)
        print(f"  ✓ Generated: {chunks_path.name} ({num_chunks} chunks)")

    print(f"\n[DONE]")
    print(f"  Output: {output_path}")


if __name__ == "__main__":
    main()
