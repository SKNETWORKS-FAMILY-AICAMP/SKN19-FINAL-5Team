# table2_stage2_extract_laws_v2_1.py
# Stage2 v2.1: reference_block.jsonl -> law_candidates_v2_1.jsonl
#
# 목표:
# - candidates에 ref_kind 포함: law / notice / terms
# - terms(표준약관/약관)을 누락 없이 따로 추출(terms_scan)
# - unquoted(비인용) 노이즈(근거 법/기타 법/기관명 등) 강하게 차단
# - derived(시행령/시행규칙)는 base가 "law"일 때만 생성
# - doc_id 매칭(3단계)은 포함하지 않음
#
# 실행 전/후 체크 포인트:
# 1) candidates 내 ref_kind="terms"가 실제로 생성되는지
# 2) law 후보에 "근거 법", "기타 법" 같은 조각이 사라졌는지
# 3) 위원회/협회/센터/기관 등 기관명이 law 후보로 들어오지 않는지
# 4) notice(고시/훈령/예규/지침)가 law로 섞이지 않는지

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --------------------
# 정규식 패턴
# --------------------

# 인용부호: 「 」, 『 』
QUOTE_PAT = re.compile(r"[「『](.+?)[」』]")

# 비인용 보조 후보(너무 공격적이면 노이즈 발생 -> 필터로 제어)
UNQUOTED_LAW_PAT = re.compile(
    r"([가-힣0-9ㆍ·\-\s()]{4,}?(?:법률|법|시행령|시행규칙))"
)

# 조문/별표/부칙 꼬리 제거
TAIL_NOISE_PAT = re.compile(
    r"\s*(제\s*\d+\s*조(?:의\s*\d+)?"
    r"|제\s*\d+\s*항|제\s*\d+\s*호"
    r"|별표\s*\d+|부칙)\b.*$"
)

# [부처] 같은 메타 제거
BRACKET_META_PAT = re.compile(r"\[[^\]]+\]")

# terms(약관) 스캔: '표준약관' 또는 '약관'이 들어간 구간을 뽑는다
# - 우선 줄 단위/문장 단위로 뽑아 후보 생성
TERMS_LINE_PAT = re.compile(r"^.*(?:표준약관|약관).*$", re.MULTILINE)

# --------------------
# 키워드 분류 기준
# --------------------

NOTICE_KEYWORDS = ["고시", "훈령", "예규", "지침"]
TERMS_KEYWORDS = ["표준약관", "약관"]

DERIVED_HINTS = {
    "시행령": "시행령",
    "시행규칙": "시행규칙",
}

# 기관/비법령 노이즈 키워드 (law 후보에서 제외)
ORG_NOISE_KEYWORDS = [
    "위원회", "협회", "센터", "기관", "공단", "공사", "재단", "연합", "조합",
    "분쟁조정", "분쟁조정위원회", "조정위원회", "분쟁조정기구",
    "중앙회", "연구원", "진흥원", "지원센터", "상담센터",
]

# law로 잡히면 안 되는 조각 후보(정규화 후 비교)
LAW_FRAGMENT_BLACKLIST = {
    "근거 법", "기타 법", "관련 법", "관계 법", "관계법", "관련법",
    "근거법", "기타법",
}

# notice/terms가 law 후보에 섞이지 않도록 강제 제외(정규화 후에도 체크)
LAW_EXCLUDE_CONTAINS = NOTICE_KEYWORDS + TERMS_KEYWORDS

# --------------------
# 유틸 함수
# --------------------

def collapse_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def classify_ref_kind(text: str) -> str:
    t = text or ""
    for k in TERMS_KEYWORDS:
        if k in t:
            return "terms"
    for k in NOTICE_KEYWORDS:
        if k in t:
            return "notice"
    return "law"


def strip_unbalanced_parens_prefix(s: str) -> str:
    """
    "(방문판매법" 같은 케이스에서 선행 괄호만 제거.
    - 시작이 '(' 이고 끝이 ')'가 아닌 경우에만 제거
    """
    if not s:
        return s
    s2 = s.strip()
    if s2.startswith("(") and not s2.endswith(")"):
        return s2.lstrip("(").strip()
    return s2


def canonicalize_name(name: str) -> str:
    """
    공통 정규화:
    - 공백/메타/조문 꼬리 제거
    - 끝의 단독 '등' 제거 (정식명 내 '등에 관한'은 보존)
    - 괄호 앞 불균형 prefix 정리
    """
    s = (name or "").strip()
    if not s:
        return ""

    s = strip_unbalanced_parens_prefix(s)
    s = s.rstrip(" ,.;:·")
    s = BRACKET_META_PAT.sub("", s).strip()
    s = TAIL_NOISE_PAT.sub("", s).strip()
    s = collapse_spaces(s)

    s = re.sub(r"\s+등$", "", s).strip()
    return s


def is_law_noise_candidate(canon: str) -> bool:
    """
    law 후보로 두면 안 되는 노이즈를 강하게 제외한다.
    """
    if not canon:
        return True

    # 1) 정확히 조각 후보
    if canon in LAW_FRAGMENT_BLACKLIST:
        return True

    # 2) notice/terms 키워드 포함하면 law 아님
    if any(k in canon for k in LAW_EXCLUDE_CONTAINS):
        return True

    # 3) 기관/조직/위원회 등 포함하면 law 아님
    if any(k in canon for k in ORG_NOISE_KEYWORDS):
        return True

    # 4) 너무 짧으면 제외(예: "민법"은 2글자이지만 유효 -> 예외 처리)
    #    - "민법" 같은 초단문 법령명 존재 가능하므로, 길이 기준만으로는 자르지 않음
    #    - 대신 아래 '법/법률/시행령/시행규칙' 형태 유효성만 확인
    if not re.search(r"(법률|법|시행령|시행규칙)$", canon):
        return True

    return False


def add_candidate(
    out: Dict[str, Dict[str, Any]],
    name_raw: str,
    ref_kind: str,
    source: str,
    type_hint: Optional[str] = None,
    derived_from: Optional[str] = None,
) -> None:
    """
    canonical 기준으로 중복 제거하며 후보 추가.
    우선순위: quoted > derived > terms_scan > notice_scan > unquoted
    """
    canon = canonicalize_name(name_raw)
    if not canon:
        return

    rec = {
        "name_raw": name_raw,
        "name_canonical": canon,
        "ref_kind": ref_kind,
        "source": source,
        "type_hint": type_hint,
        "derived_from": derived_from,
    }

    prio = {"quoted": 5, "derived": 4, "terms_scan": 3, "notice_scan": 2, "unquoted": 1}
    key = canon

    if key not in out:
        out[key] = rec
    else:
        if prio.get(source, 0) > prio.get(out[key]["source"], 0):
            out[key] = rec


# --------------------
# 핵심 로직: 추출 + ref_kind 분리
# --------------------

def extract_candidates_v2_1(text: str) -> List[Dict[str, Any]]:
    text = text or ""
    uniq: Dict[str, Dict[str, Any]] = {}

    quoted_law_bases: List[str] = []

    # (A) quoted 추출 (law/notice/terms 모두 후보로 넣되, derived base는 law만)
    for m in QUOTE_PAT.finditer(text):
        raw = collapse_spaces(m.group(1) or "")
        if not raw:
            continue

        rk = classify_ref_kind(raw)
        add_candidate(uniq, raw, rk, source="quoted")

        if rk == "law":
            quoted_law_bases.append(raw)

    # (B) derived 생성: base가 law일 때만 시행령/시행규칙 후보 생성
    base = quoted_law_bases[-1] if quoted_law_bases else None
    if base:
        for key, hint in DERIVED_HINTS.items():
            # '시행령'/'시행규칙' 단어가 등장할 때만 파생
            if key in text:
                derived = f"{base} {key}"
                add_candidate(uniq, derived, "law", source="derived", type_hint=hint, derived_from=base)

    # (C) notice 스캔: 인용부호가 없어도 '고시/훈령/예규/지침' 문장을 후보로 남김
    # - law_map 매칭 대상은 아니지만, 나중에 별도 매핑/링크 처리에 쓰일 수 있음
    for kw in NOTICE_KEYWORDS:
        if kw in text:
            # 줄 단위로 보존(너무 길면 later truncate 가능)
            for line in text.splitlines():
                if kw in line:
                    line2 = collapse_spaces(line)
                    if line2:
                        add_candidate(uniq, line2, "notice", source="notice_scan")

    # (D) terms 스캔: 표준약관/약관 줄 단위로 후보 생성
    # - 약관은 law_map에 없을 가능성이 크므로 doc_id 매칭 대상이 아님
    if any(k in text for k in TERMS_KEYWORDS):
        for m in TERMS_LINE_PAT.finditer(text):
            line = collapse_spaces(m.group(0) or "")
            if not line:
                continue
            add_candidate(uniq, line, "terms", source="terms_scan")

    # (E) unquoted 보조 추출: law 후보만 생성(노이즈 강제 필터)
    for m in UNQUOTED_LAW_PAT.finditer(text):
        raw = collapse_spaces(m.group(1) or "")
        if not raw:
            continue

        # 1차 분류: notice/terms면 law 후보로 추가하지 않음
        if classify_ref_kind(raw) != "law":
            continue

        canon = canonicalize_name(raw)
        if is_law_noise_candidate(canon):
            continue

        add_candidate(uniq, raw, "law", source="unquoted")

    # 결과 리스트
    return list(uniq.values())


def stringify_block(obj: Dict[str, Any]) -> str:
    """
    reference_block 레코드에서 참고 텍스트를 최대한 안전하게 합친다.
    """
    parts: List[str] = []

    refs_raw = obj.get("refs_raw")
    if isinstance(refs_raw, list):
        for r in refs_raw:
            if isinstance(r, dict):
                for k in ("text", "raw", "line", "value"):
                    v = r.get(k)
                    if isinstance(v, str) and v.strip():
                        parts.append(v.strip())
                        break
            elif isinstance(r, str) and r.strip():
                parts.append(r.strip())

    raw_lines = obj.get("raw_lines")
    if isinstance(raw_lines, list):
        for line in raw_lines:
            if isinstance(line, str) and line.strip():
                parts.append(line.strip())

    for k in ("raw_text", "raw", "text", "body"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())

    # 중복 제거(순서 유지)
    seen = set()
    dedup = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            dedup.append(p)

    return "\n".join(dedup).strip()


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield i, json.loads(line)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"JSON 파싱 실패: line={i}, error={e}") from e


def main(
    in_path: str,
    out_path: str,
    max_rows: Optional[int] = None,
    sample_every: int = 0,
) -> None:
    in_file = Path(in_path)
    out_file = Path(out_path)

    if not in_file.exists():
        raise FileNotFoundError(f"입력 파일을 찾을 수 없습니다: {in_file}")

    out_file.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    empty_text = 0

    # 통계
    kind_counts = {"law": 0, "notice": 0, "terms": 0}
    row_has_kind = {"law": 0, "notice": 0, "terms": 0}

    with out_file.open("w", encoding="utf-8") as w:
        for line_no, obj in read_jsonl(in_file):
            total += 1
            if max_rows and total > max_rows:
                break

            ref_id = obj.get("ref_id") or obj.get("id") or obj.get("block_id") or f"line:{line_no}"
            page = obj.get("page")

            raw_text = stringify_block(obj)
            if not raw_text:
                empty_text += 1

            candidates = extract_candidates_v2_1(raw_text) if raw_text else []

            # 통계 누적
            kinds_in_row = set()
            for c in candidates:
                rk = c.get("ref_kind")
                if rk in kind_counts:
                    kind_counts[rk] += 1
                    kinds_in_row.add(rk)
            for rk in kinds_in_row:
                row_has_kind[rk] += 1

            out_rec = {
                "ref_id": ref_id,
                "page": page,
                "raw_text": raw_text,
                "candidates": candidates,
            }
            w.write(json.dumps(out_rec, ensure_ascii=False) + "\n")

            if sample_every and total % sample_every == 0:
                print(f"\n--- SAMPLE @ {total} (ref_id={ref_id}, page={page}) ---")
                print(raw_text[:500] + ("..." if len(raw_text) > 500 else ""))
                print("candidates(kind:canon):")
                for c in candidates:
                    print(f"- {c['ref_kind']}: {c['name_canonical']} ({c['source']})")

    print("\n[Stage2 v2.1 완료]")
    print(f"- input : {in_file}")
    print(f"- output: {out_file}")
    print(f"- total rows         : {total}")
    print(f"- rows w/ empty text : {empty_text}")
    print(f"- candidate counts   : {kind_counts}")
    print(f"- rows having kind   : {row_has_kind}")

    print("\n[검수 체크리스트]")
    print("1) terms(표준약관/약관)이 candidates에 실제로 생성되는지 확인")
    print("2) law 후보에 '근거 법/기타 법/관련 법' 같은 조각이 남아있는지 확인(남으면 blacklist 추가)")
    print("3) 기관명(위원회/협회/센터 등)이 law 후보로 들어오지 않는지 확인")
    print("4) notice(고시/훈령/예규/지침)가 law로 섞이지 않는지 확인")


if __name__ == "__main__":
    # ✅ Windows 절대 경로 고정 (요청 반영)
    INPUT_PATH = r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_jsonl_data\consumer_dispute_resolution_criteria_table2_resolutions_reference_block.jsonl"
    OUTPUT_PATH = r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_jsonl_data\consumer_dispute_resolution_criteria_table2_law_candidates_v2_1.jsonl"

    # 빠른 시험:
    # main(INPUT_PATH, OUTPUT_PATH, max_rows=200, sample_every=50)
    # 전체:
    main(INPUT_PATH, OUTPUT_PATH, max_rows=None, sample_every=0)
