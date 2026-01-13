import json
import re
from pathlib import Path

# =========================
# Config
# =========================
BASE_DIR = Path(__file__).resolve().parents[2]  # ism/
DATA_DIR = BASE_DIR / "data"

# 1) 제거할 최상위(파생/추출) 필드들
DROP_TOP_LEVEL = {
    # 날짜/시간 파생
    "event_year",
    "time_note",
    "raw_date_text",
    "case_dates",
    "reference_dates",
    "events",
    # 혹시 다른 스크립트에서 만들었을 수 있는 키들
    "event_year_confidence",
    "event_year_source",
    "case_dates_norm",
    "reference_dates_norm",
}

# 2) metadata에서 제거할 키들 (views 포함)
DROP_METADATA_KEYS = {
    "views",
    "views_list",
    "event_year",
    "event_year_confidence",
    "event_year_source",
}

# 3) 텍스트 후처리 옵션
STRIP_VIEWS_LINE_IN_TEXT = True           # [조회수] 라인 제거
DEDUP_HEADER_IN_BODY = True               # [본문] 아래 중복 헤더 제거
NORMALIZE_MASKING_TOKENS = True           # ○○○, **** 표기 통일

# -------------------------
# Text cleaning helpers
# -------------------------
VIEW_LINE_RE = re.compile(r"^\s*\[조회수\].*$")

# ○○○ 같은 연속 원형 마스킹(예: ○정석, ○○공장 등) -> [익명]
CIRCLE_MASK_RE = re.compile(r"○{1,}")

# 39우**** 같은 별표 마스킹 -> [마스킹]
STAR_MASK_RE = re.compile(r"\*{2,}")

def strip_views_line(text: str) -> str:
    if not isinstance(text, str):
        return text
    lines = text.splitlines()
    kept = [ln for ln in lines if not VIEW_LINE_RE.match(ln)]
    return "\n".join(kept)

def normalize_masking(text: str) -> str:
    """
    개인정보 복원이 아니라 '표기 통일' 목적.
    """
    if not isinstance(text, str):
        return text

    # ○○○ -> [익명]
    text = CIRCLE_MASK_RE.sub("[익명]", text)

    # **** -> [마스킹]
    text = STAR_MASK_RE.sub("[마스킹]", text)

    # (선택) 너무 붙어버리면 가독성이 떨어져서, 중복 토큰 간단 정리
    text = text.replace("[익명][익명]", "[익명]")
    text = text.replace("[마스킹][마스킹]", "[마스킹]")
    return text

def dedup_header_in_body(text: str) -> str:
    """
    text_for_embedding 구조가:
    [문서유형]/[제목]/[출처]/[분류] ... (상단 헤더)
    ...
    [본문]
    [문서유형] 분쟁조정 사례
    [제목] ...
    [출처] ...
    [분류] ...
    처럼 반복되는 경우가 많아서,
    [본문] 이후에 나오는 중복 헤더 블록만 제거한다.
    """
    if not isinstance(text, str):
        return text

    if "[본문]" not in text:
        return text

    lines = text.splitlines()
    out = []
    in_body = False

    # [본문] 이후 "헤더로 보이는 라인" 제거 대상
    drop_prefixes = ("[문서유형]", "[제목]", "[출처]", "[분류]")
    # 공백 라인 과다 제거를 위해 연속 빈줄을 1줄로 제한
    prev_blank = False

    for ln in lines:
        if ln.strip() == "[본문]":
            in_body = True
            out.append(ln)
            prev_blank = False
            continue

        if in_body:
            # [본문] 이후 중복 헤더 라인 제거
            if ln.strip().startswith(drop_prefixes):
                continue

        # 빈 줄 정리(연속 2줄 이상은 1줄로)
        is_blank = (ln.strip() == "")
        if is_blank and prev_blank:
            continue

        out.append(ln)
        prev_blank = is_blank

    return "\n".join(out)

def clean_text(text: str) -> str:
    if not isinstance(text, str):
        return text

    if STRIP_VIEWS_LINE_IN_TEXT:
        text = strip_views_line(text)

    if DEDUP_HEADER_IN_BODY:
        text = dedup_header_in_body(text)

    if NORMALIZE_MASKING_TOKENS:
        text = normalize_masking(text)

    return text

# -------------------------
# JSON cleaning
# -------------------------
def clean_obj(obj: dict) -> dict:
    # (A) 최상위 제거
    for k in list(DROP_TOP_LEVEL):
        obj.pop(k, None)

    # (B) views 최상위로 있는 경우 제거
    obj.pop("views", None)
    obj.pop("view", None)

    # (C) metadata 내부 제거
    md = obj.get("metadata")
    if isinstance(md, dict):
        for k in list(DROP_METADATA_KEYS):
            md.pop(k, None)

    # (D) 본문 텍스트 정리
    if "text_for_embedding" in obj and isinstance(obj["text_for_embedding"], str):
        obj["text_for_embedding"] = clean_text(obj["text_for_embedding"])
    if "content" in obj and isinstance(obj["content"], str):
        obj["content"] = clean_text(obj["content"])

    return obj

def is_jsonl(p: Path) -> bool:
    if not (p.is_file() and p.suffix.lower() == ".jsonl"):
        return False

    name = p.name.lower()

    # 이미 clean으로 만든 결과물은 다시 처리하지 않기
    if name.endswith(".clean.jsonl"):
        return False

    # 에러 로그 파일도 제외(원하면 유지 가능)
    if name.endswith("_errors.jsonl") or name.endswith(".errors.jsonl"):
        return False

    return True

def make_out_path(in_path: Path) -> Path:
    # xxx.jsonl -> xxx.clean.jsonl
    return in_path.with_name(in_path.stem + ".clean.jsonl")

def main():
    processed_dirs = list(DATA_DIR.rglob("processed"))
    if not processed_dirs:
        print("No processed directories found under:", DATA_DIR)
        return

    total_in_files = 0
    total_out_files = 0
    total_lines = 0

    for d in processed_dirs:
        jsonl_files = [p for p in d.iterdir() if is_jsonl(p)]
        if not jsonl_files:
            continue

        for in_path in jsonl_files:
            out_path = make_out_path(in_path)

            lines = 0
            with in_path.open("r", encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
                for line in fin:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    obj = clean_obj(obj)
                    fout.write(json.dumps(obj, ensure_ascii=False) + "\n")
                    lines += 1

            total_in_files += 1
            total_out_files += 1
            total_lines += lines
            print(f"[OK] {in_path.relative_to(BASE_DIR)} -> {out_path.relative_to(BASE_DIR)} ({lines} lines)")

    print("\nDone.")
    print("Processed files:", total_in_files)
    print("Output files:", total_out_files)
    print("Total lines:", total_lines)

if __name__ == "__main__":
    main()
