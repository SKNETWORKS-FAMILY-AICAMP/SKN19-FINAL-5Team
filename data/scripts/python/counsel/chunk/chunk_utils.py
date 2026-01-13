# scripts/preprocess/chunk/chunk_utils.py
"""
공통 청킹 유틸리티 함수
"""
import re
from typing import List


# 청크 길이 제어 (kjw/scripts/chunk_for_vector_db.py와 동일)
# 토큰 기준 (한글은 대략 2자/토큰 가정)
CHUNK_MIN_TOKENS = 600
CHUNK_MAX_TOKENS = 1600
CHUNK_MIN_CHARS = 1200
CHUNK_MAX_CHARS = 3200
CHUNK_OVERLAP_RATIO = 0.1  # 10% overlap

# 하위 호환성을 위한 별칭
TARGET_CHARS_MIN = CHUNK_MIN_CHARS
TARGET_CHARS_MAX = CHUNK_MAX_CHARS
OVERLAP_CHARS_MIN = int(CHUNK_MAX_CHARS * CHUNK_OVERLAP_RATIO)
OVERLAP_CHARS_MAX = int(CHUNK_MAX_CHARS * CHUNK_OVERLAP_RATIO)
MIN_CHARS = CHUNK_MIN_CHARS
HARD_MAX = CHUNK_MAX_CHARS * 2  # 안전 마진


def estimate_tokens(text: str) -> int:
    """
    텍스트의 대략적인 토큰 수 추정 (kjw 스크립트와 동일)
    한글 기준 대략 2자/토큰 가정
    
    Args:
        text: 텍스트
    
    Returns:
        추정 토큰 수
    """
    if not text:
        return 0
    
    # 한글 기준 대략 2자/토큰 가정 (kjw 스크립트와 동일)
    return len(text) // 2


def normalize_text(text: str) -> str:
    """
    텍스트 정규화:
    - \n, \t → 공백 치환
    - 공백 2개 이상 → 1개로 축약
    - 선행/후행 공백 제거
    """
    if not text:
        return ""
    
    # \n, \t → 공백
    text = text.replace("\n", " ").replace("\t", " ")
    
    # 공백 2개 이상 → 1개
    text = re.sub(r"\s+", " ", text)
    
    # 선행/후행 공백 제거
    return text.strip()


def smart_cut(text: str, limit: int) -> int:
    """
    limit 근처에서 자연스럽게 끊을 위치 찾기
    - 줄바꿈 우선
    - 문장 끝(마침표/다./함.) 차선
    """
    if len(text) <= limit:
        return len(text)

    window = text[:limit]
    
    # 가장 마지막 줄바꿈에서 자르기
    nl = window.rfind("\n")
    if nl >= int(limit * 0.6):
        return nl + 1

    # 문장 끝 찾기 (마침표/다./함.)
    punct = max(
        window.rfind(". "),
        window.rfind("다."),
        window.rfind("함."),
        window.rfind("임."),
        window.rfind("됨."),
    )
    if punct >= int(limit * 0.6):
        return punct + 2  # 마침표와 공백 포함

    return limit


def split_text_with_overlap(text: str, max_chars: int, overlap_chars: int) -> List[str]:
    """
    텍스트를 길이 제한과 overlap을 고려하여 분할 (kjw 스크립트와 동일한 방식)
    
    Args:
        text: 분할할 텍스트
        max_chars: 최대 문자 수
        overlap_chars: overlap 문자 수
    
    Returns:
        분할된 청크 리스트
    """
    if len(text) <= max_chars:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + max_chars
        
        # 문장 경계에서 자르기 (kjw 스크립트와 동일)
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


def split_with_overlap(
    text: str,
    target_chars: int = CHUNK_MAX_CHARS,
    overlap_chars: int = None,
    hard_max: int = None,
) -> List[str]:
    """
    긴 텍스트를 target_chars 근처로 자르되, overlap_chars 만큼 겹치게 분할
    (kjw 스크립트 방식 사용)
    
    Args:
        text: 분할할 텍스트
        target_chars: 목표 청크 크기 (기본값: CHUNK_MAX_CHARS)
        overlap_chars: overlap 크기 (기본값: CHUNK_MAX_CHARS * CHUNK_OVERLAP_RATIO)
        hard_max: 사용하지 않음 (하위 호환성)
    
    Returns:
        분할된 청크 리스트
    """
    text = text.strip()
    if not text:
        return []
    
    # overlap_chars가 지정되지 않으면 기본값 사용
    if overlap_chars is None:
        overlap_chars = int(target_chars * CHUNK_OVERLAP_RATIO)
    
    # kjw 스크립트 방식 사용
    return split_text_with_overlap(text, target_chars, overlap_chars)


def merge_short_chunks(chunks: List[str], min_chars: int = CHUNK_MIN_CHARS) -> List[str]:
    """
    너무 짧은 청크는 앞 청크에 합쳐서 "조사 잘림/문장 파편" 방지
    
    Args:
        chunks: 청크 리스트
        min_chars: 최소 크기 (이보다 짧으면 병합)
    
    Returns:
        병합된 청크 리스트
    """
    if not chunks:
        return []

    merged = []
    for c in chunks:
        c = c.strip()
        if not c:
            continue

        if len(c) < min_chars and merged:
            merged[-1] = (merged[-1].rstrip() + "\n" + c).strip()
        else:
            merged.append(c)

    # 첫 청크가 너무 짧으면 뒤와 합치기
    if len(merged) >= 2 and len(merged[0]) < min_chars:
        merged[1] = (merged[0].rstrip() + "\n" + merged[1]).strip()
        merged = merged[1:]

    return merged


def split_by_section_markers(
    text: str,
    markers: List[str],
    preserve_markers: bool = True,
) -> List[tuple[str, str]]:
    """
    섹션 마커(가./나./다. 또는 (1)(2) 등)를 기준으로 텍스트 분할
    
    Args:
        text: 분할할 텍스트
        markers: 섹션 마커 패턴 리스트 (예: ["가.", "나.", "다."])
        preserve_markers: 마커를 포함할지 여부
    
    Returns:
        (section_title, section_text) 튜플 리스트
    """
    if not text or not markers:
        return [("본문", text)]
    
    # 마커를 정규식으로 변환
    escaped_markers = [re.escape(m) for m in markers]
    pattern = "|".join(escaped_markers)
    marker_re = re.compile(f"^({pattern})", re.M)
    
    lines = text.splitlines()
    hits = []
    for i, line in enumerate(lines):
        if marker_re.search(line.strip()):
            hits.append((i, line.strip()))
    
    if not hits:
        return [("본문", text)]
    
    # 섹션 단위로 자르기
    out = []
    for idx, (start_i, header) in enumerate(hits):
        end_i = hits[idx + 1][0] if idx + 1 < len(hits) else len(lines)
        chunk_lines = lines[start_i:end_i]
        section_text = "\n".join(chunk_lines).strip()
        
        if preserve_markers:
            out.append((header, section_text))
        else:
            # 마커 제거
            clean_text = section_text
            for marker in markers:
                clean_text = clean_text.replace(marker, "", 1)
            out.append((header, clean_text.strip()))
    
    return out


def split_reasoning_by_structure(text: str) -> List[str]:
    """
    reasoning 텍스트를 대문단(가./나./다.) → 소문단((1)(2)) 단위로 분할
    
    Args:
        text: reasoning 텍스트
    
    Returns:
        분할된 청크 리스트
    """
    if not text:
        return []
    
    # 대문단 마커: 가., 나., 다., 라., 마., 바., 사., 아., 자., 차., 카., 타., 파., 하.
    major_markers = [
        r"^가\.\s*",
        r"^나\.\s*",
        r"^다\.\s*",
        r"^라\.\s*",
        r"^마\.\s*",
        r"^바\.\s*",
        r"^사\.\s*",
        r"^아\.\s*",
        r"^자\.\s*",
        r"^차\.\s*",
        r"^카\.\s*",
        r"^타\.\s*",
        r"^파\.\s*",
        r"^하\.\s*",
    ]
    
    # 소문단 마커: (1), (2), (3) 등
    minor_markers = [r"^\(\d+\)\s*"]
    
    # 먼저 대문단으로 분할
    major_pattern = re.compile("|".join(major_markers), re.M)
    lines = text.splitlines()
    
    major_sections = []
    current_section = []
    current_header = None
    
    for line in lines:
        line_stripped = line.strip()
        major_match = major_pattern.match(line_stripped)
        
        if major_match:
            # 이전 섹션 저장
            if current_section:
                major_sections.append((current_header, "\n".join(current_section)))
            # 새 섹션 시작
            current_header = line_stripped
            current_section = [line]
        else:
            current_section.append(line)
    
    # 마지막 섹션 저장
    if current_section:
        major_sections.append((current_header or "본문", "\n".join(current_section)))
    
    # 대문단이 없으면 전체를 하나로
    if not major_sections:
        return [text]
    
    # 각 대문단을 소문단으로 추가 분할
    all_chunks = []
    for header, section_text in major_sections:
        # 소문단 마커로 분할
        minor_pattern = re.compile("|".join(minor_markers), re.M)
        minor_lines = section_text.splitlines()
        
        minor_sections = []
        current_minor = []
        current_minor_header = None
        
        for line in minor_lines:
            line_stripped = line.strip()
            minor_match = minor_pattern.match(line_stripped)
            
            if minor_match:
                if current_minor:
                    minor_sections.append((current_minor_header, "\n".join(current_minor)))
                current_minor_header = line_stripped
                current_minor = [line]
            else:
                current_minor.append(line)
        
        if current_minor:
            minor_sections.append((current_minor_header or header, "\n".join(current_minor)))
        
        # 소문단이 있으면 그것을 사용, 없으면 대문단 전체 사용
        if minor_sections and len(minor_sections) > 1:
            # 소문단이 여러 개면 각각을 별도 청크로
            for mh, mt in minor_sections:
                # 헤더가 있으면 포함
                if header and not mt.startswith(header):
                    chunk_text = f"{header}\n{mt}"
                else:
                    chunk_text = mt
                all_chunks.append(chunk_text.strip())
        else:
            # 소문단이 없거나 1개뿐이면 대문단 전체 사용
            all_chunks.append(section_text.strip())
    
    return [c for c in all_chunks if c]
