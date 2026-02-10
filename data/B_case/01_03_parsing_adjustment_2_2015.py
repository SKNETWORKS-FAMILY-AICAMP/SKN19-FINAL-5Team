"""
01_03_parsing_adjustment_2_2015.py
---------------------------------
KISA 2015년 전자거래 분쟁조정 사례집 PDF를 하이브리드 방식으로 파싱합니다.

전략:
1. Stage 1: pdfplumber + 정규식으로 텍스트 기반 파싱 (빠름, 기본 방식)
2. Stage 2: OpenAI Vision API로 이미지 기반 파싱 (높은 정확도, fallback용)

요구사항:
- JSON은 원본 PDF와 동일한 경로에 동일한 이름으로 .json 저장
- 권고/조정 케이스 구분
- 텍스트 파싱 실패 시 Vision API로 재시도
"""

from __future__ import annotations

import json
import re
import os
import base64
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from io import BytesIO

import pdfplumber
import fitz
from PIL import Image
import requests
from dotenv import load_dotenv

load_dotenv()

RECO_LABEL = "권고"
ADJ_LABEL = "조정"

# OpenAI API 설정
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


# -----------------------------
# 경로 설정 (상대경로)
# -----------------------------
BASE_DIR = Path(__file__).resolve().parent
PDF_PATH = BASE_DIR / "01_B_parsed" / "02_02_AdjustmentCase" / "02_kisa" / "2015년 전자거래 분쟁조정 사례집.pdf"
JSON_PATH = PDF_PATH.with_suffix(".json")


# -----------------------------
# 정규식 패턴
# -----------------------------
# 불릿(•)이 앞에 붙는 경우가 많아서 optional 처리
BULLET = r"[•\u2022]?"  # • 또는 bullet 문자

RE_CASE_NO = re.compile(rf"(?m)^\s*{BULLET}\s*사건번호\s*[:：]\s*(.+)\s*$")
RE_METHOD  = re.compile(rf"(?m)^\s*{BULLET}\s*조정방법\s*[:：]\s*(.+)\s*$")
RE_TITLE   = re.compile(rf"(?m)^\s*{BULLET}\s*사건명칭\s*[:：]\s*(.+)\s*$")

RE_SEC1 = re.compile(r"(?m)^\s*(?:제\s*)?1\.\s*사건\s*개요\s*\d*\s*$")
RE_SEC2 = re.compile(r"(?m)^\s*(?:제\s*)?2\.\s*양당사자\s*주장(?:\s*\(요지\))?.*\s*$")

RE_SEC3_RECO = re.compile(r"(?m)^\s*3\.\s*(?:\uC0AC\uBB34\uAD6D\s*)?\uD310\uB2E8\s*$")
RE_SEC3_ADJ  = re.compile(r"(?m)^\s*3\.\s*(?:\uC870\uC815\uAD6D|\uC870\uC815\uBD80)\s*\uC758?\s*\uD310\uB2E8\s*$")

RE_SEC4 = re.compile(r"(?m)^\s*4\.\s*(권고안\s*수락여부|조정안\s*수락\s*여부).*\s*$")

RE_CLAIM_A = re.compile(r"(?m)^\s*가\.\s*신청인.*\s*$")
RE_CLAIM_B = re.compile(r"(?m)^\s*나\.\s*피신청인.*\s*$")

# 주문/이유 마커 (표현 흔들림 대비)
RE_ORDER_MARK = re.compile(r"(?mi)^\s*(?:[\uAC00-\uD7A3]\.\s*)?\[?\s*\uC8FC\s*\uBB38\s*\]?\s*$")
RE_REASON_MARK = re.compile(r"(?mi)^\s*(?:[\uAC00-\uD7A3]\.\s*)?\[?\s*\uC774\s*\uC720\s*\]?\s*$")


# ============================
# OpenAI Vision API 함수
# ============================
def pdf_pages_to_base64_images(pdf_path: str, start_page: int, end_page: int, dpi: int = 150) -> List[str]:
    """PDF 페이지를 base64 인코딩된 이미지로 변환"""
    images_b64 = []
    try:
        doc = fitz.open(pdf_path)
        for page_num in range(start_page, min(end_page, len(doc))):
            page = doc[page_num]
            pix = page.get_pixmap(dpi=dpi)
            img_data = pix.tobytes("png")
            img_b64 = base64.standard_b64encode(img_data).decode("utf-8")
            images_b64.append(img_b64)
        doc.close()
    except Exception as e:
        print(f"    이미지 변환 오류: {e}")
        return []
    return images_b64


def parse_case_with_vision_api(images_b64: List[str], case_type: str = "조정", max_retries: int = 3) -> Optional[Dict]:
    """OpenAI Vision API로 케이스 파싱"""
    if not images_b64:
        return None

    if case_type == "권고":
        prompt = """이 이미지들은 전자거래 분쟁조정 사례집의 권고 사례입니다.
다음 JSON 형식으로 **원문 그대로** 추출하세요:

{
  "case_number": "사건번호",
  "method": "조정방법",
  "title": "사건명칭",
  "overview": "1. 사건개요 원문",
  "claims": {
    "applicant": ["신청인 주장 원문"],
    "respondent": ["피신청인 주장 원문"]
  },
  "judgement": {
    "order": "주문 원문",
    "reason": "이유 원문"
  },
  "result": "4. 결과 원문"
}

**중요**:
- 모든 내용을 원문 그대로 추출 (요약 금지)
- 줄바꿈과 문단 구조 유지
- JSON만 반환 (다른 텍스트 없이)"""
    else:
        prompt = """이 이미지들은 전자거래 분쟁조정 사례집의 조정 사례입니다.
다음 JSON 형식으로 **원문 그대로** 추출하세요:

{
  "case_number": "사건번호",
  "method": "조정방법",
  "title": "사건명칭",
  "overview": "1. 사건개요 원문",
  "claims": {
    "applicant": ["신청인 주장 원문"],
    "respondent": ["피신청인 주장 원문"]
  },
  "judgement": {
    "order": "주문 원문",
    "reason": "이유 원문"
  },
  "result": "4. 조정 결과 원문"
}

**중요**:
- 모든 내용을 원문 그대로 추출 (요약 금지)
- 줄바꿈과 문단 구조 유지
- JSON만 반환 (다른 텍스트 없이)"""

    try:
        # 이미지 content 구성
        content = [{"type": "text", "text": prompt}]
        for img_b64 in images_b64:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img_b64}"}
            })

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }

        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.2,
            "max_tokens": 4000
        }

        # 재시도 로직
        for attempt in range(max_retries):
            try:
                response = requests.post(OPENAI_API_URL, json=payload, headers=headers, timeout=60)
                response.raise_for_status()
                break  # 성공하면 루프 탈출
            except requests.exceptions.HTTPError as e:
                if response.status_code == 429 and attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 10  # 10초, 20초, 40초
                    print(f"    Rate limit 재시도 ({attempt + 1}/{max_retries})... {wait_time}초 대기")
                    time.sleep(wait_time)
                else:
                    raise

        result = response.json()
        text = result["choices"][0]["message"]["content"].strip()

        # JSON 추출 (마크다운 코드블록 제거)
        json_text = text
        if "```json" in text:
            m = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", text)
            if m:
                json_text = m.group(1)
        elif "```" in text:
            m = re.search(r"```\s*(\{[\s\S]*?\})\s*```", text)
            if m:
                json_text = m.group(1)
        else:
            # 코드블록 없으면 JSON 객체 부분만 추출
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                json_text = m.group(0)

        # JSON 정정: trailing comma 제거
        json_text = re.sub(r',(\s*[}\]])', r'\1', json_text)

        data = json.loads(json_text)
        data["parsing_method"] = "vision_openai"
        return data

    except json.JSONDecodeError as e:
        print(f"    Vision API JSON 파싱 오류: {e}")
        return None
    except Exception as e:
        print(f"    Vision API 오류: {e}")
        return None


# -----------------------------
# 유틸
# -----------------------------
def norm_text(t: str) -> str:
    t = (t or "").replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

HANGUL_RE = re.compile(r"[\uAC00-\uD7A3]")
SINGLE_HANGUL_RE = re.compile(r"^[\uAC00-\uD7A3]$")
ROMAN_NUM_RE = re.compile(r"^[\u2160-\u2169]\.")
SARYEJIP_RE = re.compile(r"\uC0AC\uB840\uC9D1")  # ???

def is_single_hangul(s: str) -> bool:
    return bool(SINGLE_HANGUL_RE.fullmatch(s))

def clean_section_text(t: Optional[str]) -> Optional[str]:
    if not t:
        return None
    # Remove footer-like boilerplate blocks: year/page/short hangul title
    t = re.sub(r"\d{4}\uB144\s*\d{1,3}\s*[\uAC00-\uD7A3]{3,}", "", t)
    t = re.sub(r"\n?\d{4}\uB144\s*\n\s*\d{1,3}\s*\n\s*[\uAC00-\uD7A3]{3,}\s*\n?", "\n", t)

    lines = []
    raw_lines = t.splitlines()
    skip_next = False
    for i, ln in enumerate(raw_lines):
        if skip_next:
            skip_next = False
            continue
        s = ln.strip()
        # Merge vertical single-hangul lines like "?" + "?"
        if is_single_hangul(s):
            next_s = raw_lines[i + 1].strip() if i + 1 < len(raw_lines) else ""
            if is_single_hangul(next_s):
                combo = s + next_s
                if combo == "??":
                    lines.append(combo)
                # drop "??" header and other single-hangul combos
                skip_next = True
                continue
        
        if not s:
            lines.append("")
            continue
        if SARYEJIP_RE.search(s):
            continue
        if ROMAN_NUM_RE.match(s):
            continue
        if re.search(r"\uC81C\s*\d+\s*\uD3B8", s):
            if re.search(r"\d{1,3}$", s) or re.search(r"\uD604\uD669|\uC8FC\uC694", s):
                continue
        # Remove short header line ending with a page number (e.g., "... 53")
        if re.search(r"[\uAC00-\uD7A3]{3,}\s*\d{1,3}$", s):
            continue
        if is_single_hangul(s):
            continue

        next_s = raw_lines[i + 1].strip() if i + 1 < len(raw_lines) else ""
        # Remove trailing single-hangul token like "... ?" or "... ?"
        s = re.sub(r"\s+[\uAC00-\uD7A3]\s*$", "", s)
        if re.match(r"^\s*\uC8FC\s*\uBB38\s*$", s):
            continue
        if is_single_hangul(s):
            continue
        # Remove trailing page number when next line is a vertical header token
        if re.search(r"\s\d{1,3}\s*$", s) and is_single_hangul(next_s):
            s = re.sub(r"\s\d{1,3}\s*$", "", s)
        # Drop page-number line only when part of a vertical header (e.g., ?/4/?)
        if re.fullmatch(r"\d{1,3}", s):
            prev_s = raw_lines[i - 1].strip() if i > 0 else ""
            if is_single_hangul(prev_s) or is_single_hangul(next_s):
                continue
        if s:
            lines.append(s)

    return norm_text("\n".join(lines)) or None

def clean_overview_text(t: Optional[str]) -> Optional[str]:
    t = clean_section_text(t)
    if not t:
        return None
    lines = t.splitlines()
    while lines and is_single_hangul(lines[0].strip()):
        lines = lines[1:]
    if lines and re.search(r"\uC0AC\uAC74\s*\uAC1C\uC694", lines[0].strip()):
        lines = lines[1:]
    return "\n".join(lines).strip() or None

def extract_printed_page(text: str) -> Optional[str]:
    """
    이 문서는 footer가 보통 이런 식으로 줄바꿈되어 나옴:
      2015년
      52
      전자거래분쟁조정사례집
    또는 중간에 공백/문구가 섞일 수 있음.
    => 마지막 10~15줄을 훑어서 '숫자만 있는 줄'을 찾고,
       주변에 '전자거래분쟁조정사례집'이 있으면 그 숫자를 printed page로 사용.
    """
    if not text:
        return None
    # direct pattern (line breaks allowed)
    flat = text.replace("\n", " ")
    m = re.search(r"2015년\s*(\d{1,3})\s*전자거래분쟁조정\s*사례집", flat)
    if m:
        return m.group(1)
    m = re.search(r"제\s*3\s*편\s*합의권고및조정\s*(\d{1,3})", flat)
    if m:
        return m.group(1)

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    tail = lines[-15:] if len(lines) > 15 else lines

    # '전자거래분쟁조정사례집' 라인이 tail에 있는지 먼저 확인
    has_book = any("전자거래분쟁조정사례집" in ln.replace(" ", "") for ln in tail)
    if not has_book:
        return None

    # 숫자 단독 라인을 찾음
    for ln in reversed(tail):
        if re.fullmatch(r"\d{1,3}", ln):
            return ln
    return None

def first_group(regex: re.Pattern, text: str) -> Optional[str]:
    m = regex.search(text or "")
    return m.group(1).strip() if m else None

def slice_sections(full_text: str) -> Dict[str, str]:
    """
    케이스 전체 텍스트에서 1/2/3/4 섹션을 잘라 반환.
    3번 섹션은 '사무국 판단'(권고) / '조정국 판단'(조정) 중 하나.
    """
    full_text = full_text or ""
    markers: List[tuple[str, int]] = []

    for name, rgx in [
        ("sec1", RE_SEC1),
        ("sec2", RE_SEC2),
        ("sec3_reco", RE_SEC3_RECO),
        ("sec3_adj", RE_SEC3_ADJ),
        ("sec4", RE_SEC4),
    ]:
        m = rgx.search(full_text)
        if m:
            markers.append((name, m.start()))

    markers.sort(key=lambda x: x[1])
    out: Dict[str, str] = {}

    for i, (name, pos) in enumerate(markers):
        end = markers[i + 1][1] if i + 1 < len(markers) else len(full_text)
        out[name] = norm_text(full_text[pos:end])

    # sec3 unify
    if "sec3_reco" in out:
        out["sec3"] = out["sec3_reco"]
        out["sec3_type"] = RECO_LABEL
    elif "sec3_adj" in out:
        out["sec3"] = out["sec3_adj"]
        out["sec3_type"] = ADJ_LABEL
    else:
        out["sec3"] = ""
        out["sec3_type"] = None  # type: ignore

    return out

def split_claims(sec2_text: str) -> Dict[str, List[str]]:
    sec2_text = sec2_text or ""
    a = RE_CLAIM_A.search(sec2_text)
    b = RE_CLAIM_B.search(sec2_text)

    applicant = ""
    respondent = ""

    if a and b:
        if a.start() < b.start():
            applicant = sec2_text[a.start():b.start()]
            respondent = sec2_text[b.start():]
        else:
            respondent = sec2_text[b.start():a.start()]
            applicant = sec2_text[a.start():]
    elif a and not b:
        applicant = sec2_text[a.start():]
    elif b and not a:
        respondent = sec2_text[b.start():]

    def to_paras(block: str) -> List[str]:
        block = norm_text(block)
        if not block:
            return []
        return [p.strip() for p in block.split("\n\n") if p.strip()]

    return {
        "applicant": [p for p in (clean_section_text(x) for x in to_paras(applicant)) if p],
        "respondent": [p for p in (clean_section_text(x) for x in to_paras(respondent)) if p],
    }

def split_order_reason(sec3_text: str) -> Dict[str, Optional[str]]:
    """주문과 이유를 분리. 조정 케이스의 경우 '가.', '나.', '다.' 등으로 시작하는 주문 부분 분리"""
    sec3_text = sec3_text or ""
    if not sec3_text.strip():
        return {"order": None, "reason": None}

    lines = sec3_text.splitlines()
    order_start = None
    reason_start = None

    # 먼저 명시적 마커 찾기
    for i, line in enumerate(lines):
        s = line.strip()
        if order_start is None and RE_ORDER_MARK.match(s):
            order_start = i
            continue
        if reason_start is None and RE_REASON_MARK.match(s):
            reason_start = i
            continue

    # 마커가 없으면 조정 케이스의 일반적인 구조 찾기: "가. ", "나. " 등
    if order_start is None:
        for i, line in enumerate(lines):
            s = line.strip()
            # "가. ..." 형태의 주문 시작
            if re.match(r"^가\.\s*", s):
                order_start = i
                break

    # 이유 시작 찾기 (order 이후의 "이유" 또는 "나. " 등)
    if order_start is not None and reason_start is None:
        for i in range(order_start + 1, len(lines)):
            s = lines[i].strip()
            if RE_REASON_MARK.match(s):
                reason_start = i
                break
            # "다.", "라." 등은 이유 끝을 의미할 수 있음
            if re.match(r"^[다라마]\.\s*", s):
                reason_start = i
                break

    def join_block(start: int, end: int) -> str:
        block = "\n".join(lines[start:end]).strip()
        return norm_text(block) if block else ""

    order = None
    reason = None

    if order_start is not None and reason_start is not None:
        if order_start < reason_start:
            order_block = join_block(order_start, reason_start)
            reason_block = join_block(reason_start, len(lines))
            order = order_block if order_block else None
            reason = reason_block if reason_block else None
        else:
            reason_block = join_block(reason_start, len(lines))
            reason = reason_block if reason_block else None
    elif order_start is not None and reason_start is None:
        order_block = join_block(order_start, len(lines))
        order = order_block if order_block else None
    elif order_start is None and reason_start is not None:
        reason_block = join_block(reason_start, len(lines))
        reason = reason_block if reason_block else None
    else:
        # 마커가 완전히 없으면 전체를 reason으로 처리
        reason = norm_text(sec3_text)

    return {"order": order, "reason": reason}

def infer_case_type(method: Optional[str], sec3_type_hint: Optional[str]) -> Optional[str]:
    if sec3_type_hint in (RECO_LABEL, ADJ_LABEL):
        return sec3_type_hint
    if not method:
        return None
    return RECO_LABEL if RECO_LABEL in method else ADJ_LABEL

def strip_section_header(text: Optional[str], regexes: List[re.Pattern]) -> Optional[str]:
    if not text:
        return text
    lines = text.splitlines()
    if not lines:
        return text
    idx = 0
    while idx < len(lines) and is_single_hangul(lines[idx].strip()):
        idx += 1
    if idx < len(lines):
        first = lines[idx].strip()
        if any(r.match(first) for r in regexes):
            return "\n".join(lines[idx + 1:]).lstrip()
    return "\n".join(lines[idx:]) if idx else text

@dataclass
class CaseBuffer:
    case_no: str
    method: Optional[str]
    title: str
    printed_page_number: Optional[str]
    page_start: int  # 1-based
    texts: List[str]
    last_page_index: int  # 1-based


def is_case_complete(case: Dict) -> bool:
    """케이스 완성도 확인: order가 있어야 완성으로 판단 (이유만으로는 불충분)"""
    return bool(
        case.get("overview")
        and case.get("judgement", {}).get("order")  # order가 필수
        and case.get("result")
    )


def merge_vision_result(text_case: Dict, vision_case: Optional[Dict]) -> Dict:
    """텍스트 파싱과 Vision API 결과를 병합"""
    if not vision_case:
        return text_case

    # 텍스트 파싱이 완성되지 않았으면 Vision 결과로 대체
    if not is_case_complete(text_case):
        # 텍스트에서 추출된 기본 정보 유지
        vision_case["case_number"] = text_case.get("case_number") or vision_case.get("case_number")
        vision_case["method"] = text_case.get("method") or vision_case.get("method")
        vision_case["title"] = text_case.get("title") or vision_case.get("title")
        vision_case["case_type"] = text_case.get("case_type") or vision_case.get("case_type")
        vision_case["printed_page_number"] = text_case.get("printed_page_number")
        vision_case["number"] = text_case.get("number")
        vision_case["page_start"] = text_case.get("page_start")
        vision_case["page_end"] = text_case.get("page_end")
        return vision_case

    return text_case


def parse_pdf(pdf_path: Path, use_vision_fallback: bool = True) -> Dict:
    """하이브리드 파싱: 텍스트 기반 + Vision API fallback"""
    cases: List[Dict] = []
    buf: Optional[CaseBuffer] = None
    vision_parsed_count = 0

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_i0, page in enumerate(pdf.pages):
            page_i1 = page_i0 + 1
            text = norm_text(page.extract_text() or "")
            if not text:
                continue

            printed_page = extract_printed_page(text)

            # 이 페이지에서 "사건번호/사건명칭"이 나오면 새 케이스 시작으로 판단
            case_no = first_group(RE_CASE_NO, text)
            title   = first_group(RE_TITLE, text)

            is_new_case = bool(case_no and title)

            if is_new_case:
                method = first_group(RE_METHOD, text)

                # 기존 케이스 finalize
                if buf is not None:
                    full_text = "\n\n".join(buf.texts)
                    sections = slice_sections(full_text)
                    sec1 = strip_section_header(sections.get("sec1"), [RE_SEC1])
                    sec2 = strip_section_header(sections.get("sec2"), [RE_SEC2])
                    sec3 = strip_section_header(sections.get("sec3"), [RE_SEC3_RECO, RE_SEC3_ADJ])
                    sec4 = sections.get("sec4")
                    claims = split_claims(sec2 or "")
                    order_reason = split_order_reason(sec3 or "")
                    case_type = infer_case_type(buf.method, sections.get("sec3_type"))

                    text_case = {
                        "case_number": buf.case_no,
                        "method": buf.method,
                        "title": buf.title,
                        "case_type": case_type,
                        "printed_page_number": buf.printed_page_number,
                        "overview": clean_overview_text(sec1),
                        "claims": claims,
                        "judgement": {
                            "order": clean_section_text(order_reason.get("order")),
                            "reason": clean_section_text(order_reason.get("reason")),
                        },
                        "result": clean_section_text(sec4),
                        "parsing_method": "pdfplumber",
                        "number": len(cases) + 1,
                        "page_start": buf.page_start,
                        "page_end": buf.last_page_index,
                    }

                    # Vision API fallback
                    vision_case = None
                    if use_vision_fallback and not is_case_complete(text_case):
                        print(f"    [Vision 재시도] 페이지 {buf.page_start}-{buf.last_page_index}")
                        time.sleep(3)  # Vision API 호출 전 대기
                        images_b64 = pdf_pages_to_base64_images(
                            str(pdf_path),
                            buf.page_start - 1,
                            buf.last_page_index,
                            dpi=150
                        )
                        if images_b64:
                            vision_case = parse_case_with_vision_api(images_b64, case_type or "조정")
                            if vision_case:
                                vision_parsed_count += 1
                                time.sleep(5)  # rate limit 대비

                    final_case = merge_vision_result(text_case, vision_case)
                    cases.append(final_case)

                # 새 케이스 시작
                buf = CaseBuffer(
                    case_no=case_no.strip(),
                    method=method.strip() if method else None,
                    title=title.strip(),
                    printed_page_number=printed_page,
                    page_start=page_i1,
                    texts=[text],
                    last_page_index=page_i1,
                )
            else:
                # 케이스 진행중이면 누적
                if buf is not None:
                    buf.texts.append(text)
                    buf.last_page_index = page_i1

        # 마지막 케이스 finalize
        if buf is not None:
            full_text = "\n\n".join(buf.texts)
            sections = slice_sections(full_text)
            sec1 = strip_section_header(sections.get("sec1"), [RE_SEC1])
            sec2 = strip_section_header(sections.get("sec2"), [RE_SEC2])
            sec3 = strip_section_header(sections.get("sec3"), [RE_SEC3_RECO, RE_SEC3_ADJ])
            sec4 = sections.get("sec4")
            claims = split_claims(sec2 or "")
            order_reason = split_order_reason(sec3 or "")
            case_type = infer_case_type(buf.method, sections.get("sec3_type"))

            text_case = {
                "case_number": buf.case_no,
                "method": buf.method,
                "title": buf.title,
                "case_type": case_type,
                "printed_page_number": buf.printed_page_number,
                "overview": clean_overview_text(sec1),
                "claims": claims,
                "judgement": {
                    "order": clean_section_text(order_reason.get("order")),
                    "reason": clean_section_text(order_reason.get("reason")),
                },
                "result": clean_section_text(sec4),
                "parsing_method": "pdfplumber",
                "number": len(cases) + 1,
                "page_start": buf.page_start,
                "page_end": buf.last_page_index,
            }

            # Vision API fallback
            vision_case = None
            if use_vision_fallback and not is_case_complete(text_case):
                print(f"    [Vision 재시도] 페이지 {buf.page_start}-{buf.last_page_index}")
                time.sleep(3)  # Vision API 호출 전 대기
                images_b64 = pdf_pages_to_base64_images(
                    str(pdf_path),
                    buf.page_start - 1,
                    buf.last_page_index,
                    dpi=150
                )
                if images_b64:
                    vision_case = parse_case_with_vision_api(images_b64, case_type or "조정")
                    if vision_case:
                        vision_parsed_count += 1
                        time.sleep(5)  # rate limit 대비

            final_case = merge_vision_result(text_case, vision_case)
            cases.append(final_case)

    complete = sum(1 for c in cases if is_case_complete(c))
    reco = sum(1 for c in cases if c.get("case_type") == RECO_LABEL)
    adj  = sum(1 for c in cases if c.get("case_type") == ADJ_LABEL)

    return {
        "year": "2015",
        "total_cases": len(cases),
        "parsing_statistics": {
            "text_parsed": len(cases) - vision_parsed_count,
            "vision_parsed": vision_parsed_count,
            "gemini_parsed": 0,
            "complete_cases": complete,
            "recommendation_cases": reco,
            "adjustment_cases": adj,
        },
        "cases": cases,
    }


def main():
    if not PDF_PATH.exists():
        raise FileNotFoundError(f"PDF not found: {PDF_PATH}")

    print("=" * 80)
    print("2015년 전자거래 분쟁조정 사례집 - 하이브리드 파싱")
    print("=" * 80)
    print(f"Strategy: pdfplumber (텍스트) + OpenAI Vision API (이미지 fallback)")
    print()

    data = parse_pdf(PDF_PATH, use_vision_fallback=True)

    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 80)
    print("파싱 결과")
    print("=" * 80)
    print(f"저장 경로: {JSON_PATH}")
    print(f"총 사례: {data['total_cases']}개")
    print()
    print("파싱 방식:")
    print(f"  - 텍스트 기반: {data['parsing_statistics']['text_parsed']}개")
    print(f"  - Vision API: {data['parsing_statistics']['vision_parsed']}개")
    print()
    print("사례 유형:")
    print(f"  - 권고: {data['parsing_statistics']['recommendation_cases']}개")
    print(f"  - 조정: {data['parsing_statistics']['adjustment_cases']}개")
    print()
    print(f"완성도: {data['parsing_statistics']['complete_cases']}/{data['total_cases']} "
          f"({100*data['parsing_statistics']['complete_cases']/data['total_cases']:.1f}%)")
    print("=" * 80)


if __name__ == "__main__":
    main()

