import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pdfplumber

# =========================================================
# Reduce pdfminer warnings (optional)
# =========================================================
logging.getLogger("pdfminer").setLevel(logging.ERROR)

# =========================================================
# Path config (relative to this .py file)
# =========================================================
BASE_DIR = Path(__file__).resolve().parent  # ...\data_n_db\B_case
KCA_DIR = BASE_DIR / "01_B_parsed" / "02_01_SolutionCase" / "01_kca"

YEAR_START = 2010
YEAR_END = 2020  # inclusive

# =========================================================
# Patterns
# =========================================================
# Item header like "1. 가구"
ITEM_HEADER_RE = re.compile(r"^\s*(\d{1,2})\.\s+(.+?)\s*$")

# "라. 주요 합의권고 사례" (라/마/바... can vary)
MAJOR_CASES_RE = re.compile(r"^\s*[가-하]\.\s*주요\s*합의권고\s*사례\s*$")

CASE_BULLET = "▣"

# Footer patterns:
FOOTER_DASH_RE = re.compile(r"[-–—]\s*(\d{1,4})\s*[-–—]")  # "- 50 -"
FOOTER_DASH_LINE_RE = re.compile(r"^\s*[-–—]\s*\d{1,4}\s*[-–—]\s*$")

FOOTER_DIGITS_LINE_RE = re.compile(r"^\s*(\d{1,4})\s*$")  # "50" alone
# Page number line that may include suffix like "쪽"/"頁"/"page" or stray symbols
FOOTER_PAGE_NUM_LINE_RE = re.compile(
    r"^\s*(?:제\s*)?(\d{1,4})\s*(?:쪽|頁|page|p\.?)?\s*[^\w가-힣]*\s*$",
    re.IGNORECASE,
)

# Pipe footer like: "| 제2편 피해구제 | 95"
FOOTER_PIPE_RE = re.compile(r"\|\s*제\s*\d+\s*편.*?\|\s*(\d{1,4})\s*$")
FOOTER_PIPE_LINE_RE = re.compile(r"^\s*\|\s*제\s*\d+\s*편.*?\|\s*\d{1,4}\s*$")

# Bullet footer like: "50 • 2014 소비자피해구제 연보 및 사례집" or "• 55"
FOOTER_BULLET_NUM_RE = re.compile(r"^\s*(\d{1,4})\s*[•·]\s*.*$")
FOOTER_BULLET_ONLY_NUM_RE = re.compile(r"^\s*[•·]\s*(\d{1,4})\s*$")

# Next part heading
NEXT_PART_RE = re.compile(r"^\s*제\s*\d+\s*편\b")

# Canonical section keys
SECTION_KEYS = ["사건개요", "쟁점사항", "판단경위", "처리결과"]

# Bracket style: 【사건 개요】 (띄어쓰기 허용)
SECTION_BRACKET_RE = re.compile(
    r"【\s*(사건\s*개요|쟁점\s*사항|판단\s*경위|처리\s*결과)\s*】"
)

# Plain heading line style: 사건 개요 (띄어쓰기 허용)
SECTION_PLAIN_LINE_RE = re.compile(
    r"^\s*(사건\s*개요|쟁점\s*사항|판단\s*경위|처리\s*결과)\s*$"
)


def canonicalize_label(label: str) -> str:
    """Remove all spaces to map to 사건개요/쟁점사항/판단경위/처리결과."""
    return re.sub(r"\s+", "", label)


# =========================================================
# Text helpers
# =========================================================
def normalize_text(t: str) -> str:
    t = t.replace("\u00ad", "")  # soft hyphen
    t = t.replace("\xa0", " ")
    t = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in t.splitlines())
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t


def extract_year_from_first_page(text: str) -> Optional[str]:
    years = re.findall(r"\b(19\d{2}|20\d{2})\b", text)
    return years[0] if years else None


def split_lines(text: str) -> List[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


# =========================================================
# Footer handling
# =========================================================
def extract_printed_page_no(raw_text: str) -> Optional[str]:
    """
    1) '- 50 -' style anywhere
    2) In last N lines: '| 제2편 ... | 95' style
    3) In last N lines: digits-only line '95'
    """
    m = FOOTER_DASH_RE.search(raw_text)
    if m:
        return m.group(1)

    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    tail = lines[-12:]  # bottom area

    for ln in reversed(tail):
        m2 = FOOTER_PIPE_RE.search(ln)
        if m2:
            return m2.group(1)

    for ln in reversed(tail):
        m2b = FOOTER_BULLET_NUM_RE.match(ln)
        if m2b:
            return m2b.group(1)

    for ln in reversed(tail):
        m2c = FOOTER_BULLET_ONLY_NUM_RE.match(ln)
        if m2c:
            return m2c.group(1)

    for ln in reversed(tail):
        m3 = FOOTER_DIGITS_LINE_RE.match(ln)
        if m3:
            return m3.group(1)

    for ln in reversed(tail):
        m4 = FOOTER_PAGE_NUM_LINE_RE.match(ln)
        if m4:
            return m4.group(1)

    return None


def remove_footer_lines_for_parsing(raw_text: str) -> str:
    """
    Remove footer noise from PAGE-level text so it doesn't pollute parsing.
    - Always remove '- 50 -' lines.
    - Remove pipe footer '| 제2편 ... | 95' only near bottom.
    - Remove digits-only lines only near bottom.
    """
    lines = raw_text.splitlines()
    if not lines:
        return raw_text

    kept = []
    total = len(lines)
    bottom_zone_start = max(0, total - 12)  # last 12 lines are "bottom zone"

    for idx, ln in enumerate(lines):
        s = ln.strip()

        # dash footer anywhere
        if FOOTER_DASH_LINE_RE.match(s):
            continue

        # bottom-only removals
        if idx >= bottom_zone_start:
            if FOOTER_PIPE_LINE_RE.match(s):
                continue
            if FOOTER_BULLET_NUM_RE.match(s):
                continue
            if FOOTER_BULLET_ONLY_NUM_RE.match(s):
                continue
            if FOOTER_DIGITS_LINE_RE.match(s):
                continue
            if FOOTER_PAGE_NUM_LINE_RE.match(s):
                continue

        kept.append(ln)

    cleaned = "\n".join(kept)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


# =========================================================
# Item section location
# =========================================================
def find_item_headers(pages_lines: List[List[str]]) -> List[Tuple[int, int, str]]:
    headers = []
    for pi, lines in enumerate(pages_lines):
        for line in lines:
            m = ITEM_HEADER_RE.match(line)
            if m:
                headers.append((pi, int(m.group(1)), m.group(2)))
                break
    headers.sort(key=lambda x: (x[0], x[1]))
    return headers


def slice_ranges(headers: List[Tuple[int, int, str]], total_pages: int) -> List[Tuple[int, int, int, str]]:
    ranges = []
    for i, (start_pi, item_no, item_name) in enumerate(headers):
        end_pi = headers[i + 1][0] if i + 1 < len(headers) else total_pages
        ranges.append((start_pi, end_pi, item_no, item_name))
    return ranges


def find_major_cases_line(lines: List[str]) -> Optional[int]:
    for i, line in enumerate(lines):
        if MAJOR_CASES_RE.match(line):
            return i
    return None


def trim_major_cases_body(lines_after_heading: List[str]) -> List[str]:
    trimmed = []
    for line in lines_after_heading:
        # next item begins
        if ITEM_HEADER_RE.match(line):
            break
        # next subsection begins (but not the same heading)
        if re.match(r"^\s*[가-하]\.\s*", line) and ("주요 합의권고 사례" not in line):
            break
        trimmed.append(line)
    return trimmed


# =========================================================
# Case parsing
# =========================================================
def split_cases_by_bullet_with_pages(lines_with_page: List[Tuple[int, str]]) -> List[List[Tuple[int, str]]]:
    blocks: List[List[Tuple[int, str]]] = []
    current: List[Tuple[int, str]] = []
    for page_no, line in lines_with_page:
        if line.startswith(CASE_BULLET):
            if current:
                blocks.append(current)
            current = [(page_no, line)]
        else:
            if current:
                current.append((page_no, line))
    if current:
        blocks.append(current)
    return blocks


def clean_case_lines(block_lines: List[str]) -> List[str]:
    """
    Remove noise inside a case:
    - '- 50 -' line
    - '| 제2편 ... | 95' line
    - digits-only '95' line
    - '제2편 ...' big heading line
    """
    cleaned = []
    for ln in block_lines:
        s = ln.strip()
        if FOOTER_DASH_LINE_RE.match(s):
            continue
        if FOOTER_PIPE_LINE_RE.match(s):
            continue
        if FOOTER_DIGITS_LINE_RE.match(s):
            continue
        if NEXT_PART_RE.match(s):
            continue
        cleaned.append(ln)
    return cleaned


def parse_case_block(block_lines: List[str]) -> Dict:
    block_lines = clean_case_lines(block_lines)

    raw = "\n".join(block_lines).strip()
    title = block_lines[0].lstrip(CASE_BULLET).strip() if block_lines else ""

    sections: Dict[str, Optional[str]] = {k: None for k in SECTION_KEYS}

    # 1) bracket style split first
    parts = SECTION_BRACKET_RE.split(raw)
    if len(parts) >= 3:
        for i in range(1, len(parts) - 1, 2):
            label = canonicalize_label(parts[i])
            content = parts[i + 1].strip()
            if label in sections:
                sections[label] = content
        return {"title": title, "sections": sections, "raw": raw}

    # 2) plain heading lines
    current_label = None
    buf: List[str] = []

    def flush():
        nonlocal buf, current_label
        if current_label:
            key = canonicalize_label(current_label)
            content = "\n".join(buf).strip()
            if key in sections and content:
                sections[key] = content
        buf = []

    for ln in block_lines[1:]:
        s = ln.strip()
        m = SECTION_PLAIN_LINE_RE.match(s)
        if m:
            flush()
            current_label = m.group(1)
        else:
            if current_label:
                buf.append(ln)

    flush()
    return {"title": title, "sections": sections, "raw": raw}


# =========================================================
# PDF parsing per file
# =========================================================
def parse_pdf(pdf_path: Path) -> Dict:
    pages_text: List[str] = []
    pages_lines: List[List[str]] = []
    printed_page_nos: List[Optional[str]] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            raw_text = normalize_text(page.extract_text() or "")

            # Extract printed page no from raw (before removal)
            printed_no = extract_printed_page_no(raw_text)

            # Remove footer lines for parsing
            clean_text = remove_footer_lines_for_parsing(raw_text)

            pages_text.append(clean_text)
            pages_lines.append(split_lines(clean_text))
            printed_page_nos.append(printed_no)

    year = extract_year_from_first_page(pages_text[0]) if pages_text else None

    headers = find_item_headers(pages_lines)
    ranges = slice_ranges(headers, len(pages_text))

    result = {
        "source_pdf": str(pdf_path),
        "year": year,
        "items": []
    }

    for start_pi, end_pi, item_no, item_name in ranges:
        flat: List[Tuple[int, str]] = []
        for pi in range(start_pi, end_pi):
            pdf_page_index_1based = pi + 1
            for line in pages_lines[pi]:
                flat.append((pdf_page_index_1based, line))

        only_lines = [l for _, l in flat]
        major_idx = find_major_cases_line(only_lines)
        if major_idx is None:
            continue

        body = only_lines[major_idx + 1 :]
        body = trim_major_cases_body(body)

        body_with_pages = flat[major_idx + 1 :]
        body_with_pages = [(p, l) for p, l in body_with_pages if l in body]
        case_blocks = split_cases_by_bullet_with_pages(body_with_pages)

        cases = []
        for cb in case_blocks:
            cb_lines = [l for _, l in cb]
            case_obj = parse_case_block(cb_lines)
            case_start_pdf_page = cb[0][0] if cb else flat[major_idx][0]
            case_start_printed = printed_page_nos[case_start_pdf_page - 1]
            case_obj["source"] = {
                "pdf_page_index": case_start_pdf_page,
                "printed_page_no": case_start_printed
            }
            cases.append(case_obj)

        result["items"].append({
            "item_no": item_no,
            "item_name": item_name,
            "cases": cases
        })

    return result


# =========================================================
# Batch runner (2010~2020)
# =========================================================
def find_pdf_for_year(year: int) -> Optional[Path]:
    exact = KCA_DIR / f"{year}년 소비자분쟁 해결사례집.pdf"
    if exact.exists():
        return exact
    candidates = list(KCA_DIR.glob(f"{year}년*해결사례집*.pdf"))
    return sorted(candidates)[0] if candidates else None


def run_batch():
    KCA_DIR.mkdir(parents=True, exist_ok=True)

    processed = 0
    skipped: List[int] = []

    for year in range(YEAR_START, YEAR_END + 1):
        pdf_path = find_pdf_for_year(year)
        if not pdf_path:
            skipped.append(year)
            print(f"[SKIP] {year} PDF not found in: {KCA_DIR}")
            continue

        out_json = KCA_DIR / f"{year}_해결사례.json"

        try:
            data = parse_pdf(pdf_path)

            # Fill year if extraction fails
            if not data.get("year"):
                data["year"] = str(year)

            with open(out_json, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            processed += 1
            print(f"[OK] {year} -> {out_json.name} (items={len(data.get('items', []))})")

        except Exception as e:
            print(f"[ERROR] {year} failed: {pdf_path.name} | {type(e).__name__}: {e}")

    print("\n===== SUMMARY =====")
    print(f"Processed: {processed} file(s)")
    if skipped:
        print(f"Missing years: {skipped}")
    print(f"Output dir: {KCA_DIR}")


def main():
    run_batch()


if __name__ == "__main__":
    main()



