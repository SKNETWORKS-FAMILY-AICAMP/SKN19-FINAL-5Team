"""
01_02_parsing_adjustment_2.py
---------------------------------
KISA 전자거래 분쟁조정 사례집(2010~2024) PDF를 배치로 구조 파싱해서 JSON으로 저장합니다.

✅ 목표
1) 텍스트 PDF: pdfplumber로 텍스트 추출 → 사건번호 기준 케이스 묶기 → 섹션 분리
2) 스캔/이미지/폰트깨짐 PDF: (페이지 렌더링 → Gemini Vision 페이지별 텍스트 추출) → 동일 파서 재사용
3) 페이지번호 꼬임 대응: physical_pages(0-based PDF index) + printed_pages(문서 하단 쪽번호) 둘 다 저장
4) OCR 캐시: PDF 1개당 캐시 파일 1개로 저장 (파일 폭증 방지)

✅ 속도 최적화(중요)
- (A) 앞부분(표지/목차/머리말) 스킵: pre-scan으로 "사건번호" 처음 등장 페이지(start_page) 추정
- (B) 배치 OCR: 2페이지씩 묶어서 Gemini 호출 (호출 수 1/2로 감소)
- (C) 렌더링 zoom 기본 2.0 (2.5보다 빠름/가벼움)

✅ 필요 패키지
pip install pdfplumber pymupdf python-dotenv google-genai

✅ .env 예시
GEMINI_API_KEY=xxxx
GEMINI_MODEL=gemini-2.5-flash

✅ 출력
- PDF와 같은 폴더에 같은 파일명으로 .json 생성
- 통합본: 02_kisa/ALL_YEARS_kisa_adjustment_cases.json
- OCR 캐시: 02_kisa/_cache_gemini_ocr/{PDF스테미}.ocr_cache.json
"""

import os
import re
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import pdfplumber
import fitz  # PyMuPDF
from dotenv import load_dotenv
from google import genai


# ---------------------------
# Paths (relative)
# ---------------------------
BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "01_B_parsed" / "02_02_AdjustmentCase" / "02_kisa"
CACHE_DIR = PDF_DIR / "_cache_gemini_ocr"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------
# Env / Gemini config
# ---------------------------
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY가 .env에 없습니다. .env에 GEMINI_API_KEY=... 를 설정하세요.")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
client = genai.Client(api_key=GEMINI_API_KEY)


# ---------------------------
# Speed knobs (tune here)
# ---------------------------
OCR_ZOOM = float(os.getenv("OCR_ZOOM", "2.0"))              # 1.8~2.2 권장
OCR_BATCH_SIZE = int(os.getenv("OCR_BATCH_SIZE", "2"))      # 2 or 3 권장
OCR_PRE_SCAN_PAGES = int(os.getenv("OCR_PRE_SCAN_PAGES", "60"))  # 60~100 권장
OCR_PER_BATCH_SLEEP = float(os.getenv("OCR_PER_BATCH_SLEEP", "0.0"))  # 레이트리밋 시 0.2~0.5


# ---------------------------
# Regex rules
# ---------------------------
RE_CASE_NO = re.compile(r"사건\s*번호\s*[:：]?\s*(CA\d{2}\s*[-–]\s*\d{5})")
RE_METHOD = re.compile(r"조정방법\s*[:：]?\s*([^\n]+)")
RE_TITLE = re.compile(r"사건명칭\s*[:：]?\s*([^\n]+)")

SECTION_RULES = {
    "사건개요": re.compile(r"(?m)^\s*1\.\s*사건\s*개요\s*$"),
    "당사자주장": re.compile(r"(?m)^\s*2\.\s*(당사자\s*주장|양\s*당사자\s*주장)\s*$"),
    "판단": re.compile(r"(?m)^\s*3\.\s*(사무국|조정부).{0,12}판단\s*$"),
    "결과": re.compile(r"(?m)^\s*4\.\s*(권고\(안\)\s*수락\s*여부|조정안\s*권고결과|권고결과).*\s*$"),
}

RE_PRINTED_PAGE = re.compile(
    r"(?m)^\s*(\d{2,4})\s*(?:\|\s*)?\s*(\d{4})년\s*$"
)
RE_CID = re.compile(r"\(cid:\d+\)")


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


# ---------------------------
# Printed page detection
# ---------------------------
def detect_printed_page(text: str) -> Optional[int]:
    tail = text[-1200:] if text else ""
    matches = list(RE_PRINTED_PAGE.finditer(tail))
    if not matches:
        return None
    m = matches[-1]
    try:
        return int(m.group(1))
    except:
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
    sample = " ".join(p.text for p in pages[:5]).strip()
    if len(sample) < 50:
        return True

    has_cid = bool(RE_CID.search(sample)) or ("cid" in sample)
    hangul_cnt = len(re.findall(r"[가-힣]", sample))
    hangul_ratio = hangul_cnt / max(len(sample), 1)

    if has_cid and hangul_ratio < 0.01:
        return True

    if hangul_ratio < 0.003:
        return True

    return False


# ---------------------------
# Gemini OCR (page render -> vision) + PDF 1개당 캐시 1개 + 속도 최적화
# ---------------------------
def render_page_to_png_bytes(pdf_path: Path, page_idx: int, zoom: float) -> bytes:
    doc = fitz.open(pdf_path)
    page = doc.load_page(page_idx)
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    doc.close()
    return pix.tobytes("png")


def render_page_to_png_bytes_clipped(pdf_path: Path, page_idx: int, zoom: float, clip: Tuple[float, float, float, float]) -> bytes:
    """
    clip: (x0, y0, x1, y1) in PDF points (PyMuPDF 좌표계)
    """
    doc = fitz.open(pdf_path)
    page = doc.load_page(page_idx)
    rect = fitz.Rect(*clip)
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, clip=rect, alpha=False)
    doc.close()
    return pix.tobytes("png")


def _gemini_call_extract_text_multi(images: List[bytes], page_indices: List[int], model: str) -> str:
    """
    여러 페이지 이미지를 한 번에 넣고,
    반드시 아래 포맷으로만 출력하도록 강제:
      [PAGE <idx>]
      ...
    """
    assert len(images) == len(page_indices)

    prompt = (
        "너는 OCR 엔진이다. 아래에 여러 개의 '문서 페이지 이미지'가 주어진다.\n"
        "각 이미지의 텍스트를 최대한 그대로 추출하되, 출력은 반드시 다음 형식만 사용해라:\n"
        "[PAGE <페이지번호>]\n"
        "<해당 페이지의 추출 텍스트>\n\n"
        "규칙:\n"
        "1) 페이지번호는 내가 제공한 page index를 그대로 사용해라.\n"
        "2) '사건번호', '조정방법', '사건명칭' 라벨과 값, '1. 사건 개요' 같은 섹션 제목(번호/마침표 포함)을 절대 누락하지 마라.\n"
        "3) 표/박스는 블록이 섞이지 않게 줄바꿈으로 구분해라.\n"
        "4) 추가 설명/해설/요약 금지. 오직 위 포맷으로만 출력.\n"
        "5) 각 페이지는 반드시 1번씩만 출력해라.\n"
    )

    parts = [{"text": prompt}]

    # 이미지 순서와 page index 매핑을 명시적으로 알려줌
    mapping_text = "페이지 매핑:\n" + "\n".join([f"- 이미지 {i+1} => PAGE {pidx}" for i, pidx in enumerate(page_indices)])
    parts.append({"text": mapping_text})

    for img in images:
        parts.append({"inline_data": {"mime_type": "image/png", "data": img}})

    resp = client.models.generate_content(
        model=model,
        contents=[{"role": "user", "parts": parts}],
    )
    return (getattr(resp, "text", None) or "").strip()


def gemini_extract_text_multi_with_retry(
    images: List[bytes],
    page_indices: List[int],
    model: str,
    max_retries: int = 4,
    base_sleep: float = 1.2,
) -> str:
    last_err = None
    for attempt in range(max_retries):
        try:
            return _gemini_call_extract_text_multi(images, page_indices, model=model)
        except Exception as e:
            last_err = e
            time.sleep(base_sleep * (2 ** attempt))
    raise RuntimeError(f"Gemini OCR 실패: {last_err}")


def split_multi_page_output(text: str) -> Dict[int, str]:
    """
    Gemini가 출력한:
      [PAGE 12]
      ...
      [PAGE 13]
      ...
    를 {12: "...", 13: "..."}로 분리
    """
    if not text:
        return {}

    # 헤더 기준으로 split
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


def looks_like_bad_layout(txt: str) -> bool:
    """
    다단/레이아웃 섞임으로 파싱 품질이 떨어질 가능성이 높을 때 True.
    완벽한 판별은 어렵고 '재시도 트리거'용 휴리스틱.
    """
    if not txt:
        return True

    # 케이스/섹션 앵커가 전혀 없으면 의심
    anchor_hits = 0
    if RE_CASE_NO.search(txt): anchor_hits += 1
    if re.search(r"(?m)^\s*1\.\s*사건\s*개요\s*$", txt): anchor_hits += 1
    if re.search(r"(?m)^\s*2\.\s*(당사자\s*주장|양\s*당사자\s*주장)\s*$", txt): anchor_hits += 1
    if re.search(r"(?m)^\s*3\.\s*(사무국|조정부).{0,12}판단\s*$", txt): anchor_hits += 1
    if re.search(r"(?m)^\s*4\.\s*(권고|조정안).*\s*$", txt): anchor_hits += 1

    if anchor_hits == 0:
        return True

    # 흔히 다단 섞일 때 목차/머리말 같은 잡텍스트가 본문 중간중간 끼는 현상 방지(너 예시에 실제로 섞임)
    noisy_tokens = ["머리말", "발간사", "제1편", "제2편", "제3편", "제4편"]
    noisy_count = sum(1 for t in noisy_tokens if t in txt)

    # 앵커는 있는데 잡토큰이 과하게 많이 끼면 섞였을 가능성
    if anchor_hits <= 2 and noisy_count >= 3:
        return True

    return False


def ocr_page_with_columns(pdf_path: Path, page_idx: int, zoom: float) -> str:
    """
    1페이지를 좌/우 2분할하여 OCR 후 좌->우 순서로 합친다.
    """
    doc = fitz.open(pdf_path)
    page = doc.load_page(page_idx)
    w = page.rect.width
    h = page.rect.height
    doc.close()

    # 중앙 분할. 가운데 경계 겹침/누락을 줄이기 위해 margin을 약간 둠(포인트 단위)
    margin = 8.0
    mid = w / 2.0

    left_clip = (0, 0, mid + margin, h)
    right_clip = (mid - margin, 0, w, h)

    left_img = render_page_to_png_bytes_clipped(pdf_path, page_idx, zoom, left_clip)
    right_img = render_page_to_png_bytes_clipped(pdf_path, page_idx, zoom, right_clip)

    # 한 번에 2개 이미지 넣고, 출력은 [PAGE <idx>]로 동일하게 받되,
    # 내부 텍스트는 "LEFT"와 "RIGHT"를 구분해받아 합친다.
    prompt = (
        "너는 OCR 엔진이다. 동일한 페이지를 왼쪽/오른쪽 두 이미지로 나누어 제공한다.\n"
        "출력은 반드시 다음 형식만 사용해라:\n"
        "[PAGE {page_idx} LEFT]\n<왼쪽 텍스트>\n"
        "[PAGE {page_idx} RIGHT]\n<오른쪽 텍스트>\n\n"
        "규칙:\n"
        "1) 왼쪽은 왼쪽 컬럼만, 오른쪽은 오른쪽 컬럼만.\n"
        "2) 요약/해설 금지. 텍스트만.\n"
    ).format(page_idx=page_idx)

    parts = [{"text": prompt}]
    parts.append({"inline_data": {"mime_type": "image/png", "data": left_img}})
    parts.append({"inline_data": {"mime_type": "image/png", "data": right_img}})

    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[{"role": "user", "parts": parts}],
    )
    out = (getattr(resp, "text", None) or "").strip()

    # LEFT/RIGHT 분리
    m_left = re.search(rf"\[PAGE\s+{page_idx}\s+LEFT\]\s*\n", out)
    m_right = re.search(rf"\[PAGE\s+{page_idx}\s+RIGHT\]\s*\n", out)
    if not (m_left and m_right):
        # 포맷이 안 맞으면 그냥 전체를 반환(최후 폴백)
        return out

    # LEFT 텍스트
    left_start = m_left.end()
    right_pos = m_right.start()
    left_txt = out[left_start:right_pos].strip()

    # RIGHT 텍스트
    right_start = m_right.end()
    right_txt = out[right_start:].strip()

    # 좌 -> 우 순서 강제
    merged = (left_txt + "\n" + right_txt).strip()
    return merged


def load_or_init_cache(pdf_path: Path, zoom: float) -> Tuple[Path, dict, dict]:
    cache_path = CACHE_DIR / f"{pdf_path.stem}.ocr_cache.json"
    cache_obj = read_json(cache_path)
    if not isinstance(cache_obj, dict):
        cache_obj = {"pdf": pdf_path.name, "model": GEMINI_MODEL, "zoom": zoom, "pages": {}}

    pages_cache = cache_obj.get("pages", {})
    if not isinstance(pages_cache, dict):
        pages_cache = {}
        cache_obj["pages"] = pages_cache

    # zoom/모델이 바뀌어도 기존 캐시를 재사용할 수는 있지만,
    # 원하면 여기서 zoom/모델 불일치 시 pages를 비우도록 바꿀 수도 있음(현재는 재사용 우선)
    cache_obj["model"] = GEMINI_MODEL
    cache_obj["zoom"] = zoom

    return cache_path, cache_obj, pages_cache


def estimate_start_page_by_prescan(
    pdf_path: Path,
    total_pages: int,
    zoom: float,
    batch_size: int,
    pre_scan_pages: int,
) -> int:
    """
    앞부분 몇 페이지만 OCR 스캔하여 사건번호가 처음 등장하는 페이지를 찾는다.
    찾으면 그 페이지를 start_page로 반환, 못 찾으면 0 반환(=전체 OCR).
    """
    scan_until = min(total_pages, max(pre_scan_pages, batch_size))
    # 0..scan_until-1만 대상으로 prescan
    prescan_indices = list(range(scan_until))

    # 배치 단위로 호출
    for i in range(0, len(prescan_indices), batch_size):
        batch = prescan_indices[i:i + batch_size]
        images = [render_page_to_png_bytes(pdf_path, p, zoom) for p in batch]
        raw = gemini_extract_text_multi_with_retry(images, batch, model=GEMINI_MODEL)
        page_map = split_multi_page_output(raw)

        # 사건번호 등장 확인
        for p in batch:
            txt = page_map.get(p, "")
            if RE_CASE_NO.search(txt):
                return p

    return 0


def extract_pages_text_gemini_ocr_optimized(
    pdf_path: Path,
    zoom: float = OCR_ZOOM,
    batch_size: int = OCR_BATCH_SIZE,
    pre_scan_pages: int = OCR_PRE_SCAN_PAGES,
    per_batch_sleep: float = OCR_PER_BATCH_SLEEP,
) -> List[PageText]:
    """
    ✅ 속도 최적화 OCR:
    - prescan으로 start_page 추정(앞부분 스킵)
    - batch OCR(2페이지씩)
    - 캐시: PDF 1개당 1개 파일에 page_idx->text 저장
    """
    doc = fitz.open(pdf_path)
    total = doc.page_count
    doc.close()

    cache_path, cache_obj, pages_cache = load_or_init_cache(pdf_path, zoom=zoom)

    # 1) start_page 추정 (이미 캐시에 사건번호 있는 페이지가 있으면 그것을 우선)
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

    # 2) 전체 페이지 중 start_page 이전은 원칙적으로 스킵
    #    단, 기존 캐시에 이미 있으면 그대로 PageText를 만들 수는 있음(여기서는 굳이 필요 없으니 생략)
    pages: List[PageText] = []

    # start_page부터 끝까지 처리
    indices = list(range(start_page, total))

    for i in range(0, len(indices), batch_size):
        batch = indices[i:i + batch_size]

        # batch 중 캐시에 없는 것만 OCR 호출
        need = [p for p in batch if (str(p) not in pages_cache) or (not isinstance(pages_cache[str(p)], str)) or (not pages_cache[str(p)].strip())]

        if need:
            images = [render_page_to_png_bytes(pdf_path, p, zoom) for p in need]
            raw = gemini_extract_text_multi_with_retry(images, need, model=GEMINI_MODEL)
            page_map = split_multi_page_output(raw)

            for p in need:
                txt = page_map.get(p, "").strip()

                # ✅ 다단/레이아웃 섞임 의심 시: 해당 페이지는 좌/우 분할 OCR로 재시도
                if looks_like_bad_layout(txt):
                    try:
                        txt2 = ocr_page_with_columns(pdf_path, p, zoom).strip()
                        # 재시도 결과가 더 낫다고 판단되면 교체
                        if txt2 and (len(txt2) >= len(txt) * 0.9):
                            txt = txt2
                    except Exception:
                        pass

                pages_cache[str(p)] = txt

            # 매 배치마다 저장(중단 복구)
            write_json(cache_path, cache_obj)

        # batch 페이지들 PageText 구성(캐시에서 가져옴)
        for p in batch:
            txt = pages_cache.get(str(p), "") if isinstance(pages_cache.get(str(p), ""), str) else ""
            printed = detect_printed_page(txt)
            pages.append(PageText(page_idx=p, text=txt, printed_page=printed))

        if per_batch_sleep > 0:
            time.sleep(per_batch_sleep)

    return pages


# ---------------------------
# Case grouping + section splitting
# ---------------------------
def group_cases_by_case_no(pages: List[PageText]) -> List[List[PageText]]:
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


def parse_case(case_pages: List[PageText], year: Optional[int], source_pdf: str) -> Dict:
    full_text = "\n".join(p.text for p in case_pages)

    m_no = RE_CASE_NO.search(full_text)
    m_method = RE_METHOD.search(full_text)
    m_title = RE_TITLE.search(full_text)

    case_no = m_no.group(1).replace(" ", "") if m_no else None
    method = m_method.group(1).strip() if m_method else None
    title = m_title.group(1).strip() if m_title else None

    sections = split_sections(full_text)

    printed_pages = [p.printed_page for p in case_pages if p.printed_page is not None]
    phys_pages = [p.page_idx for p in case_pages]

    return {
        "year": year,
        "source_pdf": source_pdf,
        "case_id": case_no,
        "method": method,
        "title": title,
        "sections": sections,
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
    m = re.search(r"(\d{4})년", pdf_path.name)
    year = safe_int(m.group(1)) if m else None

    # 1) textpdf 시도
    pages_textpdf = extract_pages_text_textpdf(pdf_path, max_pages=None)

    # 2) OCR 필요하면 gemini_ocr 수행(최적화 버전)
    if should_use_ocr(pages_textpdf):
        pages = extract_pages_text_gemini_ocr_optimized(
            pdf_path,
            zoom=OCR_ZOOM,
            batch_size=OCR_BATCH_SIZE,
            pre_scan_pages=OCR_PRE_SCAN_PAGES,
            per_batch_sleep=OCR_PER_BATCH_SLEEP,
        )
        extraction_mode = "gemini_ocr"
    else:
        pages = pages_textpdf
        extraction_mode = "textpdf"

    # 3) 케이스 그룹핑
    groups = group_cases_by_case_no(pages)

    # 4) textpdf인데 케이스 0개면 OCR로 재시도
    if extraction_mode == "textpdf" and len(groups) == 0:
        pages = extract_pages_text_gemini_ocr_optimized(
            pdf_path,
            zoom=OCR_ZOOM,
            batch_size=OCR_BATCH_SIZE,
            pre_scan_pages=OCR_PRE_SCAN_PAGES,
            per_batch_sleep=OCR_PER_BATCH_SLEEP,
        )
        extraction_mode = "gemini_ocr"
        groups = group_cases_by_case_no(pages)

    cases = [parse_case(g, year=year, source_pdf=pdf_path.name) for g in groups]

    return {
        "year": year,
        "source_pdf": pdf_path.name,
        "extraction_mode": extraction_mode,
        "page_count": len(pages),
        "case_count": len(cases),
        "ocr_zoom": OCR_ZOOM if extraction_mode == "gemini_ocr" else None,
        "ocr_batch_size": OCR_BATCH_SIZE if extraction_mode == "gemini_ocr" else None,
        "ocr_pre_scan_pages": OCR_PRE_SCAN_PAGES if extraction_mode == "gemini_ocr" else None,
        "cases": cases,
    }


def main():
    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDF found in: {PDF_DIR}")
        return

    all_results = []
    for pdf in pdf_files:
        print(f"\n--- Parsing: {pdf.name}")
        try:
            result = parse_pdf(pdf)
        except Exception as e:
            result = {
                "year": safe_int(re.search(r"(\d{4})년", pdf.name).group(1)) if re.search(r"(\d{4})년", pdf.name) else None,
                "source_pdf": pdf.name,
                "error": str(e),
                "cases": [],
            }

        all_results.append(result)

        # ✅ PDF와 같은 폴더에 같은 파일명으로 저장
        out_path = pdf.with_suffix(".json")
        write_json(out_path, result)
        print(f"Saved: {out_path}  (cases={result.get('case_count', 0)}, mode={result.get('extraction_mode', 'n/a')})")

    merged_path = PDF_DIR / "ALL_YEARS_kisa_adjustment_cases.json"
    write_json(merged_path, all_results)
    print(f"\nSaved merged: {merged_path}")


if __name__ == "__main__":
    main()

