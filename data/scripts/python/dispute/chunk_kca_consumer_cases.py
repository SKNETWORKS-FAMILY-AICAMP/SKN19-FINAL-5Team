#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Chunk KCA consumer dispute cases from merged elements text file into JSONL format.

Parses kca_merged_elements copy.txt (2020 분쟁조정례 100선) and generates
properly chunked JSONL output compatible with kca_final_chunks.jsonl format.

Enhanced version with support for collective dispute cases and malformed headers.

Example:
  python chunk_kca_consumer_cases.py \\
    --input kjw/data/preprocess/kca_merged_elements\\ copy.txt \\
    --output kjw/data/preprocess/kca_final_chunks\\ copy.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Tuple, Optional


# Multiple regex patterns to handle different header formats
CASE_HEADER_PATTERNS = [
    # Pattern 1: Standard format - [ 카테고리 ] 소비자분쟁조정위원회, 사건번호｜결정 날짜
    (
        'standard',
        r'\[\s*([^\]]+)\s*\]\s*소비자분쟁조정위원회[,\s]*(\d{4}일[가나다][가-힣]?\d+)｜결정\s*(\d{4})[.\s]*(\d{1,2})[.\s]*(\d{1,2})'
    ),

    # Pattern 2: Collective disputes - [집단] (optional 소비자분쟁조정위원회) 사건번호｜결정 날짜
    (
        'collective',
        r'\[\s*집단\s*\](?:\s*소비자분쟁조정위원회)?\s*(\d{4}집단\d+)｜결정\s*(\d{1,4})[.\s]*(\d{1,2})[.\s]*(\d{1,2})\.?\)?'
    ),

    # Pattern 3: Simplified format - [ 카테고리 ] 사건번호｜결정 날짜 (without committee name)
    (
        'simplified',
        r'\[\s*([^\]]+)\s*\]\s*(\d{4}(?:일[가나다][가-힣]?|집단)\d+)｜결정\s*(\d{2,4})[.\s]*(\d{1,2})[.\s]*(\d{1,2})\.?\)?'
    ),
]


@dataclass
class ParsingIssue:
    """Represents a parsing issue encountered during processing."""
    line_number: int
    issue_type: str
    description: str
    resolution: str
    raw_text: str = ''


@dataclass
class ParsingIssues:
    """Tracks all parsing issues encountered."""
    malformed_headers: List[ParsingIssue] = field(default_factory=list)
    missing_metadata: List[ParsingIssue] = field(default_factory=list)
    ocr_errors: List[ParsingIssue] = field(default_factory=list)
    warnings: List[ParsingIssue] = field(default_factory=list)

    def add_malformed_header(self, line_num: int, desc: str, resolution: str, raw: str = ''):
        self.malformed_headers.append(ParsingIssue(line_num, 'malformed_header', desc, resolution, raw))

    def add_ocr_error(self, line_num: int, desc: str, resolution: str, raw: str = ''):
        self.ocr_errors.append(ParsingIssue(line_num, 'ocr_error', desc, resolution, raw))

    def add_warning(self, line_num: int, desc: str, resolution: str, raw: str = ''):
        self.warnings.append(ParsingIssue(line_num, 'warning', desc, resolution, raw))


def try_match_case_header(page: str, page_num: int, issues: ParsingIssues) -> Optional[Dict]:
    """
    Try multiple patterns to match case header.

    Args:
        page: Page text to search
        page_num: Page number for logging
        issues: ParsingIssues tracker

    Returns:
        Dictionary with matched groups and metadata, or None if no match
    """
    for pattern_name, pattern in CASE_HEADER_PATTERNS:
        match = re.search(pattern, page)
        if match:
            result = {
                'pattern': pattern_name,
                'match': match
            }

            # Log if non-standard pattern was used
            if pattern_name != 'standard':
                header_text = match.group(0)
                issues.add_malformed_header(
                    page_num,
                    f"Non-standard header format detected: {pattern_name}",
                    f"Matched using pattern '{pattern_name}'",
                    header_text[:100]
                )

            return result

    return None


def normalize_case_number(case_no: str, issues: ParsingIssues, page_num: int) -> str:
    """
    Normalize case number format.

    Args:
        case_no: Raw case number
        issues: ParsingIssues tracker
        page_num: Page number for logging

    Returns:
        Normalized case number
    """
    # Handle collective dispute format
    if '집단' in case_no:
        return case_no

    # Standard format
    return case_no


def normalize_date(year: str, month: str, day: str, issues: ParsingIssues, page_num: int) -> str:
    """
    Normalize and validate date, fixing common OCR errors.

    Args:
        year: Year string (2-4 digits)
        month: Month string
        day: Day string
        issues: ParsingIssues tracker
        page_num: Page number for logging

    Returns:
        Normalized date in YYYY.MM.DD format
    """
    # Fix 2-digit or 3-digit year (OCR error)
    if len(year) == 2:
        year = '20' + year
        issues.add_ocr_error(
            page_num,
            f"2-digit year detected: {year[-2:]}",
            f"Expanded to {year}",
            year
        )
    elif len(year) == 3:
        year = '2' + year
        issues.add_ocr_error(
            page_num,
            f"3-digit year detected: {year[1:]}",
            f"Corrected to {year}",
            year
        )

    month = month.zfill(2)
    day = day.zfill(2)

    return f"{year}.{month}.{day}"


def parse_kca_consumer_txt(file_path: Path, issues: ParsingIssues) -> List[Dict]:
    """
    Parse KCA consumer cases from merged elements text file.

    Args:
        file_path: Path to the input text file
        issues: ParsingIssues tracker

    Returns:
        List of case dictionaries with metadata and text
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split by page markers
    pages = re.split(r'=== PAGE \d+ ===', content)
    pages = [p.strip() for p in pages if p.strip()]

    cases = []
    current_case = None
    current_case_text = []
    page_num = 0

    for page in pages:
        page_num += 1

        # Try to match case header with multiple patterns
        header_match_result = try_match_case_header(page, page_num, issues)

        if header_match_result:
            # Save previous case if exists
            if current_case and current_case_text:
                current_case['text'] = '\n'.join(current_case_text).strip()
                cases.append(current_case)

            # Extract metadata based on pattern type
            pattern_name = header_match_result['pattern']
            match = header_match_result['match']

            if pattern_name == 'standard':
                # Standard pattern: (category, case_no, year, month, day)
                category = match.group(1).strip()
                case_no = match.group(2)
                year = match.group(3)
                month = match.group(4)
                day = match.group(5)

            elif pattern_name == 'collective':
                # Collective pattern: (case_no, year, month, day)
                category = '집단'
                case_no = match.group(1)
                year = match.group(2)
                month = match.group(3)
                day = match.group(4)

            elif pattern_name == 'simplified':
                # Simplified pattern: (category, case_no, year, month, day)
                category = match.group(1).strip()
                case_no = match.group(2)
                year = match.group(3)
                month = match.group(4)
                day = match.group(5)

            # Normalize data
            case_no = normalize_case_number(case_no, issues, page_num)
            decision_date = normalize_date(year, month, day, issues, page_num)

            # Start new case
            current_case = {
                'category': category,
                'case_no': case_no,
                'decision_date': decision_date,
                'pattern_used': pattern_name
            }
            current_case_text = [page]

        elif current_case:
            # Continue current case
            current_case_text.append(page)
        # else: skip pages before first case

    # Don't forget the last case
    if current_case and current_case_text:
        current_case['text'] = '\n'.join(current_case_text).strip()
        cases.append(current_case)

    case_no_to_index = {}
    next_index = 1
    for case in cases:
        case_no = case.get('case_no', '').strip()
        if not case_no:
            case_no = f"_missing_{next_index}"
            issues.add_warning(
                0,
                "Missing case_no; assigned synthetic key for case_index mapping.",
                f"Assigned {case_no}"
            )
        if case_no not in case_no_to_index:
            case_no_to_index[case_no] = next_index
            next_index += 1
        case['case_index'] = case_no_to_index[case_no]

    return cases

DECISION_BULLET_PREFIX = r'(?:^|[\n\r])\s*(?:[•▪·■□○●]|\*)?\s*'
DECISION_BULLET_REGEX = re.compile(r'^\s*(?:[•▪·■□○●]|\*)\s*')

DECISION_AMOUNT_PATTERN = r'원(?:\([^)]+\))?\s*(?:을|를)?\s*(?:지급|환급)'

DECISION_PATTERNS = [
    # 1. 표준 지급 결정 (사업자/피신청인)
    rf'{DECISION_BULLET_PREFIX}((?:사업자|피신청인)(?:\([12]\))?[은는] 소비자에게[^。]+?{DECISION_AMOUNT_PATTERN}[^。]+[다함]\.)',

    # 2. 피신청인 지급 (복잡한 형식)
    rf'{DECISION_BULLET_PREFIX}(피신청인은.*?{DECISION_AMOUNT_PATTERN}[^。]+다\.)',

    # 3. 번호 매겨진 결정 (1. 피신청인은...)
    rf'{DECISION_BULLET_PREFIX}(1\.\s+피신청인은.*?지급한다\.(?:\n2\..*?지급한다\.)?)',

    # 4. 공동 사업자 결정
    rf'{DECISION_BULLET_PREFIX}(사업자들은 공동하여.*?회수하고,?\n.*?원을 지급함\.)',

    # 5. 집단분쟁 환급 결정
    rf'{DECISION_BULLET_PREFIX}(사업자(?:들)?는 (?:소비자(?:들)?에게|별지.*?소비자.*?에게)[^。]+?{DECISION_AMOUNT_PATTERN}.*?한다?\.)',

    # 6. 번호 있는 주체 (사업자(1), 사업자(2))
    rf'{DECISION_BULLET_PREFIX}(사업자\(\d+\)[은는] 소비자(?:\(\d+\))?에게[^。]+?{DECISION_AMOUNT_PATTERN}[^。]+[다함]\.)',

    # 7. 병원/한의원 주체
    rf'{DECISION_BULLET_PREFIX}((?:병원|한의원|의원|치과)[은는] 소비자에게[^。]+?{DECISION_AMOUNT_PATTERN}[^。]+[다함]\.)',

    # 8. 복수 수혜자 (배우자 + 자녀들)
    rf'{DECISION_BULLET_PREFIX}(사업자[은는] (?:배우자인|망인의 배우자인) 소비자\([^)]+\)에게[^。]+?{DECISION_AMOUNT_PATTERN}[,\s]+(?:자녀들인|망인의 자녀인)[^。]+?{DECISION_AMOUNT_PATTERN}[^。]+[다함]\.)',

    # 9. 무효/확인 결정
    rf'{DECISION_BULLET_PREFIX}((?:사업자|피신청인)[가는]?.*?소비자에게.*?(?:무효임을|존재하지 않?음을|부존재함을) 확인[^。]+[다함]\.)',

    # 10. 기각/각하 결정
    rf'{DECISION_BULLET_PREFIX}(이 사건 (?:집단분쟁조정 절차를?|분쟁조정 신청에 대하여는 각?) (?:개시하지|조정하지) 아니함\.)',

    # 11. 조정 불성립
    rf'{DECISION_BULLET_PREFIX}(위 (?:신청인과 피신청인|소비자와 사업자) (?:사이의|간) .*?조정[이가] 성립되지 (?:아니하였음|않았음)\.)',

    # 12. 복수 결정 (별지 목록)
    rf'{DECISION_BULLET_PREFIX}(사업자[은는] 별지 제\d+목록 기재 소비자들에게[^。]+?{DECISION_AMOUNT_PATTERN}[^。]+[다함]\.(?:\s+사업자와 별지 제\d+목록[^。]+조정하지 아니함\.)?)',

    # 13. 특정 대상 조정 불가
    rf'{DECISION_BULLET_PREFIX}((?:사업자|피신청인|신청인|소비자)(?:\(\d+\))?(?:에 대해서는)? 조정하지 아니함\.)',

    # 14. 개시/조정 불가 단문
    rf'{DECISION_BULLET_PREFIX}(조정하지 아니함\.)',
    rf'{DECISION_BULLET_PREFIX}(개시하지 아니함\.)',
]

LAW_PATTERNS = [
    # 소비자분쟁해결기준
    r'(「소비자분쟁해결기준」은[\s\S]+?(?:\n\n|$))',
]

DECISION_LINE_KEYWORDS = re.compile(r'(지급|환급|회수|반환|조정하지|개시하지|무효|부존재|존재하지|기각|각하)')
DECISION_LINE_START = re.compile(r'^(?:사업자|피신청인|신청인|이 사건|위|1\.|조정하지|개시하지)')
CLAIM_LINE_KEYWORDS = re.compile(r'(요구|주장|다툼|반박)')
SPEAKER_LINE = re.compile(r'^\s*[^:\n]{1,20}\s*[:：]')

CHUNK_MAX_LEN = 1500
CHUNK_OVERLAP = 200


def strip_bullet(line: str) -> str:
    return DECISION_BULLET_REGEX.sub('', line).strip()


def is_decision_line(line: str) -> bool:
    stripped = strip_bullet(line)
    if not stripped:
        return False
    if SPEAKER_LINE.match(stripped):
        return False
    if CLAIM_LINE_KEYWORDS.search(stripped):
        return False
    if not DECISION_LINE_KEYWORDS.search(stripped):
        return False
    return bool(DECISION_LINE_START.match(stripped))


def find_decision_match(case_text: str) -> Optional[re.Match]:
    for pattern in DECISION_PATTERNS:
        match = re.search(pattern, case_text, re.DOTALL)
        if match:
            return match
    return None


def find_first_law_match(case_text: str) -> Optional[re.Match]:
    earliest = None
    for pattern in LAW_PATTERNS:
        match = re.search(pattern, case_text, re.DOTALL)
        if match:
            if earliest is None or match.start() < earliest.start():
                earliest = match
    return earliest


def find_decision_span(case_text: str) -> Optional[Tuple[int, int, str]]:
    """
    Find decision text with original span offsets.
    """
    lines = case_text.splitlines(keepends=True)
    offset = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if not is_decision_line(line):
            offset += len(line)
            i += 1
            continue
        decision_lines = [strip_bullet(line)]
        start = offset
        end = offset + len(line)
        i += 1
        offset += len(line)
        while i < len(lines):
            next_line = lines[i]
            if is_decision_line(next_line):
                decision_lines.append(strip_bullet(next_line))
                end = offset + len(next_line)
                i += 1
                offset += len(next_line)
                continue
            if DECISION_BULLET_REGEX.match(next_line):
                following = lines[i + 1] if i + 1 < len(lines) else ''
                if decision_lines and following and not DECISION_BULLET_REGEX.match(following) and DECISION_LINE_KEYWORDS.search(following):
                    decision_lines.append(strip_bullet(next_line))
                    end = offset + len(next_line)
                    i += 1
                    offset += len(next_line)
                    continue
                break
            if decision_lines and next_line.strip():
                decision_lines[-1] += ' ' + next_line.strip()
                end = offset + len(next_line)
                i += 1
                offset += len(next_line)
                continue
            break
        decision_text = '\n'.join(decision_lines).strip()
        decision_text = re.sub(r'!\[image\]\(/image/placeholder\)', '', decision_text).strip()
        if decision_text and len(decision_text) > 15:
            return start, end, decision_text
        break

    match = find_decision_match(case_text)
    if match:
        decision_text = match.group(1).strip()
        decision_text = re.sub(r'!\[image\]\(/image/placeholder\)', '', decision_text).strip()
        if decision_text and len(decision_text) > 15:
            return match.start(), match.end(), decision_text

    return None


def extract_decision(case_text: str) -> Optional[str]:
    """
    Extract decision section from case text.
    """
    result = find_decision_span(case_text)
    if result:
        return result[2]
    return None


def extract_parties_claim(case_text: str) -> Optional[str]:
    """
    Extract parties claim section (당사자 주장).

    Args:
        case_text: Full text of the case

    Returns:
        Parties claim text or None if not found
    """
    # 시작 마커
    start_patterns = [
        r'당사자 주장',
        r'가\.\s*신청인\(?소비자\)?',
        r'신청인\(?소비자\)?의 주장',
    ]

    # 종료 마커 (판단 섹션 시작)
    end_patterns = [
        r'\n판단\n',
        r'\n이유\n',
        r'\n사실 관계\n',
        r'\n손해배상책임의 발생\n',
        r'\n책임 유무\n',
        r'\n위원회의 판단\n',
    ]

    # 시작점 찾기
    start_pos = None
    for pattern in start_patterns:
        match = re.search(pattern, case_text)
        if match:
            start_pos = match.start()
            break

    if start_pos is None:
        decision_span = find_decision_span(case_text)
        if decision_span:
            search_end = decision_span[0]
        else:
            search_end = len(case_text)
        pre_decision = case_text[:search_end]
        claim_patterns = [
            r'(소비자|신청인)[\s\S]{0,120}?(?:주장|요구|신청)(?:함|하였음|하였고|함\.)',
            r'(사업자|피신청인)[\s\S]{0,120}?(?:주장|거절|다툼|반박)(?:함|하였음|하였고|함\.)',
        ]
        claim_matches = []
        for pattern in claim_patterns:
            claim_matches.extend(list(re.finditer(pattern, pre_decision)))

        if not claim_matches:
            return None

        start_pos = min(m.start() for m in claim_matches)
        end_pos = max(m.end() for m in claim_matches)

        line_start = pre_decision.rfind('\n', 0, start_pos)
        if line_start != -1:
            start_pos = line_start + 1

        next_line_break = pre_decision.find('\n', end_pos)
        if next_line_break != -1:
            end_pos = next_line_break
        else:
            end_pos = len(pre_decision)

        parties_claim = pre_decision[start_pos:end_pos].strip()

        if len(parties_claim) > 50:
            return parties_claim

        return None

    # 종료점 찾기
    end_pos = len(case_text)
    for pattern in end_patterns:
        match = re.search(pattern, case_text[start_pos:])
        if match:
            end_pos = start_pos + match.start()
            break

    parties_claim = case_text[start_pos:end_pos].strip()

    # 최소 길이 확인
    if len(parties_claim) > 50:
        return parties_claim

    return None


def extract_judgment(case_text: str) -> Optional[str]:
    """
    Extract judgment section (판단/이유).

    Args:
        case_text: Full text of the case

    Returns:
        Judgment text or None if not found
    """
    # 시작 마커
    start_patterns = [
        r'\n판단\n',
        r'\n이유\n',
        r'\n사실 관계\n',
        r'\n손해배상책임의 발생\n',
        r'\n책임 유무\n',
        r'\n위원회의 판단\n',
    ]

    # 종료 마커 (법령 섹션 또는 파일 끝)
    end_patterns = [
        r'\n\n「소비자분쟁해결기준」',
    ]

    # 시작점 찾기
    start_pos = None
    for pattern in start_patterns:
        match = re.search(pattern, case_text)
        if match:
            start_pos = match.start()
            break

    if start_pos is None:
        decision_span = find_decision_span(case_text)
        if not decision_span:
            return None
        start_pos = decision_span[1]
        law_match = find_first_law_match(case_text[start_pos:])
        if law_match:
            end_pos = start_pos + law_match.start()
        else:
            end_pos = len(case_text)
        judgment = case_text[start_pos:end_pos].strip()
        if len(judgment) > 50:
            return judgment
        return None

    # 종료점 찾기
    end_pos = len(case_text)
    for pattern in end_patterns:
        match = re.search(pattern, case_text[start_pos:])
        if match:
            end_pos = start_pos + match.start()
            break

    judgment = case_text[start_pos:end_pos].strip()

    # 최소 길이 확인
    if len(judgment) > 50:
        return judgment

    return None


def extract_law(case_text: str) -> Optional[str]:
    """
    Extract law/reference section (법령/조정례).

    Args:
        case_text: Full text of the case

    Returns:
        Law reference text or None if not found
    """
    laws = []
    for pattern in LAW_PATTERNS:
        matches = re.findall(pattern, case_text, re.DOTALL)
        if matches:
            for m in matches:
                # Clean up
                m = m.strip()
                if m and len(m) > 20:
                    laws.append(m)

    if laws:
        # 중복 제거 및 결합
        law_text = '\n\n'.join(laws)
        return law_text.strip()

    return None


def split_text_with_overlap(text: str, max_len: int, overlap: int) -> List[str]:
    """
    Split long text into overlapping chunks using soft boundaries.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_len, len(text))
        window = text[start:end]

        cut = max(
            window.rfind('\n'),
            window.rfind('。'),
            window.rfind('.'),
            window.rfind('!'),
            window.rfind('?')
        )
        if cut <= 0 or end == len(text):
            cut_pos = end
        else:
            cut_pos = start + cut + 1

        if cut_pos <= start:
            cut_pos = end

        chunk = text[start:cut_pos].strip()
        if chunk:
            chunks.append(chunk)

        if cut_pos >= len(text):
            break

        start = max(cut_pos - overlap, 0)

    return chunks


def classify_sections(case_text: str) -> List[Tuple[str, str]]:
    """
    Classify case text into detailed sections matching original chunking strategy.

    Args:
        case_text: Full text of the case

    Returns:
        List of (chunk_type, text) tuples:
        - decision: 결정문
        - parties_claim: 당사자 주장
        - judgment: 판단/이유
        - law: 법령/조정례 (선택적)
    """
    sections = []

    # 1. Decision 추출
    decision_text = extract_decision(case_text)
    if decision_text:
        sections.append(('decision', decision_text))

    # 2. Parties Claim 추출
    parties_claim_text = extract_parties_claim(case_text)
    if parties_claim_text:
        sections.append(('parties_claim', parties_claim_text))

    # 3. Judgment 추출
    judgment_text = extract_judgment(case_text)
    if judgment_text:
        sections.append(('judgment', judgment_text))

    # 4. Law 추출 (없으면 공백)
    law_text = extract_law(case_text)
    sections.append(('law', law_text or ''))

    # 폴백: 아무것도 추출되지 않으면 전체를 case_overview로
    if not sections:
        sections.append(('case_overview', case_text))

    return sections


def generate_chunks(cases: List[Dict], issues: ParsingIssues) -> List[Dict]:
    """
    Generate JSONL chunks from parsed cases.

    Args:
        cases: List of case dictionaries
        issues: ParsingIssues tracker

    Returns:
        List of chunk dictionaries ready for JSONL output
    """
    chunks = []

    for case in cases:
        case_text = case.get('text', '')
        case_index = case.get('case_index', 1)
        case_no = case.get('case_no', '')
        decision_date = case.get('decision_date', '')

        # Classify sections
        sections = classify_sections(case_text)

        # Generate chunks for each section (with overlap if long)
        for chunk_type, text in sections:
            text = (text or '').strip()
            if not text and chunk_type == 'law':
                parts = ['']
            else:
                parts = split_text_with_overlap(text, CHUNK_MAX_LEN, CHUNK_OVERLAP)
            for part in parts:
                chunk = {
                    'source': 'kca_merged',
                    'agency': 'kca',
                    'case_index': case_index,
                    'case_no': case_no,
                    'decision_date': decision_date,
                    'chunk_type': chunk_type,
                    'text': part.strip()
                }
                chunks.append(chunk)

    return chunks


def generate_validation_report(
    cases: List[Dict],
    chunks: List[Dict],
    issues: ParsingIssues,
    output_path: Path
) -> None:
    """
    Generate detailed validation report.

    Args:
        cases: List of parsed cases
        chunks: List of generated chunks
        issues: ParsingIssues tracker
        output_path: Path to write the report
    """
    report_lines = []

    # Header
    report_lines.append("=" * 80)
    report_lines.append("KCA 청킹 검증 리포트")
    report_lines.append("=" * 80)
    report_lines.append(f"생성 날짜: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("")

    # 1. Parsing Statistics
    report_lines.append("1. 파싱 통계")
    report_lines.append("   " + "-" * 76)
    report_lines.append(f"   - 총 케이스 수: {len(cases)}")
    report_lines.append(f"   - 총 청크 수: {len(chunks)}")
    report_lines.append(f"   - 케이스당 평균 청크: {len(chunks)/len(cases):.2f}")
    report_lines.append(f"   - 말형된 헤더: {len(issues.malformed_headers)}")
    report_lines.append(f"   - OCR 오류: {len(issues.ocr_errors)}")
    report_lines.append(f"   - 경고: {len(issues.warnings)}")
    report_lines.append("")

    # 2. Chunk Type Statistics
    report_lines.append("2. Chunk Type 통계")
    report_lines.append("   " + "-" * 76)

    # Count chunk types
    chunk_type_counts = {}
    for chunk in chunks:
        chunk_type = chunk['chunk_type']
        chunk_type_counts[chunk_type] = chunk_type_counts.get(chunk_type, 0) + 1

    report_lines.append("   Chunk Type 분포:")
    for chunk_type in ['decision', 'parties_claim', 'judgment', 'law', 'case_overview']:
        count = chunk_type_counts.get(chunk_type, 0)
        percentage = (count / len(chunks) * 100) if chunks else 0
        report_lines.append(f"     - {chunk_type:15s}: {count:3d} ({percentage:5.1f}%)")

    # Coverage per case
    report_lines.append("")
    report_lines.append("   Chunk Type별 케이스 커버리지:")

    chunks_by_case = {}
    for chunk in chunks:
        case_idx = chunk['case_index']
        if case_idx not in chunks_by_case:
            chunks_by_case[case_idx] = []
        chunks_by_case[case_idx].append(chunk['chunk_type'])

    for chunk_type in ['decision', 'parties_claim', 'judgment', 'law']:
        cases_with_type = sum(1 for types in chunks_by_case.values() if chunk_type in types)
        coverage = (cases_with_type / len(cases) * 100) if cases else 0
        report_lines.append(f"     - {chunk_type:15s}: {cases_with_type:3d}/{len(cases)} 케이스 ({coverage:5.1f}%)")

    # Cases missing decision
    cases_missing_decision = []
    for case_idx, chunk_types in chunks_by_case.items():
        if 'decision' not in chunk_types:
            case_info = next((c for c in cases if c['case_index'] == case_idx), None)
            if case_info:
                cases_missing_decision.append((case_idx, case_info['case_no']))

    if cases_missing_decision:
        report_lines.append("")
        report_lines.append(f"   Decision 청크 누락 케이스 ({len(cases_missing_decision)}개):")
        for case_idx, case_no in cases_missing_decision[:10]:
            report_lines.append(f"     - Case {case_idx:3d} ({case_no})")
        if len(cases_missing_decision) > 10:
            report_lines.append(f"     ... ({len(cases_missing_decision) - 10} more)")

    report_lines.append("")

    # 3. Malformed Headers
    if issues.malformed_headers:
        report_lines.append("3. 말형된 헤더")
        report_lines.append("   " + "-" * 76)
        for issue in issues.malformed_headers[:20]:  # Show first 20
            report_lines.append(f"   페이지 {issue.line_number}:")
            report_lines.append(f"     문제: {issue.description}")
            report_lines.append(f"     해결: {issue.resolution}")
            if issue.raw_text:
                report_lines.append(f"     원본: {issue.raw_text}")
            report_lines.append("")

    # 4. OCR Errors
    if issues.ocr_errors:
        report_lines.append("4. OCR 오류")
        report_lines.append("   " + "-" * 76)
        for issue in issues.ocr_errors[:10]:
            report_lines.append(f"   페이지 {issue.line_number}: {issue.description} -> {issue.resolution}")
        report_lines.append("")

    # 5. Case Distribution
    report_lines.append("5. 케이스별 청크 분포")
    report_lines.append("   " + "-" * 76)

    # Group chunks by case_index
    chunks_by_case = {}
    for chunk in chunks:
        case_idx = chunk['case_index']
        if case_idx not in chunks_by_case:
            chunks_by_case[case_idx] = []
        chunks_by_case[case_idx].append(chunk['chunk_type'])

    for case_idx in sorted(chunks_by_case.keys())[:20]:  # Show first 20
        chunk_types = ', '.join(chunks_by_case[case_idx])
        case_info = next((c for c in cases if c['case_index'] == case_idx), None)
        case_no = case_info['case_no'] if case_info else 'Unknown'
        report_lines.append(f"   Case {case_idx:3d} ({case_no}): {len(chunks_by_case[case_idx])} chunks ({chunk_types})")

    if len(chunks_by_case) > 20:
        report_lines.append(f"   ... ({len(chunks_by_case) - 20} more cases)")
    report_lines.append("")

    # 6. Chunk Length Statistics
    report_lines.append("6. 청크 길이 통계")
    report_lines.append("   " + "-" * 76)

    chunk_lengths = [len(c['text']) for c in chunks]
    chunk_lengths.sort(reverse=True)

    report_lines.append(f"   - 평균 길이: {sum(chunk_lengths)/len(chunk_lengths):.0f} 문자")
    report_lines.append(f"   - 최소 길이: {min(chunk_lengths)} 문자")
    report_lines.append(f"   - 최대 길이: {max(chunk_lengths)} 문자")
    report_lines.append("")
    report_lines.append("   상위 10개 긴 청크:")
    for i, length in enumerate(chunk_lengths[:10]):
        chunk = next(c for c in chunks if len(c['text']) == length)
        report_lines.append(f"     {i+1}. {length:6,} 문자 - Case {chunk['case_index']:3d} ({chunk['case_no']}) - {chunk['chunk_type']}")
    report_lines.append("")

    # 7. Warnings
    if issues.warnings:
        report_lines.append("7. 경고")
        report_lines.append("   " + "-" * 76)
        for issue in issues.warnings:
            report_lines.append(f"   {issue.description}")
        report_lines.append("")

    # 8. Recommendations
    report_lines.append("8. 권장 사항")
    report_lines.append("   " + "-" * 76)

    if issues.ocr_errors:
        report_lines.append("   - 입력 파일의 OCR 오류 수정 권장")
    if issues.malformed_headers:
        report_lines.append("   - 집단분쟁 케이스 헤더 형식 표준화 필요")
    if max(chunk_lengths) > 10000:
        report_lines.append("   - 매우 긴 청크 발견: 추가 분할 고려 필요")
    if not issues.ocr_errors and not issues.malformed_headers:
        report_lines.append("   - 모든 케이스가 성공적으로 파싱되었습니다!")

    report_lines.append("")
    report_lines.append("=" * 80)

    # Write report
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))


def main():
    parser = argparse.ArgumentParser(
        description='Chunk KCA consumer dispute cases into JSONL format'
    )
    parser.add_argument(
        '--input',
        type=Path,
        required=True,
        help='Input text file (kca_merged_elements copy.txt)'
    )
    parser.add_argument(
        '--output',
        type=Path,
        required=True,
        help='Output JSONL file (kca_final_chunks copy.jsonl)'
    )
    parser.add_argument(
        '--report',
        type=Path,
        default=None,
        help='Validation report output path (default: <output_dir>/kca_chunking_validation_report.txt)'
    )

    args = parser.parse_args()

    # Initialize issue tracker
    issues = ParsingIssues()

    # Parse cases
    print(f"Parsing cases from {args.input}...")
    cases = parse_kca_consumer_txt(args.input, issues)
    print(f"Found {len(cases)} cases")

    # Generate chunks
    print("Generating chunks...")
    chunks = generate_chunks(cases, issues)
    print(f"Generated {len(chunks)} chunks")

    # Write output
    print(f"Writing to {args.output}...")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with open(args.output, 'w', encoding='utf-8') as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + '\n')

    print(f"Done! Wrote {len(chunks)} chunks to {args.output}")

    # Generate validation report
    if args.report is None:
        report_path = args.output.parent / 'kca_chunking_validation_report.txt'
    else:
        report_path = args.report

    print(f"\nGenerating validation report...")
    generate_validation_report(cases, chunks, issues, report_path)
    print(f"Validation report written to {report_path}")

    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Cases parsed: {len(cases)}")
    print(f"Chunks generated: {len(chunks)}")
    print(f"Average chunks per case: {len(chunks)/len(cases):.2f}")
    print(f"Malformed headers: {len(issues.malformed_headers)}")
    print(f"OCR errors: {len(issues.ocr_errors)}")
    print(f"Warnings: {len(issues.warnings)}")

    # Print sample
    if chunks:
        print("\nSample chunk:")
        print(json.dumps(chunks[0], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
