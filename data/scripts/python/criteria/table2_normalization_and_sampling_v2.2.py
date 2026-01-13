# table2_stage2_extract_laws_v2_2.py
# Stage2 v2.2: reference_block.jsonl -> law_candidates_v2_2.jsonl
#
# 목표(2단계에서 끝):
# - ref_kind 분리: law / notice / terms
# - law는 doc_id 매칭용 canonicalize(조문/별표/부칙 제거)
# - notice/terms는 "보존용 canonicalize"(조문/제nn호 등 제거 금지)로 정보 손실 방지
# - derived(시행령/시행규칙) 과잉 생성 방지: 근접성 조건(같은 줄/인접 줄)로 제한
# - unquoted 보조 추출은 옵션으로 ON/OFF 가능(기본 OFF 권장)
# - law 후보 노이즈(근거 법/기타 법/기관명/위원회 등) 강하게 제외
# - notice/terms에는 재생성 가능한 안정 키(notice_id/terms_id) 부여(해시)
#
# 입력/출력:
# - Windows 절대 경로 사용 (아래 __main__에서 수정)
# - doc_id 매칭(3단계)은 포함하지 않음
#
# 실행 후 추천 검수:
# 1) terms 후보가 "표준약관(제100xx호...)" 같이 번호까지 유지되는지
# 2) notice 후보가 "고시 제xxxx호" 등 식별자 유지되는지
# 3) law 후보에 '근거 법/기타 법/위원회' 등이 남지 않는지
# 4) derived가 과하게 생성되지 않는지(특히 여러 법령이 섞인 블록)

import json
import re
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# -----------------------------
# Patterns
# -----------------------------

QUOTE_PAT = re.compile(r"[「『](.+?)[」』]")

# 비인용 보조 후보(옵션): "…법/법률/시행령/시행규칙"으로 끝나는 덩어리
UNQUOTED_LAW_PAT = re.compile(r"([가-힣0-9ㆍ·\-\s()]{4,}?(?:법률|법|시행령|시행규칙))")

# law 전용 꼬리 제거(조문/별표/부칙) - terms/notice에는 적용 금지
LAW_TAIL_NOISE_PAT = re.compile(
    r"\s*(제\s*\d+\s*조(?:의\s*\d+)?"
    r"|제\s*\d+\s*항|제\s*\d+\s*호"
    r"|별표\s*\d+|부칙)\b.*$"
)

BRACKET_META_PAT = re.compile(r"\[[^\]]+\]")

# terms: 줄 단위 스캔
TERMS_LINE_PAT = re.compile(r"^.*(?:표준약관|약관).*$", re.MULTILINE)

# notice: 줄 단위 스캔
NOTICE_LINE_PAT = re.compile(r"^.*(?:고시|훈령|예규|지침).*$", re.MULTILINE)

# derived 근접성: 같은 줄에 시행령/시행규칙 등장 시
DERIVED_WORDS = ("시행령", "시행규칙")

# -----------------------------
# Keyword sets
# -----------------------------

NOTICE_KEYWORDS = ["고시", "훈령", "예규", "지침"]
TERMS_KEYWORDS = ["표준약관", "약관"]

ORG_NOISE_KEYWORDS = [
    "위원회", "협회", "센터", "기관", "공단", "공사", "재단", "연합", "조합",
    "분쟁조정", "분쟁조정위원회", "조정위원회", "분쟁조정기구",
    "중앙회", "연구원", "진흥원", "지원센터", "상담센터",
]

LAW_FRAGMENT_BLACKLIST = {
    "근거 법", "기타 법", "관련 법", "관계 법", "관계법", "관련법",
    "근거법", "기타법",
}

# -----------------------------
# Helpers
# -----------------------------

def collapse_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def sha1_id(text: str, prefix: str) -> str:
    h = hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{h}"

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
    if not s:
        return s
    s2 = s.strip()
    if s2.startswith("(") and not s2.endswith(")"):
        return s2.lstrip("(").strip()
    return s2

def canonicalize_law(name: str) -> str:
    """
    law_map 매칭용:
    - [..] 메타 제거
    - 조문/별표/부칙 등 꼬리 제거
    - 끝의 단독 '등' 제거
    """
    s = (name or "").strip()
    if not s:
        return ""
    s = strip_unbalanced_parens_prefix(s)
    s = s.rstrip(" ,.;:·")
    s = BRACKET_META_PAT.sub("", s).strip()
    s = LAW_TAIL_NOISE_PAT.sub("", s).strip()
    s = collapse_spaces(s)
    s = re.sub(r"\s+등$", "", s).strip()
    return s

def canonicalize_preserve(name: str) -> str:
    """
    notice/terms 보존용:
    - [..] 메타는 제거(선택적으로 유지하고 싶으면 여기서 주석 처리)
    - 조문/제nn호 같은 식별자는 유지(자르지 않음)
    - 공백만 정리
    """
    s = (name or "").strip()
    if not s:
        return ""
    s = s.rstrip(" ,.;:·")
    s = BRACKET_META_PAT.sub("", s).strip()
    s = collapse_spaces(s)
    return s

def looks_like_law_name(s: str) -> bool:
    """law 후보 형태 검증: 법/법률/시행령/시행규칙으로 끝나야 함"""
    return bool(re.search(r"(법률|법|시행령|시행규칙)$", s or ""))

def is_law_noise(canon: str) -> bool:
    if not canon:
        return True
    if canon in LAW_FRAGMENT_BLACKLIST:
        return True
    if any(k in canon for k in TERMS_KEYWORDS + NOTICE_KEYWORDS):
        return True
    if any(k in canon for k in ORG_NOISE_KEYWORDS):
        return True
    if not looks_like_law_name(canon):
        return True
    return False

# -----------------------------
# Candidate builder with dedupe
# -----------------------------

PRIO = {
    "quoted": 6,
    "derived": 5,
    "unquoted": 4,
    "notice_scan": 3,
    "terms_scan": 3,
}

def add_candidate(
    uniq: Dict[Tuple[str, str], Dict[str, Any]],
    *,
    ref_kind: str,
    source: str,
    name_raw: str,
    line_index: Optional[int] = None,
    derived_from: Optional[str] = None,
    type_hint: Optional[str] = None,
) -> None:
    """
    dedupe key: (ref_kind, canonical)
    - law: canonicalize_law
    - notice/terms: canonicalize_preserve
    """
    raw = collapse_spaces(name_raw)
    if not raw:
        return

    if ref_kind == "law":
        canon = canonicalize_law(raw)
        if is_law_noise(canon):
            return
    else:
        canon = canonicalize_preserve(raw)
        if not canon:
            return

    key = (ref_kind, canon)
    rec = {
        "ref_kind": ref_kind,
        "source": source,
        "name_raw": raw,
        "name_canonical": canon,
        "line_index": line_index,
        "derived_from": derived_from,
        "type_hint": type_hint,
    }

    # 안정 키(후속 활용용)
    if ref_kind == "notice":
        rec["notice_id"] = sha1_id(canon, "notice")
    elif ref_kind == "terms":
        # 약관은 번호가 들어가면 안정적이므로 canonical 전체 기반으로 hash
        rec["terms_id"] = sha1_id(canon, "terms")

    if key not in uniq:
        uniq[key] = rec
    else:
        if PRIO.get(source, 0) > PRIO.get(uniq[key]["source"], 0):
            uniq[key] = rec

# -----------------------------
# Derived proximity logic
# -----------------------------

def build_line_index(text: str) -> List[str]:
    lines = [collapse_spaces(x) for x in (text or "").splitlines()]
    return [l for l in lines if l]

def find_last_law_quote_in_line(line: str) -> Optional[str]:
    """
    한 줄에서 마지막 quoted law를 찾는다.
    - ref_kind 판단은 line 내 quoted 문자열로만 수행(terms/notice는 제외)
    """
    last = None
    for m in QUOTE_PAT.finditer(line or ""):
        raw = collapse_spaces(m.group(1) or "")
        if not raw:
            continue
        if classify_ref_kind(raw) != "law":
            continue
        canon = canonicalize_law(raw)
        if not is_law_noise(canon):
            last = raw
    return last

def generate_derived_from_proximity(lines: List[str], i: int) -> List[Tuple[str, str]]:
    """
    derived 생성:
    - 현재 라인 i에 시행령/시행규칙 단어가 있을 때만 시도
    - base law는 (우선) 같은 줄에 인용된 마지막 law
    - 없으면 바로 위 라인(i-1)에서 마지막 law 인용을 찾음
    - 그래도 없으면 생성하지 않음
    반환: [(derived_name, type_hint), ...]
    """
    line = lines[i]
    if not any(w in line for w in DERIVED_WORDS):
        return []

    base = find_last_law_quote_in_line(line)
    if not base and i - 1 >= 0:
        base = find_last_law_quote_in_line(lines[i - 1])

    if not base:
        return []

    out = []
    if "시행령" in line:
        out.append((f"{base} 시행령", "시행령"))
    if "시행규칙" in line:
        out.append((f"{base} 시행규칙", "시행규칙"))
    return out

# -----------------------------
# Main extraction
# -----------------------------

def extract_candidates_v2_2(text: str, *, enable_unquoted: bool = False) -> List[Dict[str, Any]]:
    """
    2단계 v2.2:
    - quoted: law/notice/terms 모두 추출(단, law는 형태 검증)
    - notice_scan / terms_scan: 인용부호 없어도 줄 단위로 보존
    - derived: 근접성 조건으로 제한 생성
    - unquoted: 옵션(기본 OFF)
    """
    uniq: Dict[Tuple[str, str], Dict[str, Any]] = {}
    lines = build_line_index(text)

    # (1) quoted 추출 (line_index 포함)
    for idx, line in enumerate(lines):
        for m in QUOTE_PAT.finditer(line):
            raw = collapse_spaces(m.group(1) or "")
            if not raw:
                continue
            rk = classify_ref_kind(raw)

            # quoted가 law로 분류되더라도 "법/법률/시행령/시행규칙" 형태가 아니면 제외
            # (terms/notice는 형태 검증하지 않음)
            if rk == "law":
                canon = canonicalize_law(raw)
                if is_law_noise(canon):
                    continue

            add_candidate(
                uniq,
                ref_kind=rk,
                source="quoted",
                name_raw=raw,
                line_index=idx,
            )

    # (2) derived 생성(근접성)
    for i in range(len(lines)):
        for derived_name, hint in generate_derived_from_proximity(lines, i):
            add_candidate(
                uniq,
                ref_kind="law",
                source="derived",
                name_raw=derived_name,
                line_index=i,
                derived_from=None,  # 필요하면 base를 넣을 수도 있으나, derived_name에서 충분히 추적 가능
                type_hint=hint,
            )

    # (3) notice_scan: 줄 단위 보존
    for idx, line in enumerate(lines):
        if any(k in line for k in NOTICE_KEYWORDS):
            add_candidate(
                uniq,
                ref_kind="notice",
                source="notice_scan",
                name_raw=line,
                line_index=idx,
            )

    # (4) terms_scan: 줄 단위 보존
    for idx, line in enumerate(lines):
        if any(k in line for k in TERMS_KEYWORDS):
            add_candidate(
                uniq,
                ref_kind="terms",
                source="terms_scan",
                name_raw=line,
                line_index=idx,
            )

    # (5) unquoted 보조(옵션): law만
    if enable_unquoted:
        for idx, line in enumerate(lines):
            for m in UNQUOTED_LAW_PAT.finditer(line):
                raw = collapse_spaces(m.group(1) or "")
                if not raw:
                    continue
                if classify_ref_kind(raw) != "law":
                    continue
                canon = canonicalize_law(raw)
                if is_law_noise(canon):
                    continue
                add_candidate(
                    uniq,
                    ref_kind="law",
                    source="unquoted",
                    name_raw=raw,
                    line_index=idx,
                )

    # 결과 반환
    return list(uniq.values())

# -----------------------------
# IO
# -----------------------------

def stringify_block(obj: Dict[str, Any]) -> str:
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
    *,
    enable_unquoted: bool = False,
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
    derived_count = 0

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

            candidates = extract_candidates_v2_2(raw_text, enable_unquoted=enable_unquoted) if raw_text else []

            # 통계
            kinds_in_row = set()
            for c in candidates:
                rk = c.get("ref_kind")
                if rk in kind_counts:
                    kind_counts[rk] += 1
                    kinds_in_row.add(rk)
                if c.get("source") == "derived":
                    derived_count += 1
            for rk in kinds_in_row:
                row_has_kind[rk] += 1

            out_rec = {
                "ref_id": ref_id,
                "page": page,
                "raw_text": raw_text,         # 원문 보존(절대 축약/수정하지 않음)
                "candidates": candidates,
                "params": {
                    "enable_unquoted": enable_unquoted,
                    "version": "v2_2",
                }
            }
            w.write(json.dumps(out_rec, ensure_ascii=False) + "\n")

            # 샘플 출력
            if sample_every and total % sample_every == 0:
                print(f"\n--- SAMPLE @ {total} (ref_id={ref_id}, page={page}) ---")
                print(raw_text[:500] + ("..." if len(raw_text) > 500 else ""))
                print("candidates(kind:canon:source):")
                for c in candidates:
                    print(f"- {c['ref_kind']}: {c['name_canonical']} ({c['source']})")

    print("\n[Stage2 v2.2 완료]")
    print(f"- input : {in_file}")
    print(f"- output: {out_file}")
    print(f"- total rows         : {total}")
    print(f"- rows w/ empty text : {empty_text}")
    print(f"- candidate counts   : {kind_counts}")
    print(f"- rows having kind   : {row_has_kind}")
    print(f"- derived count      : {derived_count}")
    print("\n[추천 검수]")
    print("1) terms 후보에 '제100xx호' 같은 번호가 유지되는지 확인")
    print("2) notice 후보에 '고시 제xxxx호' 같은 식별자가 유지되는지 확인")
    print("3) law 후보에 '근거 법/기타 법/위원회' 등이 남지 않는지 확인")
    print("4) derived가 과잉 생성되지 않는지 확인")
    print("\n[팁]")
    print("- unquoted는 기본 OFF(enable_unquoted=False) 권장. quoted 누락이 많으면 ON으로 재시도.")


if __name__ == "__main__":
    # ✅ Windows 절대 경로 고정 (필요 시 너 환경에 맞게만 수정)
    INPUT_PATH = r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_jsonl_data\consumer_dispute_resolution_criteria_table2_resolutions_reference_block.jsonl"
    OUTPUT_PATH = r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_jsonl_data\consumer_dispute_resolution_criteria_table2_law_candidates_v2_2.jsonl"

    # 기본: unquoted OFF (권장)
    main(
        in_path=INPUT_PATH,
        out_path=OUTPUT_PATH,
        enable_unquoted=False,
        max_rows=None,
        sample_every=0,
    )

    # 만약 quoted 누락이 많아 law 후보가 너무 적으면 아래를 켜서 재생성:
    # main(INPUT_PATH, OUTPUT_PATH.replace("_v2_2", "_v2_2_unquoted_on"), enable_unquoted=True)
