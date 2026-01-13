import json
import re
from pathlib import Path

# scripts/preprocess/event_year_jsonl.py 기준
BASE_DIR = Path(__file__).resolve().parents[2]  # → ism/

IN_PATH = (
    BASE_DIR
    / "data"
    / "cnslt"
    / "processed"
    / "cnslt_cases_114_full.processed.jsonl"
)

OUT_PATH = (
    BASE_DIR
    / "data"
    / "cnslt"
    / "processed"
    / "cnslt_cases_114_full.processed.event_year.jsonl"
)

# =========================
# Date patterns
# =========================
# YYYY.MM.DD / YYYY-MM-DD
DATE_FULL = re.compile(r"\b((?:19|20)\d{2})[./-](\d{1,2})[./-](\d{1,2})\b")

# YYYY년 / YYYY년도
YEAR_ONLY = re.compile(r"\b((?:19|20)\d{2})\s*년(?:도)?\b")

# YY년 / YY년도  (예: 06년)
YEAR_2DIGIT = re.compile(r"\b(\d{2})\s*년(?:도)?\b")

# ✅ 추가: '95.7.11 / 95.7.11 같은 형태 (판례 인용에 자주 나옴)
YY_DOT_MM_DD = re.compile(r"[\'’]?\b(\d{2})\.(\d{1,2})\.(\d{1,2})\b")

# '06.6월 / 06.6월 / ’08.11월 같은 형태
YY_DOT_MM_MONTH = re.compile(r"[\'’]?\b(\d{2})\.(\d{1,2})\s*월\b")

# (선택) '06.6 / 06.6 (월 생략)
# ⚠️ 주의: YY.MM.DD가 존재하는 경우 YY.MM을 따로 뽑지 않도록 아래에서 중복 방지함
YY_DOT_MM = re.compile(r"[\'’]?\b(\d{2})\.(\d{1,2})\b(?!\s*\.\s*\d{1,2})")  # 뒤에 .DD가 오면 매칭 금지

# =========================
# Ruling/notice code patterns (예규 코드)
# =========================
RULING_CODE = re.compile(r"\b[가-힣]{2,4}\d{2,6}(?:-\d{1,6})?\b")

# ✅ 판례번호 패턴 (예: 95다8850, 95다 53942, 2019도1234 등)
CASELAW_CODE = re.compile(r"\b\d{2,4}\s*[가-힣]\s*\d+\b")

PREFERRED = [
    "상담일", "접수일", "작성일", "등록일", "게시일", "문의일",
    "발생", "사고", "구입", "구매", "계약", "수리", "교환", "환불",
    "가입", "진단", "청구", "해지", "치료"
]

# reference/근거로 분류해야 하는 문맥(고시/예규/법령/판례 인용 등)
FORBIDDEN = [
    "고시", "시행", "개정", "제정", "공포", "훈령", "예규", "국세청", "재무부",
    "규정", "기준", "예규는", "예규:", "부가가치세", "부가",
    # ✅ 판례(대법원) 인용 컨텍스트
    "대법원", "선고", "판결", "법원", "재판부", "사건번호"
]

CASELAW_KEYWORDS = ["대법원", "선고", "판결", "법원", "재판부", "사건번호"]

def yy_to_yyyy(yy: int) -> int:
    return 2000 + yy if yy <= 29 else 1900 + yy

def normalize_year_tokens(text: str) -> str:
    # YYYY년/년도 -> YYYY/
    text = YEAR_ONLY.sub(lambda m: f"{m.group(1)}/", text)

    # YY년/년도 -> YYYY/
    def repl(m):
        yyyy = yy_to_yyyy(int(m.group(1)))
        return f"{yyyy}/"
    text = YEAR_2DIGIT.sub(repl, text)
    return text

def is_reference_context(ctx: str) -> bool:
    if any(k in ctx for k in FORBIDDEN):
        return True
    if RULING_CODE.search(ctx):
        return True
    if CASELAW_CODE.search(ctx):
        return True
    return False

def is_caselaw_context(ctx: str) -> bool:
    # ✅ 판례 인용은 pref 여부와 무관하게 reference로 고정
    if any(k in ctx for k in CASELAW_KEYWORDS):
        return True
    if CASELAW_CODE.search(ctx):
        return True
    return False

def extract_dates(text: str):
    """
    날짜/연도 후보를 (start, end, yyyy, raw) 형태로 추출
    - YYYY.MM.DD
    - YYYY년
    - 'YY.MM.DD (판례에서 자주)
    - 'YY.MM월
    - (선택) 'YY.MM  (단, YY.MM.DD 있으면 중복 생성 방지)
    """
    cands = []

    # 1) YYYY.MM.DD
    for m in DATE_FULL.finditer(text):
        yyyy = int(m.group(1))
        cands.append((m.start(), m.end(), yyyy, m.group(0)))

    # 2) YYYY년/년도
    for m in YEAR_ONLY.finditer(text):
        yyyy = int(m.group(1))
        cands.append((m.start(), m.end(), yyyy, m.group(0)))

    # 3) ✅ YY.MM.DD (예: '95.7.11)
    for m in YY_DOT_MM_DD.finditer(text):
        yy = int(m.group(1))
        mm = int(m.group(2))
        dd = int(m.group(3))
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            yyyy = yy_to_yyyy(yy)
            cands.append((m.start(), m.end(), yyyy, m.group(0)))

    # 4) 'YY.MM월
    for m in YY_DOT_MM_MONTH.finditer(text):
        yy = int(m.group(1))
        mm = int(m.group(2))
        if 1 <= mm <= 12:
            yyyy = yy_to_yyyy(yy)
            cands.append((m.start(), m.end(), yyyy, m.group(0)))

    # 5) (선택) 'YY.MM  (정규식에서 (?!\.\d{1,2})로 YY.MM.DD 중복을 원천 방지)
    for m in YY_DOT_MM.finditer(text):
        raw = m.group(0)
        if "월" in raw:
            continue
        yy = int(m.group(1))
        mm = int(m.group(2))
        if 1 <= mm <= 12:
            yyyy = yy_to_yyyy(yy)
            cands.append((m.start(), m.end(), yyyy, raw))

    cands.sort(key=lambda x: x[0])
    return cands

def pick_event_year(text: str):
    dates = extract_dates(text)
    if not dates:
        return None, [], [], "no_date_found"

    case_dates = []
    ref_dates = []

    for s, e, yyyy, raw in dates:
        left = max(0, s - 40)
        right = min(len(text), e + 40)
        ctx = text[left:right]

        pref = any(k in ctx for k in PREFERRED)

        # ✅ 핵심: 판례 인용은 pref와 관계없이 무조건 reference
        if is_caselaw_context(ctx):
            ref_dates.append((raw, yyyy))
            continue

        ref = is_reference_context(ctx)

        if ref and not pref:
            ref_dates.append((raw, yyyy))
        else:
            case_dates.append((raw, yyyy))

    if case_dates:
        return case_dates[0][1], case_dates, ref_dates, "picked_case_date"
    if ref_dates:
        return None, [], ref_dates, "only_reference_date"
    return None, [], [], "ambiguous"

with IN_PATH.open("r", encoding="utf-8") as fin, OUT_PATH.open("w", encoding="utf-8") as fout:
    for line in fin:
        obj = json.loads(line)

        text = obj.get("text_for_embedding") or obj.get("content") or ""
        if isinstance(text, str):
            text = normalize_year_tokens(text)

        event_year, case_dates, ref_dates, reason = pick_event_year(text)

        obj["text_for_embedding"] = text
        obj["event_year"] = event_year
        obj["case_dates"] = [d[0] for d in case_dates]
        obj["reference_dates"] = [d[0] for d in ref_dates]
        obj["time_note"] = reason

        fout.write(json.dumps(obj, ensure_ascii=False) + "\n")

print("Wrote:", OUT_PATH)
