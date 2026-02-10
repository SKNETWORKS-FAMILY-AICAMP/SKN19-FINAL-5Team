"""
01_03_parsing_adjustment_1_2018_1.py
---------------------------------
KCA 물품 분쟁조정 사례집(2018) PDF를 구조 파싱해서 JSON으로 저장합니다.

✅ 목표
1) 텍스트 PDF: pdfplumber로 텍스트 추출 → 사건번호 기준 케이스 묶기 → 섹션 분리
2) 스캔/이미지 PDF: (페이지 렌더링 → OpenAI Vision 페이지별 텍스트 추출) → 동일 파서 재사용
3) 페이지번호: 문서 하단의 페이지 번호 추출 (예: "제3장 ... 17", "18 2018 물품")
4) OCR 캐시: PDF 1개당 캐시 파일 1개로 저장 (파일 폭증 방지)

✅ 섹션 구조 (KCA 2018 물품)
- "주 문" → order 필드
- "이 유" > "1. 기초 사실" → overview 필드
- "이 유" > "2. 판 단" → reason 필드
- "이 유" > "[관련 법령]" 이후 → result 필드
- claims: null (이 문서에는 당사자 주장이 따로 없음)
- case_type: "조정" (고정)

✅ 필요 패키지
pip install pdfplumber pymupdf python-dotenv openai pillow

✅ .env 예시
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

✅ 출력
- PDF와 같은 폴더에 같은 파일명으로 .json 생성
- OCR 캐시: _cache_openai_ocr/{PDF스템}.ocr_cache.json
"""

import os
import re
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from io import BytesIO

import pdfplumber
import fitz  # PyMuPDF
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image


# ---------------------------
# Paths (relative)
# ---------------------------
BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "01_B_parsed" / "02_02_AdjustmentCase" / "01_kca"
CACHE_DIR = PDF_DIR / "_cache_openai_ocr"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------
# Env / OpenAI config
# ---------------------------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY가 .env에 없습니다. .env에 OPENAI_API_KEY=... 를 설정하세요.")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
client = OpenAI(api_key=OPENAI_API_KEY)


# ---------------------------
# Speed knobs (tune here)
# ---------------------------
OCR_ZOOM = float(os.getenv("OCR_ZOOM", "2.0"))              # 1.8~2.2 권장
OCR_BATCH_SIZE = int(os.getenv("OCR_BATCH_SIZE", "2"))      # 2 or 3 권장
OCR_PRE_SCAN_PAGES = int(os.getenv("OCR_PRE_SCAN_PAGES", "60"))  # 60~100 권장
OCR_PER_BATCH_SLEEP = float(os.getenv("OCR_PER_BATCH_SLEEP", "0.2"))  # 레이트리밋 대비


# ---------------------------
# Regex rules (KCA specific)
# ---------------------------
# 사건번호 패턴: 2015일나1984, 2016나50, etc.
# 형식: [사건번호 2015일나1984] 또는 사건번호 2015일나1984
RE_CASE_NO = re.compile(r"사건\s*번호\s+(\d{4}[가-힣]+\d{1,4})")
RE_TITLE = re.compile(r"^\s*사례\s*\d+\s*\n(.+?)(?:\n\[사건|$)", re.MULTILINE)
RE_DECISION_DATE = re.compile(r"\[결정일자\s*(\d{4}\.\s*\d{1,2}\.\s*\d{1,2})\]")

# 섹션 마커
# 일반 조정: 주문 - 이유(기초사실, 판단)
# 집단 조정: 주문 - 이유(사건개요, 당사자주장, 판단, 결론)
SECTION_RULES = {
    "주문": re.compile(r"(?m)^\s*주\s+문\s*$"),
    "이유": re.compile(r"(?m)^\s*이\s+유\s*$"),
    "기초사실": re.compile(r"(?m)^\s*1\.\s*(?:기초\s*사실|사건\s*개요)\s*$"),
    "당사자주장": re.compile(r"(?m)^\s*2\.\s*(?:양\s*)?당사자\s*주장\s*$"),
    "판단": re.compile(r"(?m)^\s*(?:2|3)\.\s*판\s*단\s*$"),
    "법령": re.compile(r"(?m)^\s*\[?관련\s*법령\]?\s*$"),
}

# 신청인/피신청인 주장 분리
RE_APPLICANT = re.compile(r"(?m)^\s*가\.\s*신청인")
RE_RESPONDENT = re.compile(r"(?m)^\s*나\.\s*피신청인")

# 페이지 번호 감지: "18 2018 물품" 또는 "제3장 ... 17" 형태
RE_PRINTED_PAGE = re.compile(
    r"(?m)^.*?(\d{2,3})\s*(?:2018|2017|물품|서비스|의료|분쟁|조정).*?$|^(\d{2,3})\s*\|\s*2018"
)


# ---------------------------
# Data models
# ---------------------------
@dataclass
class PageText:
    page_idx: int
    text: str
    printed_page: Optional[int]


# ---------------------------
# JSON helpers
# ---------------------------
def read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_int(x: str) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


def summarize_text(text: str, max_length: int = 500) -> Optional[str]:
    """텍스트 요약: 핵심 내용만 max_length 이내로 반환"""
    if not text:
        return None

    text = text.strip()
    if len(text) <= max_length:
        return text

    # 문장 단위로 자르기
    lines = text.split('\n')
    result = []
    total_len = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if total_len + len(line) <= max_length:
            result.append(line)
            total_len += len(line) + 1
        else:
            # 마지막 문장이 끝나는 지점에서 자르기
            if result:
                break
            else:
                # 첫 문장이 max_length보다 길면 강제로 자르기
                result.append(line[:max_length])
                break

    summary = '\n'.join(result).strip()
    return summary if summary else None


# ---------------------------
# Printed page detection
# ---------------------------
def detect_printed_page(text: str) -> Optional[int]:
    """문서 하단의 페이지 번호 추출"""
    tail = text[-500:] if text else ""

    # 패턴 1: "제3장 일반분쟁조정 사례-물품 17"
    m1 = re.search(r"(\d{2,3})\s*$", tail.split('\n')[-1] if '\n' in tail else tail)
    if m1:
        try:
            return int(m1.group(1))
        except:
            pass

    # 패턴 2: "18 2018 물품"
    m2 = re.search(r"^(\d{2,3})\s+2018", tail.split('\n')[-1] if '\n' in tail else tail)
    if m2:
        try:
            return int(m2.group(1))
        except:
            pass

    # 패턴 3: 일반적인 숫자 패턴
    matches = list(RE_PRINTED_PAGE.finditer(tail))
    if matches:
        m = matches[-1]
        try:
            page_num = m.group(1) or m.group(2)
            return int(page_num) if page_num else None
        except:
            return None

    return None


# ---------------------------
# Text-PDF extraction (pdfplumber)
# ---------------------------
def extract_pages_text_textpdf(pdf_path: Path, max_pages: Optional[int] = None) -> List[PageText]:
    pages: List[PageText] = []
    with pdfplumber.open(pdf_path) as pdf:
        n = len(pdf.pages) if max_pages is None else min(len(pdf.pages), max_pages)
        for i in range(n):
            page = pdf.pages[i]
            txt = page.extract_text() or ""
            printed = detect_printed_page(txt)
            pages.append(PageText(page_idx=i, text=txt, printed_page=printed))
    return pages


def should_use_ocr(pages: List[PageText]) -> bool:
    """OCR 필요 여부 판단"""
    sample = " ".join(p.text for p in pages[:5]).strip()
    if len(sample) < 50:
        return True

    hangul_cnt = len(re.findall(r"[가-힣]", sample))
    hangul_ratio = hangul_cnt / max(len(sample), 1)

    if hangul_ratio < 0.005:
        return True

    return False


# ---------------------------
# OpenAI Vision OCR
# ---------------------------
def render_page_to_png_bytes(pdf_path: Path, page_idx: int, zoom: float) -> bytes:
    """PDF 페이지를 PNG로 렌더링"""
    doc = fitz.open(pdf_path)
    page = doc.load_page(page_idx)
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    doc.close()
    return pix.tobytes("png")


def openai_extract_text_multi_with_retry(
    images_b64: List[str],
    page_indices: List[int],
    model: str,
    max_retries: int = 4,
    base_sleep: float = 2.0,
) -> str:
    """OpenAI Vision으로 여러 페이지 한 번에 OCR"""
    last_err = None
    for attempt in range(max_retries):
        try:
            prompt = (
                "너는 OCR 엔진이다. 아래에 여러 개의 '문서 페이지 이미지'가 주어진다.\n"
                "각 이미지의 텍스트를 최대한 정확하게 추출하되, 출력은 반드시 다음 형식만 사용해라:\n"
                "[PAGE <페이지번호>]\n"
                "<해당 페이지의 추출 텍스트>\n\n"
                "규칙:\n"
                "1) 페이지번호는 내가 제공한 page index를 그대로 사용해라.\n"
                "2) '사건번호', '결정일자', '주문', '이유', '기초 사실', '판단' 같은 섹션 제목을 절대 누락하지 마라.\n"
                "3) 마침표, 쉼표, 괄호 등 문장 기호를 정확히 유지해라.\n"
                "4) 추가 설명/해설 금지. 오직 위 포맷으로만 출력.\n"
                "5) 각 페이지는 반드시 1번씩만 출력해라.\n"
            )

            # 메시지 구성
            content = [{"type": "text", "text": prompt}]

            # 페이지 매핑 정보
            mapping_text = "페이지 매핑:\n" + "\n".join([f"- 이미지 {i+1} => PAGE {pidx}" for i, pidx in enumerate(page_indices)])
            content.append({"type": "text", "text": mapping_text})

            # 이미지 추가
            for img_b64 in images_b64:
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_b64}",
                        "detail": "high"
                    }
                })

            response = client.chat.completions.create(
                model=model,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": content
                    }
                ]
            )
            return response.choices[0].message.content

        except Exception as e:
            last_err = e
            wait_time = base_sleep * (2 ** attempt)
            print(f"  WARNING Retry {attempt + 1}/{max_retries}, waiting {wait_time}s: {str(e)[:100]}")
            time.sleep(wait_time)

    raise RuntimeError(f"OpenAI OCR 실패: {last_err}")


def split_multi_page_output(text: str) -> Dict[int, str]:
    """OpenAI 출력을 페이지별로 분리"""
    if not text:
        return {}

    pattern = re.compile(r"\[PAGE\s+(\d+)\]\s*\n")
    matches = list(pattern.finditer(text))
    if not matches:
        return {}

    out: Dict[int, str] = {}
    for i, m in enumerate(matches):
        p = int(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[p] = text[start:end].strip()

    return out


def load_or_init_cache(pdf_path: Path, zoom: float) -> Tuple[Path, dict, dict]:
    """캐시 로드 또는 초기화"""
    cache_path = CACHE_DIR / f"{pdf_path.stem}.ocr_cache.json"
    cache_obj = read_json(cache_path)
    if not isinstance(cache_obj, dict):
        cache_obj = {"pdf": pdf_path.name, "model": OPENAI_MODEL, "zoom": zoom, "pages": {}}

    pages_cache = cache_obj.get("pages", {})
    if not isinstance(pages_cache, dict):
        pages_cache = {}
        cache_obj["pages"] = pages_cache

    cache_obj["model"] = OPENAI_MODEL
    cache_obj["zoom"] = zoom

    return cache_path, cache_obj, pages_cache


def estimate_start_page_by_prescan(
    pdf_path: Path,
    total_pages: int,
    zoom: float,
    batch_size: int,
    pre_scan_pages: int,
) -> int:
    """앞부분만 스캔하여 사건번호 첫 등장 페이지 찾기"""
    scan_until = min(total_pages, max(pre_scan_pages, batch_size))
    prescan_indices = list(range(scan_until))

    for i in range(0, len(prescan_indices), batch_size):
        batch = prescan_indices[i:i + batch_size]
        images_b64 = []

        for p in batch:
            img_bytes = render_page_to_png_bytes(pdf_path, p, zoom)
            import base64
            images_b64.append(base64.b64encode(img_bytes).decode('utf-8'))

        raw = openai_extract_text_multi_with_retry(images_b64, batch, model=OPENAI_MODEL)
        page_map = split_multi_page_output(raw)

        for p in batch:
            txt = page_map.get(p, "")
            if RE_CASE_NO.search(txt):
                print(f"  [INFO] 사건번호 첫 등장: 페이지 {p}")
                return p

    return 0


def extract_pages_text_openai_ocr_optimized(
    pdf_path: Path,
    zoom: float = OCR_ZOOM,
    batch_size: int = OCR_BATCH_SIZE,
    pre_scan_pages: int = OCR_PRE_SCAN_PAGES,
    per_batch_sleep: float = OCR_PER_BATCH_SLEEP,
) -> List[PageText]:
    """OpenAI Vision을 이용한 최적화된 OCR"""
    import base64

    doc = fitz.open(pdf_path)
    total = doc.page_count
    doc.close()

    cache_path, cache_obj, pages_cache = load_or_init_cache(pdf_path, zoom=zoom)

    # start_page 추정
    cached_case_pages = [int(k) for k, v in pages_cache.items() if isinstance(v, str) and RE_CASE_NO.search(v)]
    if cached_case_pages:
        start_page = min(cached_case_pages)
    else:
        start_page = estimate_start_page_by_prescan(
            pdf_path=pdf_path,
            total_pages=total,
            zoom=zoom,
            batch_size=batch_size,
            pre_scan_pages=pre_scan_pages,
        )

    pages: List[PageText] = []
    indices = list(range(start_page, total))

    for i in range(0, len(indices), batch_size):
        batch = indices[i:i + batch_size]

        # 캐시에 없는 페이지만 OCR
        need = [p for p in batch if (str(p) not in pages_cache) or (not isinstance(pages_cache[str(p)], str)) or (not pages_cache[str(p)].strip())]

        if need:
            print(f"  [OCR] batch: pages {need}")
            images_b64 = []
            for p in need:
                img_bytes = render_page_to_png_bytes(pdf_path, p, zoom)
                images_b64.append(base64.b64encode(img_bytes).decode('utf-8'))

            raw = openai_extract_text_multi_with_retry(images_b64, need, model=OPENAI_MODEL)
            page_map = split_multi_page_output(raw)

            for p in need:
                txt = page_map.get(p, "").strip()
                pages_cache[str(p)] = txt

            write_json(cache_path, cache_obj)

            if per_batch_sleep > 0:
                time.sleep(per_batch_sleep)

        # batch 페이지들 PageText 구성
        for p in batch:
            txt = pages_cache.get(str(p), "") if isinstance(pages_cache.get(str(p), ""), str) else ""
            printed = detect_printed_page(txt)
            pages.append(PageText(page_idx=p, text=txt, printed_page=printed))

    return pages


# ---------------------------
# Case grouping + section splitting
# ---------------------------
def group_cases_by_case_no(pages: List[PageText]) -> List[List[PageText]]:
    """사건번호 기준으로 페이지 그룹핑"""
    case_starts: List[int] = []
    for idx, p in enumerate(pages):
        if RE_CASE_NO.search(p.text):
            case_starts.append(idx)

    if not case_starts:
        return []

    groups: List[List[PageText]] = []
    for s_i, start in enumerate(case_starts):
        end = case_starts[s_i + 1] if s_i + 1 < len(case_starts) else len(pages)
        groups.append(pages[start:end])
    return groups


def split_sections(case_text: str) -> Dict[str, str]:
    """케이스 텍스트를 섹션으로 분리"""
    hits: List[Tuple[int, str, str]] = []
    for name, pat in SECTION_RULES.items():
        m = pat.search(case_text)
        if m:
            hits.append((m.start(), name, m.group(0)))

    if not hits:
        return {}

    hits.sort(key=lambda x: x[0])
    sections: Dict[str, str] = {}

    for i, (pos, name, header) in enumerate(hits):
        start = pos + len(header)
        end = hits[i + 1][0] if i + 1 < len(hits) else len(case_text)
        sections[name] = case_text[start:end].strip()

    return sections


def extract_case_number_from_bracket(text: str) -> Optional[str]:
    """[사건번호 xxx] 형식에서 사건번호 추출"""
    m = RE_CASE_NO.search(text)
    if m:
        return m.group(1).strip()
    return None


def extract_title(text: str) -> Optional[str]:
    """사례 제목 추출"""
    # 2018년 구조: "사례 01\n제목\n주 문" 또는 "사 01\n례 사건번호 ...\n제목\n주 문"

    # 방법 1: 2016년 형식 "사례 01\n제목\n[사건번호"
    m = re.search(r"사례\s+\d+\s*\n(.+?)\n\[사건번호", text, re.DOTALL)
    if m:
        title = m.group(1).strip()
        # 여러 줄이면 한 줄로 정리
        title = " ".join(title.split())
        return title

    # 방법 2: 2018년 형식 "사건번호" 다음부터 "주 문" 전까지
    m = re.search(r"사건번호.*?\n(.+?)\n주\s+문", text, re.DOTALL)
    if m:
        title = m.group(1).strip()
        # 여러 줄이면 한 줄로 정리
        title = " ".join(title.split())
        return title

    return None


def extract_overview(sections: Dict[str, str]) -> Optional[str]:
    """기초 사실/사건 개요 섹션에서 overview 추출 (요약)"""
    basic_facts = sections.get("기초사실", "")
    if basic_facts:
        summary = summarize_text(basic_facts, max_length=400)
        return summary
    return None


def extract_claims(sections: Dict[str, str]) -> Optional[Dict]:
    """당사자 주장 섹션에서 신청인/피신청인 주장 추출 (요약)"""
    claims_text = sections.get("당사자주장", "")
    if not claims_text:
        return None

    # 신청인 주장 추출
    m_applicant = RE_APPLICANT.search(claims_text)
    m_respondent = RE_RESPONDENT.search(claims_text)

    result = {}

    if m_applicant:
        start = m_applicant.start()
        end = m_respondent.start() if m_respondent else len(claims_text)
        applicant_text = claims_text[start:end].strip()
        applicant_summary = summarize_text(applicant_text, max_length=400)
        if applicant_summary:
            result["applicant"] = [applicant_summary]

    if m_respondent:
        start = m_respondent.start()
        respondent_text = claims_text[start:].strip()
        respondent_summary = summarize_text(respondent_text, max_length=400)
        if respondent_summary:
            result["respondent"] = [respondent_summary]

    return result if result else None


def extract_reason(sections: Dict[str, str]) -> Optional[str]:
    """판단 섹션에서 reason 추출 (요약)"""
    judgment = sections.get("판단", "")
    if judgment:
        summary = summarize_text(judgment, max_length=600)
        return summary
    return None


def extract_order(sections: Dict[str, str]) -> Optional[str]:
    """주문 섹션 전체 추출"""
    order_text = sections.get("주문", "")
    if order_text:
        return order_text.strip()
    return None


def extract_result(sections: Dict[str, str], full_text: str) -> Optional[str]:
    """결과 섹션 추출: "이상과 같은 이유로 주문과 같이 결정한다" 같은 결론"""
    reason_text = sections.get("판단", "")
    if not reason_text:
        return None

    # 판단 끝 부분 (보통 "이상과 같은 이유로" 이후)
    m = re.search(r"이상과\s*같은\s*이유로.*?결정한다\.?", reason_text, re.DOTALL)
    if m:
        return m.group(0).strip()

    return None


def parse_case(case_pages: List[PageText], year: Optional[int], source_pdf: str) -> Optional[Dict]:
    """단일 케이스 파싱"""
    full_text = "\n".join(p.text for p in case_pages)

    # 사건번호
    case_no = extract_case_number_from_bracket(full_text)
    if not case_no:
        return None

    # 제목
    title = extract_title(full_text)

    # 섹션 분리
    sections = split_sections(full_text)

    # 페이지 정보
    printed_pages = [p.printed_page for p in case_pages if p.printed_page is not None]
    phys_pages = [p.page_idx for p in case_pages]
    printed_page_number = str(printed_pages[0]) if printed_pages else None

    # 섹션별 텍스트 추출
    overview = extract_overview(sections)
    claims = extract_claims(sections)
    reason = extract_reason(sections)
    order = extract_order(sections)
    result = extract_result(sections, full_text)

    return {
        "case_number": case_no,
        "method": None,
        "title": title,
        "case_type": "조정",
        "printed_page_number": printed_page_number,
        "overview": overview,
        "result": result,
        "claims": claims,
        "judgement": {
            "reason": reason,
            "order": order
        } if reason and order else None,
        "page": {
            "physical_pages": phys_pages,
            "printed_pages": printed_pages,
        },
        "raw_text": full_text,
    }


# ---------------------------
# PDF parsing orchestrator
# ---------------------------
def parse_pdf(pdf_path: Path) -> Dict:
    """PDF 전체 파싱"""
    m = re.search(r"(\d{4})년", pdf_path.name)
    year = safe_int(m.group(1)) if m else None

    print(f"\n[1] 텍스트 추출 (pdfplumber)...")
    pages_textpdf = extract_pages_text_textpdf(pdf_path, max_pages=None)
    print(f"  [OK] {len(pages_textpdf)} pages extracted")

    # OCR 필요 여부 판단
    if should_use_ocr(pages_textpdf):
        print(f"[2] OCR 필요 (텍스트 추출 부족) - OpenAI Vision 사용...")
        pages = extract_pages_text_openai_ocr_optimized(
            pdf_path,
            zoom=OCR_ZOOM,
            batch_size=OCR_BATCH_SIZE,
            pre_scan_pages=OCR_PRE_SCAN_PAGES,
            per_batch_sleep=OCR_PER_BATCH_SLEEP,
        )
        extraction_mode = "openai_ocr"
    else:
        print(f"[2] 텍스트 PDF 사용")
        pages = pages_textpdf
        extraction_mode = "textpdf"

    print(f"[3] 케이스 그룹핑 (사건번호 기준)...")
    groups = group_cases_by_case_no(pages)
    print(f"  [OK] {len(groups)} cases found")

    # textpdf인데 케이스 0개면 OCR로 재시도
    if extraction_mode == "textpdf" and len(groups) == 0:
        print(f"[3-2] 케이스 0개 - OCR 재시도...")
        pages = extract_pages_text_openai_ocr_optimized(
            pdf_path,
            zoom=OCR_ZOOM,
            batch_size=OCR_BATCH_SIZE,
            pre_scan_pages=OCR_PRE_SCAN_PAGES,
            per_batch_sleep=OCR_PER_BATCH_SLEEP,
        )
        extraction_mode = "openai_ocr"
        groups = group_cases_by_case_no(pages)
        print(f"  [OK] {len(groups)} cases found (OCR mode)")

    print(f"[4] 케이스별 섹션 파싱...")
    cases = []
    for i, g in enumerate(groups):
        try:
            parsed = parse_case(g, year=year, source_pdf=pdf_path.name)
            if parsed:
                cases.append(parsed)
                title = parsed.get('title') or 'N/A'
                title_display = title[:50] if title else 'N/A'
                print(f"  [OK] Case {i+1}: {title_display}")
        except Exception as e:
            print(f"  [ERROR] Case {i+1}: {str(e)}")
            import traceback
            traceback.print_exc()

    return {
        "year": year,
        "total_cases": len(cases),
        "parsing_statistics": {
            "extraction_mode": extraction_mode,
            "page_count": len(pages),
            "case_count": len(cases),
        },
        "cases": cases,
    }


def main():
    """메인 실행"""
    # 특정 파일만 처리
    target_name = "2018년 물품 분쟁조정 사례집.pdf"
    target_pdf = PDF_DIR / target_name

    if not target_pdf.exists():
        print(f"ERROR: File not found: {target_pdf}")
        return

    pdf_files = [target_pdf]
    print(f"[FILES] Processing: {target_name}")

    all_results = []
    for pdf in pdf_files:
        print(f"\n{'='*80}")
        print(f"Parsing: {pdf.name}")
        print(f"{'='*80}")

        try:
            result = parse_pdf(pdf)
            status = "[OK] SUCCESS"
        except Exception as e:
            print(f"ERROR: {str(e)}")
            result = {
                "year": safe_int(re.search(r"(\d{4})년", pdf.name).group(1)) if re.search(r"(\d{4})년", pdf.name) else None,
                "total_cases": 0,
                "error": str(e),
                "cases": [],
            }
            status = "[FAIL]"

        all_results.append(result)

        # PDF와 같은 폴더에 저장
        out_path = pdf.with_suffix(".json")
        write_json(out_path, result)
        print(f"\n{status}")
        print(f"[SAVED] {out_path}")
        print(f"   Cases: {result.get('total_cases', 0)}")

    print(f"\n{'='*80}")
    print(f"[OK] Parsing complete")
    print(f"  Total cases: {sum(r.get('total_cases', 0) for r in all_results)}")


if __name__ == "__main__":
    main()
