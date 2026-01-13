#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Upstage Document Parse -> save -> merge elements -> case-level jsonl

IMPORTANT: parsing(API 호출)과 전처리는 분리되어야 합니다!
- parsing: API 호출하여 response.json 저장 (비용 발생!)
- 전처리: 기존 response.json을 읽어서 merged_elements, cases, chunks 생성 (비용 없음)

Usage:
  conda activate crawling

  # Both parsing and processing (default) - API 호출 + 전처리
  python kjw/scripts/upstage_parse_to_case_jsonl.py --pdf kca_2016_의료-001-100.pdf

  # Only parse (API call, save response.json) - 비용 발생!
  python kjw/scripts/upstage_parse_to_case_jsonl.py --pdf kca_2016_의료-001-100.pdf --parse-only

  # Only process (read existing response.json, no API call) - 비용 없음
  python kjw/scripts/upstage_parse_to_case_jsonl.py --pdf kca_2016_의료-001-100.pdf --process-only

  # Process all existing parsed directories - 비용 없음
  python kjw/scripts/upstage_parse_to_case_jsonl.py --process-only

Input:
  kjw/data/raw/split/<pdf>

Output:
  kjw/data/raw/parsed/<stem>/
    - response.json            (raw API response)
    - merged_elements.txt      (elements merged to reading order)
    - cases.jsonl              (1 line per case, includes decision/parties_claim/judgment fields)
    - chunks.jsonl             (1 line per chunk (decision/parties_claim/judgment) with shared metadata)
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv


# -----------------------------
# ENV GUARD
# -----------------------------
def assert_crawling_env() -> None:
    env = os.environ.get("CONDA_DEFAULT_ENV", "")
    if env != "crawling":
        raise RuntimeError(
            f"[ENV GUARD] CONDA_DEFAULT_ENV={env!r}\n"
            "You MUST run in miniconda env 'crawling'. DO NOT install anything in 'base'.\n"
            "=> conda activate crawling"
        )


# -----------------------------
# API
# -----------------------------
UPSTAGE_URL = "https://api.upstage.ai/v1/document-digitization"


def call_upstage_parse(pdf_path: Path, api_key: str, output_formats: List[str]) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}"}
    # IMPORTANT: output_formats should be JSON string for form-data robustness
    data = {
        "model": "document-parse-nightly",
        "ocr": "auto",
        "chart_recognition": True,
        "coordinates": True,
        "output_formats": json.dumps(output_formats),
        "base64_encoding": json.dumps(["figure"]),
    }

    with pdf_path.open("rb") as f:
        files = {"document": f}
        resp = requests.post(UPSTAGE_URL, headers=headers, files=files, data=data, timeout=600)
    resp.raise_for_status()
    return resp.json()


# -----------------------------
# ELEMENT NORMALIZATION
# -----------------------------
@dataclass
class NormElement:
    page: int
    top: float
    left: float
    text: str
    raw: Dict[str, Any]


def _bbox_to_tl(bbox: Any) -> Tuple[float, float]:
    """
    Convert bbox/coordinates to (top, left).
    Tries to support multiple shapes:
      - [x1,y1,x2,y2]
      - [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
      - [{"x":..,"y":..}, {"x":..,"y":..}, ...] (Upstage format)
      - {"x1":..,"y1":..,"x2":..,"y2":..}
      - {"points":[...]}
    If unknown, returns (inf, inf).
    """
    try:
        if bbox is None:
            return (float("inf"), float("inf"))

        # dict forms
        if isinstance(bbox, dict):
            if all(k in bbox for k in ("x1", "y1")):
                return (float(bbox["y1"]), float(bbox["x1"]))
            if "points" in bbox and isinstance(bbox["points"], list) and bbox["points"]:
                pts = bbox["points"]
                xs = [p[0] for p in pts if isinstance(p, (list, tuple)) and len(p) >= 2]
                ys = [p[1] for p in pts if isinstance(p, (list, tuple)) and len(p) >= 2]
                if xs and ys:
                    return (float(min(ys)), float(min(xs)))
            # fallthrough
            return (float("inf"), float("inf"))

        # list forms
        if isinstance(bbox, list):
            # [x1,y1,x2,y2]
            if len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox):
                x1, y1, _, _ = bbox
                return (float(y1), float(x1))

            # [[x,y], ...] or [{"x":..,"y":..}, ...] (Upstage format)
            if bbox:
                xs, ys = [], []
                for p in bbox:
                    # Handle list/tuple format: [x, y]
                    if isinstance(p, (list, tuple)) and len(p) >= 2:
                        xs.append(p[0])
                        ys.append(p[1])
                    # Handle dict format: {"x": .., "y": ..} (Upstage)
                    elif isinstance(p, dict) and "x" in p and "y" in p:
                        xs.append(p["x"])
                        ys.append(p["y"])
                if xs and ys:
                    return (float(min(ys)), float(min(xs)))

        return (float("inf"), float("inf"))
    except Exception:
        return (float("inf"), float("inf"))


def extract_elements(resp: Dict[str, Any]) -> List[NormElement]:
    """
    Best-effort extraction of elements from Upstage response.
    Many document parsers return an `elements` list; if not present, fall back to other common layouts.
    """
    raw_elements = []
    if isinstance(resp.get("elements"), list):
        raw_elements = resp["elements"]
    elif isinstance(resp.get("pages"), list):
        # sometimes pages -> elements/blocks
        for p in resp["pages"]:
            if isinstance(p, dict):
                els = p.get("elements") or p.get("blocks") or []
                if isinstance(els, list):
                    raw_elements.extend(els)

    norm: List[NormElement] = []
    for el in raw_elements:
        if not isinstance(el, dict):
            continue

        # page
        page = el.get("page")
        if page is None:
            page = el.get("page_index")
            if isinstance(page, int):
                page = page + 1
        if page is None:
            page = el.get("page_no")
        if not isinstance(page, int):
            page = 1  # fallback

        # text - FIXED: handle Upstage API structure with nested content.text
        text = None
        # First, try Upstage API format: content.text
        if isinstance(el.get("content"), dict):
            text = el.get("content").get("text")
        # Fallback to direct text field
        if text is None:
            text = el.get("text")
        # Fallback to value field
        if text is None and isinstance(el.get("value"), str):
            text = el.get("value")
        if not isinstance(text, str):
            continue
        text = text.strip()
        if not text:
            continue

        # bbox / coordinates - FIXED: handle Upstage coordinates format
        bbox = el.get("bbox") or el.get("coordinates") or el.get("bounding_box") or el.get("polygon")
        top, left = _bbox_to_tl(bbox)

        norm.append(NormElement(page=page, top=top, left=left, text=text, raw=el))

    # sort by reading-ish order: page, top, left
    norm.sort(key=lambda x: (x.page, x.top, x.left))
    return norm


def merge_elements_to_text(elements: List[NormElement]) -> str:
    lines: List[str] = []
    last_page = None
    for el in elements:
        if last_page is None or el.page != last_page:
            if last_page is not None:
                lines.append("")  # page break
            lines.append(f"\n=== PAGE {el.page} ===\n")
            last_page = el.page
        lines.append(el.text)
    # normalize whitespace a bit (keep newlines)
    merged = "\n".join(lines)
    merged = re.sub(r"\n{3,}", "\n\n", merged)
    return merged.strip() + "\n"


# -----------------------------
# TEXT PREPROCESSING FOR RAG
# -----------------------------
def preprocess_for_rag(text: str) -> str:
    """
    RAG 시스템에 최적화된 텍스트 전처리
    - 페이지 마커 제거
    - 페이지 번호/헤더 제거
    - 문장 중간 개행 병합 (OCR 오류 수정)
    - 과도한 공백 정리
    - 특수문자 일부 정규화
    """
    # 1. 페이지 마커 제거
    text = re.sub(r'\n*=== PAGE \d+ ===\n*', '\n', text)

    # 2. 페이지 번호/헤더/푸터 제거
    text = re.sub(r'\d+\s+\d{4}\s+의료분쟁조정\s+사례집', '', text)
    text = re.sub(r'제\d+장\s+분쟁조정\s+주요\s+사례\s+\d+', '', text)
    text = re.sub(r'내과분야\s*\n*∣[^\n]*\n*', '', text)

    # 3. 문장 중간 개행 병합 (OCR 오류: "유\n방" -> "유방")
    # 한글-개행-한글(1~2자)-공백 패턴
    text = re.sub(r'([가-힣])\n([가-힣]{1,2})\s', r'\1\2 ', text)

    # 4. 특수 구두점 정규화 (의미 유지)
    text = text.replace('※', '[주]')  # 주석 표시
    text = text.replace('∣', '|')     # 구분자

    # 5. 과도한 개행 정리 (3개 이상 -> 2개)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 6. 다중 공백 제거 (2개 이상 -> 1개)
    text = re.sub(r' {2,}', ' ', text)

    # 7. 각 줄의 앞뒤 공백 제거
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(line for line in lines if line)

    # 8. 전체 앞뒤 공백 제거
    text = text.strip()

    return text


def preprocess_light(text: str) -> str:
    """
    경량 전처리: 노이즈만 제거, 구조 보존
    """
    # 페이지 마커 제거
    text = re.sub(r'\n*=== PAGE \d+ ===\n*', '\n', text)
    # 페이지 번호/헤더 제거
    text = re.sub(r'\d+\s+\d{4}\s+의료분쟁조정\s+사례집', '', text)
    text = re.sub(r'제\d+장\s+분쟁조정\s+주요\s+사례\s+\d+', '', text)
    text = re.sub(r'내과분야\s*\n*∣[^\n]*\n*', '', text)
    # 과도한 개행 정리
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    return text


# -----------------------------
# CASE SPLITTING (KCA/ECA/KCDRC style heuristic)
# -----------------------------
# Only match "사례 XX" pattern (more strict to avoid false splits)
# Match "사례 XX" but not "사례\n1. 기초 사실"
# Use [ \t]* (space/tab only) instead of \s* (includes newlines)
CASE_SPLIT_RE = re.compile(
    r"(?m)^사[ \t]*례[ \t]*\d+"
)

# Extract case number - support multiple formats:
# - [사건번호 2015일가27]
# - 사건번호: 2015일가27
# - 2015일가27 (standalone)
CASE_NO_RE = re.compile(
    r"(?:\[?사건\s*번호\s*[:：]?\s*)?(\d{4}[가-힣A-Za-z]{0,10}\d+)\]?"
)

# Extract decision date - support multiple formats:
# - [결정일자 20150511]
# - 결정일자: 2015.05.11
# - YYYYMMDD or YYYY.MM.DD
DECISION_DATE_RE = re.compile(
    r"(?:\[?결정\s*일자\s*[:：]?\s*)?(\d{4}\.?\s*\d{1,2}\.?\s*\d{1,2})\]?"
)

# Extract title - can span multiple lines until [사건번호] or section markers
TITLE_RE = re.compile(
    r"(?m)^사\s*례\s*\d+\s*\n(.+?)(?=\[사건번호|\n+(?:주\s*문|합의\s*결과|사건\s*개요))",
    re.DOTALL
)

# Section header patterns - handle various spacing and line breaks
# "주문" (decision) or "합의결과" (settlement result) can appear as:
#   - "주문" on one line
#   - "주 문" with space
#   - "문\n주" (reversed on two separate lines - OCR artifact)
#   - "합의결과" or "합의 결과"
SECTION_ORDER_RE = re.compile(r"(?:주\s*문|문\s*\n+\s*주|합의\s*결과)")
# "이유" can have spaces: "이 유" or "유\n이"
SECTION_REASON_RE = re.compile(r"이\s*유|유\s*\n+\s*이")
# "1. 당사자 주장" or "1. 기초 사실" - subsection within "이유"
SECTION_PARTIES_CLAIM_RE = re.compile(r"(?m)^1\.\s*(?:당사자\s*주장|기초\s*사실)")
# "2. 판단" - handles normal case and reversed split (단\n2. 판)
SECTION_JUDGMENT_RE = re.compile(r"단\s*\n\s*^2\.\s*판|^2\.\s*판\s*단", re.MULTILINE)
# "[관련 법령]" - related laws section
LAW_RE = re.compile(r"\[관련\s*법령\]\s*(.+?)(?=\n\n|\n이상과|$)", re.DOTALL)


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
    # Use split points; keep headings inside chunks.
    # Strategy: find split indices, then slice.
    matches = list(CASE_SPLIT_RE.finditer(merged_text))
    if not matches:
        return [merged_text.strip()] if merged_text.strip() else []

    idxs = [m.start() for m in matches]
    idxs.append(len(merged_text))

    cases = []
    for i in range(len(idxs) - 1):
        chunk = merged_text[idxs[i]:idxs[i + 1]].strip()
        if chunk:
            cases.append(chunk)
    return cases


def parse_case_fields(case_text: str) -> Dict[str, Any]:
    # Extract title - can span multiple lines
    title = None
    m = TITLE_RE.search(case_text)
    if m:
        # Replace newlines and multiple spaces with single space
        title = re.sub(r'\s+', ' ', m.group(1).strip())

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
        # Convert YYYYMMDD to YYYY.MM.DD if no dots present
        if "." not in date_str and len(date_str) == 8:
            decision_date = f"{date_str[:4]}.{date_str[4:6]}.{date_str[6:8]}"
        else:
            decision_date = date_str.rstrip(".")

    # Extract main sections
    # 주문 (decision): from "주문" to "이유"
    decision = _slice_between(case_text, SECTION_ORDER_RE, SECTION_REASON_RE)

    # 이유 section contains two subsections:
    # 1. 당사자 주장/기초 사실 (parties_claim): from "1. 당사자 주장" or "1. 기초 사실" to "2. 판단"
    # 2. 판단 (judgment): from "2. 판단" to "[관련 법령]" or end of case

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


# -----------------------------
# MAIN
# -----------------------------
def main():
    assert_crawling_env()
    load_dotenv()

    ap = argparse.ArgumentParser(
        description="Upstage Document Parse -> save -> merge elements -> case-level jsonl",
        epilog="""
Examples:
  # Both parsing and processing (default)
  python %(prog)s --pdf kca_2016_의료-001-100.pdf

  # Only parse (API call, save response.json) - 비용 발생!
  python %(prog)s --pdf kca_2016_의료-001-100.pdf --parse-only

  # Only process (read existing response.json, no API call) - 비용 없음
  python %(prog)s --pdf kca_2016_의료-001-100.pdf --process-only

  # Process all existing parsed directories
  python %(prog)s --process-only --output-dir kjw/data/raw/parsed

  # With preprocessing for RAG
  python %(prog)s --process-only --preprocess=rag
  python %(prog)s --process-only --preprocess=light
  python %(prog)s --process-only --preprocess=none
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--pdf", help="PDF filename under kjw/data/raw/split (e.g., kca_2016_의료-001-100.pdf)")
    ap.add_argument("--input-dir", default="kjw/data/raw/split", help="Input directory (default: kjw/data/raw/split)")
    ap.add_argument("--output-dir", default="kjw/data/raw/parsed", help="Output directory (default: kjw/data/raw/parsed)")
    ap.add_argument("--formats", default="text", help="Comma-separated output formats (default: text). e.g., text,markdown,html")
    ap.add_argument("--parse-only", action="store_true", help="Only call API and save response.json (비용 발생!)")
    ap.add_argument("--process-only", action="store_true", help="Only process existing response.json (비용 없음)")
    ap.add_argument("--preprocess", choices=["none", "light", "rag"], default="none",
                    help="Preprocessing mode: none (no preprocessing), light (remove noise only), rag (optimize for RAG systems)")
    args = ap.parse_args()

    # Validate arguments
    if args.parse_only and args.process_only:
        raise ValueError("Cannot use both --parse-only and --process-only")

    # If not process-only, we need --pdf for parsing
    if not args.process_only and not args.pdf:
        raise ValueError("--pdf is required unless using --process-only")

    # Setup paths
    out_root = Path(args.output_dir)

    if args.pdf:
        # Single PDF mode
        stem = Path(args.pdf).stem
        out_root = Path(args.output_dir) / stem
        out_root.mkdir(parents=True, exist_ok=True)
        process_targets = [out_root]
    else:
        # Process all subdirectories mode (only with --process-only)
        if not args.process_only:
            raise ValueError("--pdf is required unless using --process-only")
        process_targets = [d for d in out_root.iterdir() if d.is_dir() and (d / "response.json").exists()]
        if not process_targets:
            print(f"No directories with response.json found in {out_root}")
            return

    # ========================================
    # PARSING (API CALL - 비용 발생!)
    # ========================================
    if not args.process_only:
        print("\n[PARSING - API 호출 중... 비용 발생!]")

        api_key = os.getenv("UPSTAGE_API_KEY")
        if not api_key:
            raise RuntimeError("UPSTAGE_API_KEY not found. Put it in .env or export it in your shell.")

        input_dir = Path(args.input_dir)
        pdf_path = input_dir / args.pdf
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        formats = [s.strip() for s in args.formats.split(",") if s.strip()]
        if not formats:
            formats = ["text"]

        # Call API
        print(f"  Calling Upstage API for {pdf_path.name}...")
        resp = call_upstage_parse(pdf_path, api_key, formats)

        # Save raw response
        response_path = out_root / "response.json"
        response_path.write_text(
            json.dumps(resp, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"  ✓ Saved: {response_path}")

        if args.parse_only:
            print("\n[DONE - PARSE ONLY]")
            print(f"  Response saved to: {response_path}")
            print("  Run with --process-only to generate merged_elements, cases, chunks")
            return

    # ========================================
    # PROCESSING (비용 없음 - 기존 response.json 사용)
    # ========================================
    # Select preprocessing function
    preprocess_func = None
    if args.preprocess == "rag":
        preprocess_func = preprocess_for_rag
        print("\n[PROCESSING - 기존 response.json 사용 중... 비용 없음 | 전처리: RAG 최적화]")
    elif args.preprocess == "light":
        preprocess_func = preprocess_light
        print("\n[PROCESSING - 기존 response.json 사용 중... 비용 없음 | 전처리: 경량]")
    else:
        print("\n[PROCESSING - 기존 response.json 사용 중... 비용 없음 | 전처리: 없음]")

    for target_dir in process_targets:
        print(f"\n  Processing: {target_dir.name}")

        # Load existing response.json
        response_path = target_dir / "response.json"
        if not response_path.exists():
            print(f"    ✗ Skipped: response.json not found")
            continue

        with response_path.open("r", encoding="utf-8") as f:
            resp = json.load(f)

        # Infer source PDF name from directory name or use provided --pdf
        source_pdf_name = args.pdf if args.pdf else (target_dir.name + ".pdf")

        # 1) merge elements -> merged text
        elements = extract_elements(resp)
        merged_text = merge_elements_to_text(elements)
        merged_path = target_dir / "merged_elements.txt"
        merged_path.write_text(merged_text, encoding="utf-8")
        print(f"    ✓ Generated: merged_elements.txt ({len(elements)} elements)")

        # 2) split into cases and write jsonl
        agency = infer_agency_from_filename(source_pdf_name)
        cases = split_into_cases(merged_text)

        cases_path = target_dir / "cases.jsonl"
        chunks_path = target_dir / "chunks.jsonl"

        with cases_path.open("w", encoding="utf-8") as f_cases, chunks_path.open("w", encoding="utf-8") as f_chunks:
            for idx, case_text in enumerate(cases, start=1):
                fields = parse_case_fields(case_text)

                # Apply preprocessing to text fields if enabled
                if preprocess_func:
                    fields["decision"] = preprocess_func(fields.get("decision", ""))
                    fields["parties_claim"] = preprocess_func(fields.get("parties_claim", ""))
                    fields["judgment"] = preprocess_func(fields.get("judgment", ""))
                    fields["law"] = preprocess_func(fields.get("law", ""))
                    # Also preprocess raw_text for consistency
                    preprocessed_raw = preprocess_func(case_text)
                else:
                    preprocessed_raw = case_text

                record = {
                    "source_pdf": source_pdf_name,
                    "agency": agency,
                    "case_index": idx,
                    **fields,
                    "raw_text": preprocessed_raw,
                }
                f_cases.write(json.dumps(record, ensure_ascii=False) + "\n")

                # chunk-level lines (for RAG indexing)
                shared = {
                    "source_pdf": source_pdf_name,
                    "agency": agency,
                    "case_index": idx,
                    "case_no": fields.get("case_no"),
                    "decision_date": fields.get("decision_date"),
                }
                for chunk_type in ("decision", "parties_claim", "judgment", "law"):
                    txt = fields.get(chunk_type) or ""
                    txt = txt.strip()
                    if not txt:
                        continue
                    f_chunks.write(json.dumps({**shared, "chunk_type": chunk_type, "text": txt}, ensure_ascii=False) + "\n")

        print(f"    ✓ Generated: cases.jsonl ({len(cases)} cases)")

        # Count chunks
        with chunks_path.open("r", encoding="utf-8") as f:
            num_chunks = sum(1 for _ in f)
        print(f"    ✓ Generated: chunks.jsonl ({num_chunks} chunks)")

    print("\n[DONE]")
    if len(process_targets) == 1:
        print(f"  Output directory: {process_targets[0]}")
    else:
        print(f"  Processed {len(process_targets)} directories")


if __name__ == "__main__":
    main()
