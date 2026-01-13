#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Merge all split PDF parsed results and parse as a single document

This script:
1. Finds all kca_2016_의료-XXX-YYY directories
2. Reads merged_elements.txt from each in order
3. Merges them into a single text
4. Parses cases from the merged text
5. Outputs to kjw/data/preprocess/

Usage:
  conda activate crawling
  python kjw/scripts/merge_and_parse_all_cases.py --preprocess=none
  python kjw/scripts/merge_and_parse_all_cases.py --preprocess=rag
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import parsing functions from existing script
import sys
sys.path.insert(0, str(Path(__file__).parent))

# Copy regex patterns and functions from upstage_parse_to_case_jsonl.py
# Match case headers like "사례 06", "사 01\n례", or "사\n례\n01"
# Use explicit whitespace/newline handling to avoid matching body text.
CASE_SPLIT_RE = re.compile(
    r"(?m)^(?:"
    r"사[ \t]*례[ \t]*\d+(?![).])"
    r"|사[ \t]*\d+(?![).])[ \t]*\n[ \t]*례"
    r"|사[ \t]*\n[ \t]*례[ \t]*\n[ \t]*\d+(?![).])"
    r")"
)
CASE_NO_LINE_RE = re.compile(r"사건\s*번호")
CASE_HEADER_TOKEN_RE = re.compile(r"^\s*(?:사례|사)\b")
CASE_SEQ_RE = re.compile(r"^\s*\d{1,2}\s*$")

CASE_NO_RE = re.compile(
    r"(?:\[?사건\s*번호\s*[:：]?\s*)?(\d{4}[가-힣A-Za-z]{0,10}\d+)\]?"
)

DECISION_DATE_RE = re.compile(
    r"(?:\[?결정\s*일자\s*[:：]?\s*)?(\d{4}\.?\s*\d{1,2}\.?\s*\d{1,2})\]?"
)

# Title can span multiple lines until [사건번호] or section markers
TITLE_RE = re.compile(
    r"(?m)^사\s*례\s*\d+\s*\n(.+?)(?=\[사건번호|\n+(?:주\s*문|합의\s*결과|사건\s*개요))",
    re.DOTALL
)
# Some cases place the title after the case number line
TITLE_AFTER_CASE_NO_RE = re.compile(
    r"(?m)^(?:\[[^\]]+\]\s*)?사건\s*번호[^\n]*\n(.+?)(?=\n+(?:주\s*문|합의\s*결과|사건\s*개요))",
    re.DOTALL
)

# "주문" or "합의결과" - decision/settlement section
SECTION_ORDER_RE = re.compile(r"(?:주\s*문|문\s*\n+\s*주|합의\s*결과)")
SECTION_REASON_RE = re.compile(r"이\s*유|유\s*\n+\s*이")
# "N. 당사자 주장/기초 사실/사건 개요" - subsection within "이유"
SECTION_PARTIES_CLAIM_RE = re.compile(
    r"(?m)^\d+\s*\.\s*(?:당사자\s*의?\s*주장|기초\s*사실|사건\s*개요)"
)
# "N. 판단" - allow split headers like "2. 판" or "2. 판 단"
SECTION_JUDGMENT_RE = re.compile(r"(?m)^\d+\s*\.\s*판(?:\s*단)?")
# "[관련 법령]" - related laws section
LAW_RE = re.compile(r"\[관련\s*법령\]\s*(.+?)(?=\n\n|\n이상과|$)", re.DOTALL)
END_MARKER_RE = re.compile(
    r"이상\s*과\s*같은\s*이유로\s*주문\s*과\s*같이\s*결정한다\.?",
    re.DOTALL,
)


def preprocess_for_rag(text: str) -> str:
    """RAG 시스템에 최적화된 텍스트 전처리"""
    text = re.sub(r'(?:\x1a|\\u001a|\\x1a)+', '[MASKED]', text)
    text = re.sub(r'\n*=== PAGE \d+ ===\n*', '\n', text)
    text = re.sub(r'\d+\s+\d{4}\s+의료분쟁조정\s+사례집', '', text)
    text = re.sub(r'제\d+장\s+분쟁조정\s+주요\s+사례\s+\d+', '', text)
    text = re.sub(r'내과분야\s*\n*∣[^\n]*\n*', '', text)
    text = re.sub(r'([가-힣])\n([가-힣]{1,2})\s', r'\1\2 ', text)
    text = text.replace('※', '[주]')
    text = text.replace('∣', '|')
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    text = _strip_noise_lines(text)
    text = text.strip()
    return text


def preprocess_light(text: str) -> str:
    """경량 전처리: 노이즈만 제거"""
    text = re.sub(r'(?:\x1a|\\u001a|\\x1a)+', '[MASKED]', text)
    text = re.sub(r'\n*=== PAGE \d+ ===\n*', '\n', text)
    text = re.sub(r'\d+\s+\d{4}\s+의료분쟁조정\s+사례집', '', text)
    text = re.sub(r'제\d+장\s+분쟁조정\s+주요\s+사례\s+\d+', '', text)
    text = re.sub(r'내과분야\s*\n*∣[^\n]*\n*', '', text)
    text = text.replace('∣', '|')
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = _strip_noise_lines(text)
    text = text.strip()
    return text


def sanitize_masked_text(text: str) -> str:
    return re.sub(r'(?:\x1a|\\u001a|\\x1a)+', '[MASKED]', text)


def _strip_noise_lines(text: str) -> str:
    noise_chars = set("사례주문유이집단분쟁조정")
    lines = []
    for line in text.split('\n'):
        s = line.strip()
        if not s:
            continue
        if re.fullmatch(r'\d{1,3}', s):
            continue
        if re.fullmatch(r'사례\s*\d+', s):
            continue
        if re.fullmatch(r'사\s*\d+', s):
            continue
        if re.fullmatch(r'=== PAGE \d+ ===', s):
            continue
        if '사례집' in s:
            continue
        if re.match(r'^제\d+장', s):
            continue
        if re.match(r'^(일반|의료|집단)분쟁조정', s):
            continue
        if re.match(r'^사례\\(.*\\)', s):
            continue
        if re.fullmatch(r'\\|\\S+', s):
            continue
        if 1 <= len(s) <= 4 and all(ch in noise_chars for ch in s):
            continue
        lines.append(s)
    return '\n'.join(lines)


def _slice_between(text: str, start_pat: re.Pattern, end_pat: Optional[re.Pattern]) -> str:
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
    """Split merged text into individual cases"""
    def _find_case_no_header_starts(text: str) -> List[int]:
        lines = text.splitlines(keepends=True)
        offsets: List[int] = []
        pos = 0
        for line in lines:
            offsets.append(pos)
            pos += len(line)

        idxs: List[int] = []
        for i, line in enumerate(lines):
            if not CASE_NO_LINE_RE.search(line):
                continue
            start_idx = None
            if CASE_HEADER_TOKEN_RE.match(line):
                start_idx = i
            else:
                for j in range(i - 1, max(-1, i - 9), -1):
                    if CASE_HEADER_TOKEN_RE.match(lines[j]):
                        start_idx = j
                        break
            if start_idx is None:
                for j in range(i - 1, max(-1, i - 9), -1):
                    if CASE_SEQ_RE.match(lines[j]):
                        if any(re.match(r"^\s*사\s*$", lines[k]) for k in range(j + 1, i + 1)):
                            start_idx = j
                            break
            if start_idx is not None:
                idxs.append(offsets[start_idx])
        return idxs

    def _find_loose_case_starts(text: str) -> List[int]:
        lines = text.splitlines(keepends=True)
        offsets: List[int] = []
        pos = 0
        for line in lines:
            offsets.append(pos)
            pos += len(line)

        idxs: List[int] = []
        num_re = re.compile(r"^\s*\d{1,2}\s*$")
        sa_re = re.compile(r"^\s*사\s*$")
        rye_re = re.compile(r"^\s*례\s*$")
        case_no_re = re.compile(r"^\s*사건\s*번호")

        for i, line in enumerate(lines):
            if not num_re.match(line):
                continue
            sa_idx = None
            for j in range(i + 1, min(len(lines), i + 4)):
                if sa_re.match(lines[j]):
                    sa_idx = j
                    break
            if sa_idx is None:
                continue
            rye_idx = None
            has_case_no = False
            for k in range(sa_idx + 1, min(len(lines), sa_idx + 8)):
                if case_no_re.match(lines[k]):
                    has_case_no = True
                if rye_re.match(lines[k]):
                    rye_idx = k
                    break
            if rye_idx is not None and has_case_no:
                idxs.append(offsets[i])
        return idxs

    idxs_set = set()
    for m in CASE_SPLIT_RE.finditer(merged_text):
        lookahead = merged_text[m.end():m.end() + 600]
        if re.search(r"(사건\s*번호|결정\s*일자)", lookahead):
            idxs_set.add(m.start())
    for idx in _find_case_no_header_starts(merged_text):
        idxs_set.add(idx)
    for idx in _find_loose_case_starts(merged_text):
        idxs_set.add(idx)

    if not idxs_set:
        return [merged_text.strip()] if merged_text.strip() else []

    idxs = sorted(idxs_set)
    idxs.append(len(merged_text))

    cases = []
    for i in range(len(idxs) - 1):
        chunk = merged_text[idxs[i]:idxs[i + 1]].strip()
        if chunk:
            cases.append(chunk)
    return cases


def trim_case_tail(case_text: str) -> str:
    """Trim trailing book/cover pages after a case-end marker."""
    matches = list(END_MARKER_RE.finditer(case_text))
    if not matches:
        return case_text
    end = matches[-1].end()
    return case_text[:end].strip()


def parse_case_fields(case_text: str) -> Dict[str, Any]:
    """Parse individual case fields"""
    def _clean_title(text: str) -> str:
        text = re.sub(r'^\[[^\]]+\]\s*', '', text)
        text = re.sub(r'사건\s*번호[^\n]*', '', text)
        text = re.sub(r'결정\s*일자[^\n]*', '', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    # Extract title - can span multiple lines
    title = None
    m = TITLE_RE.search(case_text)
    if m:
        title = re.sub(r'\s+', ' ', m.group(1).strip())
        if "사건번호" in title or "결정일자" in title:
            m2 = TITLE_AFTER_CASE_NO_RE.search(case_text)
            if m2:
                title = re.sub(r'\s+', ' ', m2.group(1).strip())
        title = _clean_title(title)
    else:
        m = TITLE_AFTER_CASE_NO_RE.search(case_text)
        if m:
            title = _clean_title(m.group(1))

    # Extract case number
    case_no = None
    m = CASE_NO_RE.search(case_text)
    if m:
        case_no = re.sub(r"\s+", "", m.group(1))

    # Extract decision date - normalize format to YYYY.MM.DD
    decision_date = None
    m = DECISION_DATE_RE.search(case_text)
    if m:
        date_str = re.sub(r"\s+", "", m.group(1))
        if "." not in date_str and len(date_str) == 8:
            decision_date = f"{date_str[:4]}.{date_str[4:6]}.{date_str[6:8]}"
        else:
            decision_date = date_str.rstrip(".")

    # Extract main sections
    decision = _slice_between(case_text, SECTION_ORDER_RE, SECTION_REASON_RE)

    parties_claim = ""
    judgment = ""
    law = ""

    if SECTION_PARTIES_CLAIM_RE.search(case_text):
        parties_claim = _slice_between(case_text, SECTION_PARTIES_CLAIM_RE, SECTION_JUDGMENT_RE)

    if SECTION_JUDGMENT_RE.search(case_text):
        # Extract judgment text (from "2. 판단" to "[관련 법령]" or end)
        m_law = LAW_RE.search(case_text)
        if m_law:
            # If there's a law section, judgment ends before it
            judgment_end = m_law.start()
            m_judgment = SECTION_JUDGMENT_RE.search(case_text)
            if m_judgment:
                judgment = case_text[m_judgment.end():judgment_end].strip()
            # Extract law section
            law = m_law.group(1).strip()
        else:
            # No law section, extract to end
            judgment = _slice_between(case_text, SECTION_JUDGMENT_RE, None)

    return {
        "title": title,
        "case_no": case_no,
        "decision_date": decision_date,
        "decision": decision,
        "parties_claim": parties_claim,
        "judgment": judgment,
        "law": law,
    }


def infer_agency_from_filename(name: str) -> str:
    n = name.lower()
    if "kca" in n:
        return "kca"
    if "eca" in n or "ecrc" in n:
        return "eca"
    if "kcdrc" in n:
        return "kcdrc"
    return "unknown"


def write_cases_and_chunks(
    cases: List[str],
    output_dir: Path,
    preprocess_func,
    agency: str,
    output_prefix: str,
    dedup_case_no: bool,
) -> None:
    cases_path = output_dir / f"{output_prefix}_cases.jsonl"
    chunks_path = output_dir / f"{output_prefix}_chunks.jsonl"
    seen_case_no = set()
    deduped = 0
    out_idx = 0

    with cases_path.open("w", encoding="utf-8") as f_cases, \
         chunks_path.open("w", encoding="utf-8") as f_chunks:
        for case_text in cases:
            case_text = trim_case_tail(case_text)
            fields = parse_case_fields(case_text)
            case_text = sanitize_masked_text(case_text)
            for key in ("title", "decision", "parties_claim", "judgment", "law"):
                if fields.get(key):
                    fields[key] = sanitize_masked_text(fields[key])
            case_no = fields.get("case_no")
            if dedup_case_no and case_no:
                if case_no in seen_case_no:
                    deduped += 1
                    continue
                seen_case_no.add(case_no)

            # Apply preprocessing if enabled
            if preprocess_func:
                fields["decision"] = preprocess_func(fields.get("decision", ""))
                fields["parties_claim"] = preprocess_func(fields.get("parties_claim", ""))
                fields["judgment"] = preprocess_func(fields.get("judgment", ""))
                fields["law"] = preprocess_func(fields.get("law", ""))
                preprocessed_raw = preprocess_func(case_text)
            else:
                preprocessed_raw = case_text

            out_idx += 1
            record = {
                "source": "kca_merged",
                "agency": agency,
                "case_index": out_idx,
                **fields,
                "raw_text": preprocessed_raw,
            }
            f_cases.write(json.dumps(record, ensure_ascii=False) + "\n")

            # Write chunks
            shared = {
                "source": "kca_merged",
                "agency": agency,
                "case_index": out_idx,
                "case_no": fields.get("case_no"),
                "decision_date": fields.get("decision_date"),
            }
            for chunk_type in ("decision", "parties_claim", "judgment", "law"):
                txt = fields.get(chunk_type) or ""
                txt = txt.strip()
                if not txt:
                    continue
                f_chunks.write(json.dumps({**shared, "chunk_type": chunk_type, "text": txt}, ensure_ascii=False) + "\n")

    print(f"  ✓ Generated: {cases_path.name} ({out_idx} cases)")
    if dedup_case_no:
        print(f"  ✓ Deduplicated by case_no: {deduped} removed")

    # Count chunks
    with chunks_path.open("r", encoding="utf-8") as f:
        num_chunks = sum(1 for _ in f)
    print(f"  ✓ Generated: {chunks_path.name} ({num_chunks} chunks)")


def main():
    ap = argparse.ArgumentParser(
        description="Merge all split PDF parsed results and parse as a single document",
        epilog="""
Examples:
  # Process KCA data with RAG preprocessing
  python %(prog)s --kca --preprocess=rag

  # Process ECMC data with light preprocessing
  python %(prog)s --ecmc --preprocess=light

  # Process KCDRC data without preprocessing
  python %(prog)s --kcdrc --preprocess=none

  # Advanced: custom pattern and output
  python %(prog)s --pattern "custom_*" --output-prefix custom_final --preprocess=rag
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # Agency selection (mutually exclusive)
    agency_group = ap.add_mutually_exclusive_group()
    agency_group.add_argument("--kca", action="store_true",
                             help="Process KCA (한국소비자원) data - pattern: kca_*, output: kca_final")
    agency_group.add_argument("--ecmc", action="store_true",
                             help="Process ECMC (전기통신분쟁조정위원회) data - pattern: ecmc_*, output: ecmc_final")
    agency_group.add_argument("--kcdrc", action="store_true",
                             help="Process KCDRC (한국저작권위원회) data - pattern: kcdrc_*, output: kcdrc_final")

    # Directory and file options
    ap.add_argument("--parsed-dir", default="kjw/data/raw/parsed",
                    help="Directory containing parsed subdirectories (default: kjw/data/raw/parsed)")
    ap.add_argument("--output-dir", default="kjw/data/preprocess",
                    help="Output directory (default: kjw/data/preprocess)")

    # Advanced options (override automatic settings from --kca/--ecmc/--kcdrc)
    ap.add_argument("--output-prefix",
                    help="Output prefix for JSONL files (overrides automatic setting)")
    ap.add_argument("--pattern",
                    help="Pattern to match directories (overrides automatic setting)")
    ap.add_argument("--merged-input",
                    help="Use an existing merged_elements.txt file instead of merging directories")
    ap.add_argument("--agency",
                    help="Override agency code (e.g., kca, ecmc, kcdrc). If omitted, inferred from inputs.")

    # Processing options
    ap.add_argument("--preprocess", choices=["none", "light", "rag"], default="none",
                    help="Preprocessing mode")
    ap.add_argument("--dedup-case-no", action="store_true",
                    help="Drop duplicated case_no records (keep first occurrence)")
    args = ap.parse_args()

    # Determine pattern, output_prefix, and agency based on flags
    if args.kca:
        pattern = args.pattern or "kca_*"
        output_prefix = args.output_prefix or "kca_final"
        agency = args.agency or "kca"
        parsed_subdir = ""  # kca files are directly under parsed/
    elif args.ecmc:
        pattern = args.pattern or "ecmc_*"
        output_prefix = args.output_prefix or "ecmc_final"
        agency = args.agency or "ecmc"
        parsed_subdir = "ecmc"  # ecmc files are under parsed/ecmc/
    elif args.kcdrc:
        pattern = args.pattern or "kcdrc_*"
        output_prefix = args.output_prefix or "kcdrc_final"
        agency = args.agency or "kcdrc"
        parsed_subdir = "kcdrc"  # kcdrc files are under parsed/kcdrc/
    else:
        # No agency flag provided - use manual pattern/prefix or defaults
        if not args.pattern and not args.merged_input:
            print("Error: Please specify --kca, --ecmc, --kcdrc, or provide --pattern")
            return
        pattern = args.pattern or "kca_*"
        output_prefix = args.output_prefix or "kca_final"
        agency = args.agency or infer_agency_from_filename(pattern)
        parsed_subdir = ""

    # Update parsed_dir if subdir is specified
    parsed_dir = Path(args.parsed_dir)
    if parsed_subdir:
        parsed_dir = parsed_dir / parsed_subdir

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Select preprocessing function
    preprocess_func = None
    if args.preprocess == "rag":
        preprocess_func = preprocess_for_rag
    elif args.preprocess == "light":
        preprocess_func = preprocess_light

    if args.merged_input:
        merged_path = Path(args.merged_input)
        if not merged_path.exists():
            print(f"Merged input not found: {merged_path}")
            return
        full_merged_text = merged_path.read_text(encoding="utf-8")
        print(f"\n[PARSE MERGED INPUT]")
        print(f"  Loaded: {merged_path} ({len(full_merged_text):,} chars)")
        cases = split_into_cases(full_merged_text)
        print(f"  Found {len(cases)} cases")
        write_cases_and_chunks(
            cases=cases,
            output_dir=output_dir,
            preprocess_func=preprocess_func,
            agency=agency,
            output_prefix=output_prefix,
            dedup_case_no=args.dedup_case_no,
        )
        print(f"\n[DONE]")
        print(f"  Output directory: {output_dir}")
        return

    # Find all matching directories
    dirs = sorted(parsed_dir.glob(pattern))
    if not dirs:
        print(f"No directories found matching pattern: {pattern}")
        print(f"  Searched in: {parsed_dir}")
        return

    print(f"\n[MERGING AND PARSING]")
    print(f"  Agency: {agency}")
    print(f"  Pattern: {pattern}")
    print(f"  Found {len(dirs)} directories")
    print(f"  Preprocessing mode: {args.preprocess}")
    print()

    # Merge all merged_elements.txt files
    merged_text_parts = []
    for d in dirs:
        merged_file = d / "merged_elements.txt"
        if not merged_file.exists():
            print(f"  ⚠ Skipped: {d.name} (no merged_elements.txt)")
            continue

        text = merged_file.read_text(encoding="utf-8")
        merged_text_parts.append(text)
        print(f"  ✓ Loaded: {d.name} ({len(text):,} chars)")

    if not merged_text_parts:
        print("\n  ✗ No merged_elements.txt files found")
        return

    # Join all texts
    full_merged_text = "\n\n".join(merged_text_parts)
    print(f"\n  Total merged text: {len(full_merged_text):,} characters")

    # Save merged text
    merged_output = output_dir / f"{agency}_merged_elements.txt"
    merged_output.write_text(full_merged_text, encoding="utf-8")
    print(f"  ✓ Saved merged text: {merged_output}")

    if args.preprocess == "rag":
        print(f"  Applying RAG preprocessing...")
    elif args.preprocess == "light":
        print(f"  Applying light preprocessing...")

    # Split into cases
    cases = split_into_cases(full_merged_text)
    print(f"\n  Found {len(cases)} cases")

    # Parse and save
    write_cases_and_chunks(
        cases=cases,
        output_dir=output_dir,
        preprocess_func=preprocess_func,
        agency=agency,
        output_prefix=output_prefix,
        dedup_case_no=args.dedup_case_no,
    )

    print(f"\n[DONE]")
    print(f"  Output directory: {output_dir}")


if __name__ == "__main__":
    main()
