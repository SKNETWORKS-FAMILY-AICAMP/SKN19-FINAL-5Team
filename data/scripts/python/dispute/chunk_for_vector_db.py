#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Vector DB용 구조 기반 청킹 스크립트

response.json의 elements 배열을 기반으로 부서별(ECMC/KCA/KCDRC) 청킹 전략을 적용하여
Vector DB에 최적화된 청크를 생성합니다.

Usage:
  conda activate crawling
  
  # 단일 디렉토리 처리
  python kjw/scripts/chunk_for_vector_db.py --input kjw/data/raw/parsed/ecmc/ecmc_2010-001-100
  
  # 전체 디렉토리 일괄 처리
  python kjw/scripts/chunk_for_vector_db.py --input-dir kjw/data/raw/parsed

Input:
  kjw/data/raw/parsed/<dept>/<bundle>/response.json

Output:
  kjw/data/raw/parsed/<dept>/<bundle>/chunks_vector_db.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 기존 스크립트에서 필요한 함수들 import
import sys
sys.path.insert(0, str(Path(__file__).parent))
from upstage_parse_to_case_jsonl import (
    NormElement,
    extract_elements,
    assert_crawling_env,
    infer_agency_from_filename,
)


# -----------------------------
# 상수 정의
# -----------------------------

# 섹션 타입 정의
SECTION_FACTS = "facts"
SECTION_CLAIMS = "claims"
SECTION_ANALYSIS = "analysis"
SECTION_DECISION = "decision"
SECTION_MEDIATION_OUTCOME = "mediation_outcome"

# 청크 길이 제어 (토큰 기준, 한글은 대략 2자/토큰)
CHUNK_MIN_TOKENS = 600
CHUNK_MAX_TOKENS = 1600
CHUNK_MIN_CHARS = 1200
CHUNK_MAX_CHARS = 3200
CHUNK_OVERLAP_RATIO = 0.1  # 10% overlap

# 필터링할 category
NOISE_CATEGORIES = {"header", "footer", "footnote"}


# -----------------------------
# 데이터 구조
# -----------------------------

@dataclass
class Chunk:
    """Vector DB용 청크 데이터 구조"""
    agency: str
    source_pdf: str
    case_index: int
    case_no: Optional[str]
    decision_date: Optional[str]
    title: Optional[str]
    section_type: str  # facts/claims/analysis/decision/mediation_outcome
    page_start: int
    page_end: int
    chunk_index: int
    text: str
    
    def to_dict(self) -> Dict[str, Any]:
        """JSONL 출력용 딕셔너리 변환"""
        d = asdict(self)
        # None 값 제거 (선택적)
        return {k: v for k, v in d.items() if v is not None}


# -----------------------------
# 공통 전처리 모듈
# -----------------------------

def estimate_tokens(text: str) -> int:
    """텍스트의 대략적인 토큰 수 추정 (한글 기준 ~2자/토큰)"""
    return len(text) // 2


def filter_elements(elements: List[NormElement]) -> List[NormElement]:
    """
    elements 필터링:
    - header/footer/footnote 제거
    - 짧은 토큰(1-2글자) 연속 병합
    - coordinates 기반 상하단 반복 헤더/푸터 필터링
    """
    if not elements:
        return []
    
    filtered: List[NormElement] = []
    
    # 1. category 기반 필터링
    for el in elements:
        category = el.raw.get("category", "").lower()
        if category in NOISE_CATEGORIES:
            continue
        
        # 텍스트가 너무 짧고 의미 없는 경우 제외 (1-2글자만 있는 경우)
        text = el.text.strip()
        if len(text) <= 2 and not re.search(r'[가-힣]', text):
            continue
        
        filtered.append(el)
    
    # 2. 짧은 토큰 연속 병합 ("주\n문", "이\n유" 같은 경우)
    merged: List[NormElement] = []
    i = 0
    while i < len(filtered):
        current = filtered[i]
        merged_text = current.text
        
        # 다음 몇 개의 element가 짧은 토큰인지 확인
        j = i + 1
        while j < len(filtered) and j < i + 5:  # 최대 5개까지 확인
            next_el = filtered[j]
            next_text = next_el.text.strip()
            
            # 짧은 토큰(1-2글자)이고 같은 페이지에 있으면 병합 고려
            if (len(next_text) <= 2 and 
                next_el.page == current.page and
                abs(next_el.top - current.top) < 50):  # y 좌표가 가까움
                merged_text += next_text
                j += 1
            else:
                break
        
        # 병합된 텍스트로 새 element 생성
        if j > i + 1:
            merged_el = NormElement(
                page=current.page,
                top=current.top,
                left=current.left,
                text=merged_text,
                raw=current.raw
            )
            merged.append(merged_el)
            i = j
        else:
            merged.append(current)
            i += 1
    
    # 3. coordinates 기반 상하단 반복 헤더/푸터 필터링
    # 각 페이지의 상단(top < 100)과 하단(top > 페이지 높이 - 100) 요소 제거
    # 페이지 높이를 정확히 알 수 없으므로, 같은 y 좌표에 반복되는 패턴 제거
    final: List[NormElement] = []
    page_y_positions: Dict[int, List[float]] = {}
    
    for el in merged:
        page_y_positions.setdefault(el.page, []).append(el.top)
    
    # 각 페이지에서 상하단 10% 영역의 y 좌표 범위 계산
    page_bounds: Dict[int, Tuple[float, float]] = {}
    for page, y_list in page_y_positions.items():
        if y_list:
            y_min, y_max = min(y_list), max(y_list)
            page_height = y_max - y_min
            top_threshold = y_min + page_height * 0.1
            bottom_threshold = y_max - page_height * 0.1
            page_bounds[page] = (top_threshold, bottom_threshold)
    
    for el in merged:
        if el.page in page_bounds:
            top_thresh, bottom_thresh = page_bounds[el.page]
            # 상하단 10% 영역에 있고 텍스트가 짧으면 제외
            if (el.top < top_thresh or el.top > bottom_thresh) and len(el.text.strip()) < 10:
                continue
        final.append(el)
    
    return final


# -----------------------------
# 부서별 케이스 경계 감지
# -----------------------------

def detect_ecmc_case_boundaries(elements: List[NormElement]) -> List[int]:
    """
    ECMC 케이스 경계 감지:
    - ^[●·•]\s*사건번호 (Format 1)
    - ^사례\s*\d+ (Format 2)
    - ^\d{1,2}\.\s*$ 다음에 "가. 사건 개요"가 나오는 경우 (Format 3)
    """
    boundaries = [0]  # 첫 번째는 항상 시작
    
    pattern1 = re.compile(r'^[●·•]\s*사건번호\s*[:：]', re.MULTILINE)
    pattern2 = re.compile(r'^사례\s*\d+', re.MULTILINE)
    pattern3_num = re.compile(r'^\s*\d{1,2}\.\s*$', re.MULTILINE)
    pattern3_overview = re.compile(r'^\s*가\s*\.\s*사건\s*개요', re.MULTILINE)
    
    i = 0
    while i < len(elements):
        el = elements[i]
        text = el.text.strip()
        if not text:
            i += 1
            continue
        
        # Format 1: ● 사건번호:
        if pattern1.search(text):
            if i not in boundaries:
                boundaries.append(i)
            i += 1
            continue
        
        # Format 2: 사례 N
        if pattern2.search(text):
            if i not in boundaries:
                boundaries.append(i)
            i += 1
            continue
        
        # Format 3: N.\n[title]\n가. 사건 개요
        if pattern3_num.match(text):
            # 다음 몇 개 element에서 "가. 사건 개요" 확인
            found_overview = False
            for j in range(i + 1, min(i + 10, len(elements))):
                next_text = elements[j].text.strip()
                if pattern3_overview.search(next_text):
                    found_overview = True
                    break
            
            if found_overview and i not in boundaries:
                boundaries.append(i)
        
        i += 1
    
    return sorted(set(boundaries))


def detect_kca_case_boundaries(elements: List[NormElement]) -> List[int]:
    """
    KCA 케이스 경계 감지:
    - heading1: "사례 NN"
    - 이어지는 paragraph에 제목/사건번호/결정일자 패턴
    """
    boundaries = [0]
    
    heading_pattern = re.compile(r'^사례\s*\d+', re.MULTILINE)
    case_no_pattern = re.compile(r'사건번호\s*[:：]?\s*(\d{4}[가-힣A-Za-z]{0,10}\d+)', re.MULTILINE)
    date_pattern = re.compile(r'결정일자\s*[:：]?\s*(\d{4}\.?\s*\d{1,2}\.?\s*\d{1,2})', re.MULTILINE)
    
    i = 0
    while i < len(elements):
        el = elements[i]
        category = el.raw.get("category", "").lower()
        text = el.text.strip()
        
        # heading1에서 "사례 NN" 패턴 발견
        if category == "heading1" and heading_pattern.search(text):
            # 다음 몇 개 element에서 사건번호나 결정일자 확인
            found_metadata = False
            for j in range(i + 1, min(i + 5, len(elements))):
                next_text = elements[j].text.strip()
                if case_no_pattern.search(next_text) or date_pattern.search(next_text):
                    found_metadata = True
                    break
            
            if found_metadata and i not in boundaries:
                boundaries.append(i)
        
        i += 1
    
    return sorted(set(boundaries))


def detect_kcdrc_case_boundaries(elements: List[NormElement]) -> List[int]:
    """
    KCDRC 케이스 경계 감지:
    - 2016류: ▶ 사건번호 : ...
    - 2019류: 1. <제목> + 사건번호 : ...
    """
    boundaries = [0]
    
    pattern_2016 = re.compile(r'^▶\s*사건번호\s*[:：]', re.MULTILINE)
    pattern_2019 = re.compile(r'^\d+\.\s*.+사건번호\s*[:：]', re.MULTILINE)
    
    for i, el in enumerate(elements):
        text = el.text.strip()
        if not text:
            continue
        
        if pattern_2016.search(text) or pattern_2019.search(text):
            if i not in boundaries:
                boundaries.append(i)
    
    return sorted(set(boundaries))


def detect_case_boundaries(elements: List[NormElement], agency: str) -> List[int]:
    """부서별 케이스 경계 감지 래퍼 함수"""
    if agency.lower() == "ecmc" or agency.lower() == "eca" or agency.lower() == "ecrc":
        return detect_ecmc_case_boundaries(elements)
    elif agency.lower() == "kca":
        return detect_kca_case_boundaries(elements)
    elif agency.lower() == "kcdrc":
        return detect_kcdrc_case_boundaries(elements)
    else:
        # 기본: 모든 elements를 하나의 케이스로 처리
        return [0]


# -----------------------------
# 부서별 섹션 분류 및 청킹
# -----------------------------

def extract_case_metadata(elements: List[NormElement], start_idx: int, end_idx: int) -> Dict[str, Optional[str]]:
    """케이스 메타데이터 추출 (case_no, decision_date, title)"""
    case_elements = elements[start_idx:end_idx]
    case_text = "\n".join([el.text for el in case_elements])
    
    # 사건번호 패턴
    case_no_pattern = re.compile(
        r"(?:\[?사건\s*번호\s*[:：]?\s*)?(\d{4}[가-힣A-Za-z]{0,10}\d+)\]?"
    )
    case_no = None
    m = case_no_pattern.search(case_text)
    if m:
        case_no = re.sub(r"\s+", "", m.group(1))
    
    # 결정일자 패턴
    date_pattern = re.compile(
        r"(?:\[?결정\s*일자\s*[:：]?\s*)?(\d{4}\.?\s*\d{1,2}\.?\s*\d{1,2})\]?"
    )
    decision_date = None
    m = date_pattern.search(case_text)
    if m:
        date_str = re.sub(r"\s+", "", m.group(1))
        if "." not in date_str and len(date_str) == 8:
            decision_date = f"{date_str[:4]}.{date_str[4:6]}.{date_str[6:8]}"
        else:
            decision_date = date_str.rstrip(".")
    
    # 제목 추출 (첫 번째 heading1 또는 "사례 N" 다음 텍스트)
    title = None
    title_pattern = re.compile(
        r"(?m)^사\s*례\s*\d+\s*\n(.+?)(?=\[사건번호|\n+(?:주\s*문|합의\s*결과|사건\s*개요))",
        re.DOTALL
    )
    m = title_pattern.search(case_text)
    if m:
        title = re.sub(r'\s+', ' ', m.group(1).strip())
    
    return {
        "case_no": case_no,
        "decision_date": decision_date,
        "title": title
    }


def split_text_with_overlap(text: str, max_chars: int, overlap_chars: int) -> List[str]:
    """텍스트를 길이 제한과 overlap을 고려하여 분할"""
    if len(text) <= max_chars:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + max_chars
        
        # 문장 경계에서 자르기 (개선된 버전)
        if end < len(text):
            # 마지막 문장 끝 찾기
            last_period = text.rfind('.', start, end)
            last_newline = text.rfind('\n', start, end)
            cut_point = max(last_period, last_newline)
            
            if cut_point > start + max_chars * 0.7:  # 너무 앞에서 자르지 않도록
                end = cut_point + 1
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        # overlap만큼 뒤로 이동
        start = end - overlap_chars
        if start >= len(text):
            break
    
    return chunks


def create_chunks_from_section(
    section_type: str,
    section_elements: List[NormElement],
    metadata: Dict[str, Any],
    agency: str,
    source_pdf: str,
    case_index: int
) -> List[Chunk]:
    """섹션 elements로부터 청크 생성 (길이 제어 포함)"""
    if not section_elements:
        return []
    
    # 섹션 텍스트 병합
    section_text = "\n".join([el.text for el in section_elements]).strip()
    if not section_text:
        return []
    
    # 페이지 범위 계산
    pages = [el.page for el in section_elements if el.page]
    page_start = min(pages) if pages else 1
    page_end = max(pages) if pages else 1
    
    # 길이 제어: 토큰 수 또는 문자 수 기준
    tokens = estimate_tokens(section_text)
    chars = len(section_text)
    
    if tokens <= CHUNK_MAX_TOKENS and chars <= CHUNK_MAX_CHARS:
        # 하나의 청크로 충분
        overlap_chars = int(CHUNK_MAX_CHARS * CHUNK_OVERLAP_RATIO)
        return [Chunk(
            agency=agency,
            source_pdf=source_pdf,
            case_index=case_index,
            case_no=metadata.get("case_no"),
            decision_date=metadata.get("decision_date"),
            title=metadata.get("title"),
            section_type=section_type,
            page_start=page_start,
            page_end=page_end,
            chunk_index=1,
            text=section_text
        )]
    else:
        # 분할 필요
        overlap_chars = int(CHUNK_MAX_CHARS * CHUNK_OVERLAP_RATIO)
        text_chunks = split_text_with_overlap(section_text, CHUNK_MAX_CHARS, overlap_chars)
        
        chunks = []
        for idx, chunk_text in enumerate(text_chunks, start=1):
            # 각 청크의 페이지 범위는 대략적으로 계산
            # (실제로는 더 정교하게 계산할 수 있지만 여기서는 단순화)
            chunks.append(Chunk(
                agency=agency,
                source_pdf=source_pdf,
                case_index=case_index,
                case_no=metadata.get("case_no"),
                decision_date=metadata.get("decision_date"),
                title=metadata.get("title"),
                section_type=section_type,
                page_start=page_start,
                page_end=page_end,
                chunk_index=idx,
                text=chunk_text
            ))
        
        return chunks


def classify_ecmc_sections(elements: List[NormElement]) -> List[Tuple[str, List[NormElement]]]:
    """
    ECMC 섹션 분류:
    - facts: "1. 사건 개요" 또는 "가. 사건 개요"
    - claims: "2. 당사자 주장" 또는 "나. 당사자 주장"
    - analysis: "3. 조정부의 판단" 내 "이유" 부분
    - decision: "3. 조정부의 판단" 내 "주문" 부분 + "4. 조정안 권고결과"
    """
    sections: List[Tuple[str, List[NormElement]]] = []
    
    # 섹션 마커 패턴
    facts_pattern = re.compile(r'(?:^|\n|\s)\s*(?:1\s*[.)]|가\s*\.)\s*사건\s*개요', re.MULTILINE)
    claims_pattern = re.compile(r'(?:^|\n|\s)\s*(?:2\s*[.)]|나\s*\.)\s*(?:양\s*)?당사자\s*주장', re.MULTILINE)
    judgment_pattern = re.compile(
        r'(?:^|\n|\s)\s*(?:3\s*\.|다\s*\.)\s*(?:조정부\s*(?:의\s*)?판단|사무국\s*(?:판단|권고|합의\s*권고)|합의\s*권고|합의권고)',
        re.MULTILINE
    )
    result_pattern = re.compile(
        r'(?:^|\n|\s)\s*(?:4\s*\.|라\s*\.)\s*(?:조정안\s*권고결과|처리\s*결과|처리결과|조정\s*결과)',
        re.MULTILINE
    )
    decision_marker = re.compile(r'(?:^|\n)\s*주\s*문\s*(?:\n|$)|\s주\s*문\s', re.MULTILINE)
    reasoning_marker = re.compile(r'(?:^|\n)\s*이\s*유\s*(?:\n|$)|\s이\s*유\s', re.MULTILINE)
    
    # elements를 텍스트로 병합하여 섹션 경계 찾기
    full_text = "\n".join([el.text for el in elements])
    
    # 섹션 인덱스 찾기
    facts_start = None
    claims_start = None
    judgment_start = None
    result_start = None
    decision_start = None
    reasoning_start = None
    
    # 텍스트에서 패턴 검색하여 element 인덱스 매핑
    current_pos = 0
    element_positions = []
    for el in elements:
        element_positions.append((current_pos, current_pos + len(el.text), el))
        current_pos += len(el.text) + 1  # +1 for newline
    
    # 패턴 매칭하여 인덱스 찾기
    for pattern, var_name in [
        (facts_pattern, 'facts_start'),
        (claims_pattern, 'claims_start'),
        (judgment_pattern, 'judgment_start'),
        (result_pattern, 'result_start'),
        (decision_marker, 'decision_start'),
        (reasoning_marker, 'reasoning_start'),
    ]:
        match = pattern.search(full_text)
        if match:
            pos = match.start()
            # 해당 위치의 element 인덱스 찾기
            for idx, (start, end, el) in enumerate(element_positions):
                if start <= pos < end:
                    if var_name == 'facts_start':
                        facts_start = idx
                    elif var_name == 'claims_start':
                        claims_start = idx
                    elif var_name == 'judgment_start':
                        judgment_start = idx
                    elif var_name == 'result_start':
                        result_start = idx
                    elif var_name == 'decision_start':
                        decision_start = idx
                    elif var_name == 'reasoning_start':
                        reasoning_start = idx
                    break
    
    # 섹션별 elements 추출
    idx = 0
    
    # facts 섹션
    if facts_start is not None:
        end_idx = claims_start if claims_start is not None else (judgment_start if judgment_start is not None else len(elements))
        if end_idx > facts_start:
            sections.append((SECTION_FACTS, elements[facts_start:end_idx]))
            idx = end_idx
    
    # claims 섹션
    if claims_start is not None:
        end_idx = judgment_start if judgment_start is not None else len(elements)
        if end_idx > claims_start:
            sections.append((SECTION_CLAIMS, elements[claims_start:end_idx]))
            idx = end_idx
    
    # analysis/decision 섹션 (judgment 내부)
    if judgment_start is not None:
        end_idx = result_start if result_start is not None else len(elements)
        
        # 주문과 이유 분리
        if decision_start is not None and reasoning_start is not None:
            if decision_start < reasoning_start:
                # 주문이 먼저
                sections.append((SECTION_DECISION, elements[decision_start:reasoning_start]))
                sections.append((SECTION_ANALYSIS, elements[reasoning_start:end_idx]))
            else:
                # 이유가 먼저
                sections.append((SECTION_ANALYSIS, elements[reasoning_start:decision_start]))
                sections.append((SECTION_DECISION, elements[decision_start:end_idx]))
        elif decision_start is not None:
            sections.append((SECTION_DECISION, elements[decision_start:end_idx]))
        elif reasoning_start is not None:
            sections.append((SECTION_ANALYSIS, elements[reasoning_start:end_idx]))
        else:
            # 주문/이유 마커가 없으면 전체를 analysis로
            sections.append((SECTION_ANALYSIS, elements[judgment_start:end_idx]))
        
        idx = end_idx
    
    # result 섹션 (decision에 포함)
    if result_start is not None and result_start < len(elements):
        # decision 섹션이 있으면 병합, 없으면 별도 decision으로
        if sections and sections[-1][0] == SECTION_DECISION:
            # 마지막 decision 섹션에 병합
            prev_type, prev_els = sections[-1]
            sections[-1] = (prev_type, prev_els + elements[result_start:])
        else:
            sections.append((SECTION_DECISION, elements[result_start:]))
    
    # 섹션이 없으면 전체를 facts로
    if not sections:
        sections.append((SECTION_FACTS, elements))
    
    return sections


def chunk_for_ecmc(elements: List[NormElement], metadata: Dict[str, Any], 
                   agency: str, source_pdf: str, case_index: int) -> List[Chunk]:
    """ECMC 전용 청킹: facts/claims/analysis/decision 4분할"""
    sections = classify_ecmc_sections(elements)
    
    all_chunks = []
    for section_type, section_elements in sections:
        chunks = create_chunks_from_section(
            section_type, section_elements, metadata, agency, source_pdf, case_index
        )
        all_chunks.extend(chunks)
    
    return all_chunks


def classify_kca_sections(elements: List[NormElement]) -> List[Tuple[str, List[NormElement]]]:
    """
    KCA 섹션 분류:
    - 의료형: facts, claims, analysis, decision (4분할)
    - 일반/서비스형: decision, facts+analysis (2분할)
    """
    sections: List[Tuple[str, List[NormElement]]] = []
    
    # KCA 섹션 마커 패턴
    decision_pattern = re.compile(r'(?:^|\n)\s*주\s*문\s*(?:\n|$)|\s주\s*문\s', re.MULTILINE)
    reason_pattern = re.compile(r'(?:^|\n)\s*이\s*유\s*(?:\n|$)|\s이\s*유\s', re.MULTILINE)
    parties_claim_pattern = re.compile(r'(?:^|\n|\s)\s*(?:1\s*\.|당사자\s*주장)', re.MULTILINE)
    facts_pattern = re.compile(r'(?:^|\n|\s)\s*(?:기초\s*사실|사건\s*개요)', re.MULTILINE)
    judgment_pattern = re.compile(r'(?:^|\n|\s)\s*(?:2\s*\.|판단)', re.MULTILINE)
    
    full_text = "\n".join([el.text for el in elements])
    
    # element 위치 매핑
    current_pos = 0
    element_positions = []
    for el in elements:
        element_positions.append((current_pos, current_pos + len(el.text), el))
        current_pos += len(el.text) + 1
    
    # 패턴 매칭
    decision_start = None
    reason_start = None
    parties_claim_start = None
    facts_start = None
    judgment_start = None
    
    for pattern, var_name in [
        (decision_pattern, 'decision_start'),
        (reason_pattern, 'reason_start'),
        (parties_claim_pattern, 'parties_claim_start'),
        (facts_pattern, 'facts_start'),
        (judgment_pattern, 'judgment_start'),
    ]:
        match = pattern.search(full_text)
        if match:
            pos = match.start()
            for idx, (start, end, el) in enumerate(element_positions):
                if start <= pos < end:
                    if var_name == 'decision_start':
                        decision_start = idx
                    elif var_name == 'reason_start':
                        reason_start = idx
                    elif var_name == 'parties_claim_start':
                        parties_claim_start = idx
                    elif var_name == 'facts_start':
                        facts_start = idx
                    elif var_name == 'judgment_start':
                        judgment_start = idx
                    break
    
    # 의료형인지 판단 (parties_claim과 facts가 모두 있으면 의료형)
    is_medical = parties_claim_start is not None and facts_start is not None
    
    if is_medical:
        # 의료형: 4분할
        idx = 0
        
        if facts_start is not None:
            end_idx = parties_claim_start if parties_claim_start is not None else len(elements)
            if end_idx > facts_start:
                sections.append((SECTION_FACTS, elements[facts_start:end_idx]))
                idx = end_idx
        
        if parties_claim_start is not None:
            end_idx = judgment_start if judgment_start is not None else len(elements)
            if end_idx > parties_claim_start:
                sections.append((SECTION_CLAIMS, elements[parties_claim_start:end_idx]))
                idx = end_idx
        
        if judgment_start is not None:
            end_idx = decision_start if decision_start is not None else len(elements)
            if end_idx > judgment_start:
                sections.append((SECTION_ANALYSIS, elements[judgment_start:end_idx]))
                idx = end_idx
        
        if decision_start is not None:
            sections.append((SECTION_DECISION, elements[decision_start:]))
    else:
        # 일반/서비스형: 2분할
        if decision_start is not None:
            sections.append((SECTION_DECISION, elements[decision_start:]))
        
        # 나머지는 facts+analysis로
        remaining_start = 0
        if decision_start is not None:
            remaining_start = decision_start
        
        if remaining_start < len(elements):
            remaining_elements = elements[remaining_start:decision_start] if decision_start else elements
            if remaining_elements:
                # reason이 있으면 analysis로, 없으면 facts로
                if reason_start is not None and reason_start >= remaining_start:
                    # reason 이전은 facts, 이후는 analysis
                    reason_idx = reason_start - remaining_start
                    if reason_idx > 0:
                        sections.append((SECTION_FACTS, remaining_elements[:reason_idx]))
                    sections.append((SECTION_ANALYSIS, remaining_elements[reason_idx:]))
                else:
                    sections.append((SECTION_FACTS, remaining_elements))
    
    if not sections:
        sections.append((SECTION_FACTS, elements))
    
    return sections


def chunk_for_kca(elements: List[NormElement], metadata: Dict[str, Any],
                  agency: str, source_pdf: str, case_index: int) -> List[Chunk]:
    """KCA 전용 청킹: 일반형(2분할)과 의료형(4분할) 템플릿 대응"""
    sections = classify_kca_sections(elements)
    
    all_chunks = []
    for section_type, section_elements in sections:
        chunks = create_chunks_from_section(
            section_type, section_elements, metadata, agency, source_pdf, case_index
        )
        all_chunks.extend(chunks)
    
    return all_chunks


def classify_kcdrc_sections(elements: List[NormElement]) -> List[Tuple[str, List[NormElement]]]:
    """
    KCDRC 섹션 분류:
    - facts: 사건개요
    - claims: 당사자의 주장
    - mediation_outcome: 조정회의 결과(조정안+이유) + 조정결과
    """
    sections: List[Tuple[str, List[NormElement]]] = []
    
    # KCDRC 섹션 마커 패턴
    facts_pattern = re.compile(r'(?:^|\n|\s)\s*사건\s*개요', re.MULTILINE)
    claims_pattern = re.compile(r'(?:^|\n|\s)\s*당사자\s*(?:의\s*)?주장', re.MULTILINE)
    mediation_pattern = re.compile(r'(?:^|\n|\s)\s*조정\s*회의\s*결과|조정\s*안', re.MULTILINE)
    result_pattern = re.compile(r'(?:^|\n|\s)\s*조정\s*결과', re.MULTILINE)
    
    full_text = "\n".join([el.text for el in elements])
    
    # element 위치 매핑
    current_pos = 0
    element_positions = []
    for el in elements:
        element_positions.append((current_pos, current_pos + len(el.text), el))
        current_pos += len(el.text) + 1
    
    # 패턴 매칭
    facts_start = None
    claims_start = None
    mediation_start = None
    result_start = None
    
    for pattern, var_name in [
        (facts_pattern, 'facts_start'),
        (claims_pattern, 'claims_start'),
        (mediation_pattern, 'mediation_start'),
        (result_pattern, 'result_start'),
    ]:
        match = pattern.search(full_text)
        if match:
            pos = match.start()
            for idx, (start, end, el) in enumerate(element_positions):
                if start <= pos < end:
                    if var_name == 'facts_start':
                        facts_start = idx
                    elif var_name == 'claims_start':
                        claims_start = idx
                    elif var_name == 'mediation_start':
                        mediation_start = idx
                    elif var_name == 'result_start':
                        result_start = idx
                    break
    
    idx = 0
    
    # facts 섹션
    if facts_start is not None:
        end_idx = claims_start if claims_start is not None else (mediation_start if mediation_start is not None else len(elements))
        if end_idx > facts_start:
            sections.append((SECTION_FACTS, elements[facts_start:end_idx]))
            idx = end_idx
    
    # claims 섹션
    if claims_start is not None:
        end_idx = mediation_start if mediation_start is not None else len(elements)
        if end_idx > claims_start:
            sections.append((SECTION_CLAIMS, elements[claims_start:end_idx]))
            idx = end_idx
    
    # mediation_outcome 섹션 (조정회의 결과 + 조정결과)
    if mediation_start is not None:
        end_idx = len(elements)
        sections.append((SECTION_MEDIATION_OUTCOME, elements[mediation_start:end_idx]))
    elif result_start is not None:
        sections.append((SECTION_MEDIATION_OUTCOME, elements[result_start:]))
    
    if not sections:
        sections.append((SECTION_FACTS, elements))
    
    return sections


def chunk_for_kcdrc(elements: List[NormElement], metadata: Dict[str, Any],
                    agency: str, source_pdf: str, case_index: int) -> List[Chunk]:
    """KCDRC 전용 청킹: facts/claims/mediation_outcome 분류"""
    sections = classify_kcdrc_sections(elements)
    
    all_chunks = []
    for section_type, section_elements in sections:
        chunks = create_chunks_from_section(
            section_type, section_elements, metadata, agency, source_pdf, case_index
        )
        all_chunks.extend(chunks)
    
    return all_chunks


# -----------------------------
# MAIN
# -----------------------------

def process_response_json(response_path: Path, output_path: Path) -> int:
    """response.json 파일을 처리하여 chunks_vector_db.jsonl 생성"""
    print(f"  Processing: {response_path.name}")
    
    # response.json 읽기
    with response_path.open("r", encoding="utf-8") as f:
        resp = json.load(f)
    
    # elements 추출
    elements = extract_elements(resp)
    if not elements:
        print(f"    ⚠ No elements found")
        return 0
    
    # 부서 감지
    source_pdf = response_path.parent.name
    agency = infer_agency_from_filename(source_pdf)
    if agency == "unknown":
        # 디렉토리명에서도 시도
        parent_name = response_path.parent.parent.name
        agency = infer_agency_from_filename(parent_name)
        # ECMC는 ecmc로 시작하는 경우가 많음
        if agency == "unknown" and "ecmc" in source_pdf.lower():
            agency = "ecmc"
    
    print(f"    Agency: {agency}")
    
    # 공통 전처리
    filtered_elements = filter_elements(elements)
    print(f"    Elements: {len(elements)} -> {len(filtered_elements)} (filtered)")
    
    # 케이스 경계 감지
    boundaries = detect_case_boundaries(filtered_elements, agency)
    print(f"    Cases detected: {len(boundaries)}")
    
    # 각 케이스별로 청킹
    all_chunks: List[Chunk] = []
    
    for case_idx in range(len(boundaries)):
        start_idx = boundaries[case_idx]
        end_idx = boundaries[case_idx + 1] if case_idx + 1 < len(boundaries) else len(filtered_elements)
        case_elements = filtered_elements[start_idx:end_idx]
        
        # 케이스 메타데이터 추출
        metadata = extract_case_metadata(case_elements, 0, len(case_elements))
        
        # 부서별 청킹 (case_index는 1부터 시작)
        case_index = case_idx + 1
        if agency.lower() in ("ecmc", "eca", "ecrc"):
            chunks = chunk_for_ecmc(case_elements, metadata, agency, source_pdf, case_index)
        elif agency.lower() == "kca":
            chunks = chunk_for_kca(case_elements, metadata, agency, source_pdf, case_index)
        elif agency.lower() == "kcdrc":
            chunks = chunk_for_kcdrc(case_elements, metadata, agency, source_pdf, case_index)
        else:
            # 기본: 전체를 하나의 청크로
            chunks = create_chunks_from_section(
                SECTION_FACTS, case_elements, metadata, agency, source_pdf, case_index
            )
        
        all_chunks.extend(chunks)
    
    # JSONL 출력
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")
    
    print(f"    ✓ Generated: {output_path.name} ({len(all_chunks)} chunks)")
    return len(all_chunks)


def merge_by_agency(input_dir: Path, output_dir: Path) -> None:
    """각 기관별로 chunks_vector_db.jsonl 파일들을 병합"""
    input_root = Path(input_dir)
    if not input_root.exists():
        print(f"Error: {input_root} not found")
        return
    
    # 모든 chunks_vector_db.jsonl 파일 찾기
    chunk_files = list(input_root.rglob("chunks_vector_db.jsonl"))
    if not chunk_files:
        print(f"No chunks_vector_db.jsonl files found in {input_root}")
        return
    
    print(f"Found {len(chunk_files)} chunks_vector_db.jsonl files")
    
    # 기관별로 그룹핑
    agency_files: Dict[str, List[Path]] = {}
    for chunk_file in chunk_files:
        # 파일에서 agency 읽기
        try:
            with chunk_file.open("r", encoding="utf-8") as f:
                first_line = f.readline()
                if first_line.strip():
                    record = json.loads(first_line)
                    agency = record.get("agency", "unknown").lower()
                    # ECMC 관련 기관 통합 (ecmc, eca, ecrc -> ecmc)
                    if agency in ("eca", "ecrc"):
                        agency = "ecmc"
                    agency_files.setdefault(agency, []).append(chunk_file)
        except Exception as e:
            print(f"  ⚠ Skipped {chunk_file}: {e}")
            continue
    
    # 출력 디렉토리 생성
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 각 기관별로 병합
    for agency, files in agency_files.items():
        if agency == "unknown":
            continue
        
        output_path = output_dir / f"{agency}.jsonl"
        print(f"\n[MERGING {agency.upper()}]")
        print(f"  Found {len(files)} files")
        
        total_chunks = 0
        with output_path.open("w", encoding="utf-8") as f_out:
            for chunk_file in files:
                count = 0
                try:
                    with chunk_file.open("r", encoding="utf-8") as f_in:
                        for line in f_in:
                            if line.strip():
                                f_out.write(line)
                                count += 1
                                total_chunks += 1
                    print(f"    ✓ {chunk_file.parent.name}: {count} chunks")
                except Exception as e:
                    print(f"    ✗ {chunk_file.parent.name}: Error - {e}")
        
        print(f"  ✓ Saved: {output_path.name} (total: {total_chunks} chunks)")
    
    print(f"\n[DONE] Merged files saved to {output_dir}")


def main():
    assert_crawling_env()
    
    ap = argparse.ArgumentParser(
        description="Vector DB용 구조 기반 청킹 스크립트",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--input", help="단일 디렉토리 경로 (response.json이 있는 디렉토리)")
    ap.add_argument("--input-dir", default="kjw/data/raw/parsed", 
                   help="입력 디렉토리 (기본: kjw/data/raw/parsed)")
    ap.add_argument("--merge", action="store_true",
                   help="기관별로 chunks_vector_db.jsonl 파일들을 병합하여 kjw/data/preprocess/에 저장")
    ap.add_argument("--output-dir", default="kjw/data/preprocess",
                   help="병합 파일 출력 디렉토리 (기본: kjw/data/preprocess)")
    
    args = ap.parse_args()
    
    # 병합 모드
    if args.merge:
        merge_by_agency(Path(args.input_dir), Path(args.output_dir))
        return 0
    
    if args.input:
        # 단일 디렉토리 처리
        input_dir = Path(args.input)
        response_path = input_dir / "response.json"
        if not response_path.exists():
            print(f"Error: {response_path} not found")
            return 1
        
        output_path = input_dir / "chunks_vector_db.jsonl"
        process_response_json(response_path, output_path)
    else:
        # 전체 디렉토리 일괄 처리
        input_root = Path(args.input_dir)
        if not input_root.exists():
            print(f"Error: {input_root} not found")
            return 1
        
        response_files = list(input_root.rglob("response.json"))
        if not response_files:
            print(f"No response.json files found in {input_root}")
            return 1
        
        print(f"Found {len(response_files)} response.json files")
        total_chunks = 0
        
        for response_path in response_files:
            output_path = response_path.parent / "chunks_vector_db.jsonl"
            chunks_count = process_response_json(response_path, output_path)
            total_chunks += chunks_count
        
        print(f"\n[DONE] Total chunks generated: {total_chunks}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
