import json
import re
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional

# =========================
# INPUT / OUTPUT
# =========================
IN_PATH = Path(r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_jsonl_data\consumer_dispute_resolution_criteria_table3_warranty.jsonl")
OUT_PATH = Path(r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_data_chunks\table3_warranty_item_chunks_v2.jsonl")

# =========================
# POLICY (조절 포인트)
# =========================
# 1) item_chunk가 이 길이를 넘으면 parent/detail로 분해
MAX_ITEM_CHARS = 380

# 2) detail도 너무 길면 추가 분해
MAX_DETAIL_CHARS = 380

# 3) detail soft split 목표 길이
DETAIL_TARGET_CHARS = 320

# =========================
# utils
# =========================
WS_RE = re.compile(r"\s+")
SPLIT_HINT_RE = re.compile(r"(\n+|[;]|[·・‧∙ㆍ]|[※□■●○]|①|②|③|④|⑤|⑥|⑦|⑧|⑨|⑩|\s*\|\s*)")

def md5_10(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:10]

def norm_spaces(s: str) -> str:
    return WS_RE.sub(" ", (s or "")).strip()

def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)

# =========================
# splitting helpers
# =========================
def split_text_soft(text: str, target_chars: int, hard_max: int) -> List[str]:
    """
    의미 단위(구분자 힌트) 우선으로 쪼개고, 필요 시 공백 기준으로 강제 분할.
    - target_chars 근처로 묶되, hard_max는 넘지 않게 한다.
    """
    t = (text or "").strip()
    if not t:
        return []
    if len(t) <= hard_max:
        return [t]

    # 1) 구분자 기반 토큰화(구분자 보존)
    parts = []
    last = 0
    for m in SPLIT_HINT_RE.finditer(t):
        start, end = m.span()
        if start > last:
            parts.append(t[last:start])
        parts.append(t[start:end])
        last = end
    if last < len(t):
        parts.append(t[last:])

    # 2) target 근처로 누적
    chunks = []
    buf = ""
    for p in parts:
        if not p:
            continue
        cand = (buf + p) if buf else p

        # hard_max 초과면 flush
        if len(cand) > hard_max:
            if buf.strip():
                chunks.append(buf.strip())
                buf = p
            else:
                buf = p

            # 3) 버퍼가 hard_max보다 크면 공백 기준으로 강제 분할
            while len(buf) > hard_max:
                cut = buf.rfind(" ", 0, hard_max)
                if cut <= 0:
                    cut = hard_max
                chunks.append(buf[:cut].strip())
                buf = buf[cut:].strip()

            continue

        # target에 가까우면 적당히 끊기(너무 짧게 끊지는 않음)
        if len(cand) >= target_chars and buf.strip():
            # cand를 바로 확정하고 다음으로
            chunks.append(cand.strip())
            buf = ""
            continue

        buf = cand

    if buf.strip():
        chunks.append(buf.strip())

    return [c for c in chunks if c]

# =========================
# item parsing / splitting
# =========================
def parse_item_fields(item_raw: str):
    """
    item_raw -> (item_clean, item_group_meta, item_type)
    - rule 감지
    - "- " 제거
    - "... - 품목" 분리
    """
    s = norm_spaces(item_raw)

    # 규칙형(품목이 아니라 설명문 성격)
    if s.startswith("6.") and "별도의 기간" in s:
        return s, None, "rule"

    if s.startswith("- "):
        s = s[2:].strip()

    if " - " in s:
        left, right = s.split(" - ", 1)
        left = left.strip()
        right = right.strip()
        if right:
            return right, left, None

    return s, None, None

def split_by_comma_outside_brackets(s: str) -> List[str]:
    """
    괄호/대괄호/중괄호 밖의 콤마만 split
    """
    s = norm_spaces(s)
    if not s:
        return []
    if "," not in s:
        return [s]

    out = []
    buf = []
    depth = 0
    opens = set("([{")
    closes = set(")]}")

    for ch in s:
        if ch in opens:
            depth += 1
            buf.append(ch)
            continue
        if ch in closes:
            depth = max(0, depth - 1)
            buf.append(ch)
            continue
        if ch == "," and depth == 0:
            token = "".join(buf).strip()
            if token:
                out.append(token)
            buf = []
            continue
        buf.append(ch)

    last = "".join(buf).strip()
    if last:
        out.append(last)

    return [x for x in out if x]

def detect_item_level(item: str) -> str:
    s = (item or "").strip()
    if re.match(r"^\d+\.\s*", s):
        return "section"
    if re.match(r"^\d+\)\s*", s):
        return "subsection"
    return "item"

# =========================
# embed_text builder
# =========================
def build_embed_text(
    item: str,
    warranty: Optional[str],
    parts: Optional[str],
    note: Optional[str],
    item_group_meta: Optional[str],
) -> str:
    lines = [f"[품목] {item}"]
    if warranty:
        lines.append(f"[보증기간] {norm_spaces(warranty)}")
    if parts:
        lines.append(f"[부품보유기간] {norm_spaces(parts)}")
    if note:
        lines.append(f"[비고] {norm_spaces(note)}")
    if item_group_meta:
        lines.append(f"분류: {norm_spaces(item_group_meta)}")
    return "\n".join(lines).strip()

def build_parent_anchor_text(
    item: str,
    item_group_meta: Optional[str],
    has_warranty: bool,
    has_parts: bool,
    has_note: bool,
) -> str:
    """
    parent는 '원문 앵커/조회용'이므로 짧게.
    - 임베딩 대상에서 제외할 예정(record_type=item_parent_chunk)
    """
    flags = []
    if has_warranty:
        flags.append("보증기간")
    if has_parts:
        flags.append("부품보유기간")
    if has_note:
        flags.append("비고")
    flags_txt = ", ".join(flags) if flags else "필드없음"

    lines = [f"[품목] {item}", f"[포함필드] {flags_txt}"]
    if item_group_meta:
        lines.append(f"분류: {norm_spaces(item_group_meta)}")
    return "\n".join(lines).strip()

# =========================
# long chunk split (parent/detail) - method #2
# =========================
def make_parent_and_details(
    base_id: str,
    source_meta: Dict[str, Any],
    parent_block: Dict[str, Any],
    item: str,
    item_group_meta: Optional[str],
    warranty: Optional[str],
    parts: Optional[str],
    note: Optional[str],
) -> List[Dict[str, Any]]:
    """
    method #2:
      - parent_chunk는 원문 앵커(짧게) + 원문 parent.text 보관
      - VectorDB에는 detail만 넣는 운영이 쉬움(record_type으로 필터)
      - detail이 길면 soft split로 추가 분해
    """
    out: List[Dict[str, Any]] = []

    # parent (짧은 앵커 텍스트)
    parent_chunk = {
        "source": "table3",
        "record_type": "item_parent_chunk",
        "stable_id": f"{base_id}:parent",
        "embed_text": build_parent_anchor_text(
            item=item,
            item_group_meta=item_group_meta,
            has_warranty=bool(warranty),
            has_parts=bool(parts),
            has_note=bool(note),
        ),
        "metadata": {
            **source_meta,
            "field": "parent_anchor",
            "parent_stable_id": None,
        },
        # 원문 링크/검증 용도
        "parent": parent_block,
    }
    out.append(parent_chunk)

    # details (필드별)
    fields = [
        ("보증기간", warranty),
        ("부품보유기간", parts),
        ("비고", note),
    ]

    seq = 0
    for label, content in fields:
        if not content:
            continue

        content_norm = norm_spaces(content)
        prefix = f"[품목] {item}\n[{label}] "
        content_norm = norm_spaces(content)
        
        # split은 content만 수행
        if len(prefix) + len(content_norm) > MAX_DETAIL_CHARS:
            content_pieces = split_text_soft(
                content_norm,
                target_chars=max(50, DETAIL_TARGET_CHARS - len(prefix)),
                hard_max=max(80, MAX_DETAIL_CHARS - len(prefix)),
            )
        else:
            content_pieces = [content_norm]
        
        # 각 조각에 prefix를 다시 붙여서 저장
        pieces = [(prefix + cp).strip() for cp in content_pieces if cp.strip()]

        for pi, p in enumerate(pieces):
            detail_chunk = {
                "source": "table3",
                "record_type": "item_detail_chunk",
                "stable_id": f"{base_id}:d{seq:02d}_{pi:02d}",
                "embed_text": p,
                "metadata": {
                    **source_meta,
                    "field": label,
                    "parent_stable_id": parent_chunk["stable_id"],
                },
                "parent": parent_block,
            }
            out.append(detail_chunk)

        seq += 1

    return out

# =========================
# main
# =========================
def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(f"Input not found: {IN_PATH}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    n_in = 0
    n_out = 0
    n_rule = 0
    n_parent = 0
    n_detail = 0
    n_item = 0

    with OUT_PATH.open("w", encoding="utf-8") as w:
        for rec in iter_jsonl(IN_PATH):
            n_in += 1
            payload = rec.get("payload") or {}
            doc = rec.get("doc") or {}
            loc = rec.get("loc") or {}

            item_raw = payload.get("item") or ""
            warranty = payload.get("warranty_period")
            parts = payload.get("parts_retention_period")
            note = payload.get("note")

            item_clean, item_group_meta, item_type = parse_item_fields(item_raw)

            doc_id = doc.get("doc_id")
            table_id = loc.get("table_id")
            row_index = loc.get("row_index")

            parent_block = {
                "loc": loc,
                "doc": doc,
                "text": rec.get("text"),
            }

            # 공통 메타(검색/필터링에 쓰이는 정보)
            base_meta = {
                "item_raw": item_raw,
                "item_base": item_clean,
                "item_group_meta": item_group_meta,
                "item_type": item_type,
                "item_level": detect_item_level(item_clean),

                "page": loc.get("page"),
                "doc_id": doc_id,
                "table_id": table_id,
                "row_index": row_index,
            }

            # ---- rule_chunk (폭발 대상 제외) ----
            if item_type == "rule":
                n_rule += 1
                h = md5_10(item_clean)
                stable_id = f"table3:rule:{doc_id}:{table_id}:{row_index}:h{h}"

                rule_chunk = {
                    "source": "table3",
                    "record_type": "rule_chunk",
                    "stable_id": stable_id,
                    "embed_text": build_embed_text(
                        item=item_clean,
                        warranty=warranty,
                        parts=parts,
                        note=note,
                        item_group_meta=item_group_meta,
                    ),
                    "metadata": {
                        **base_meta,
                        "item": item_clean,
                        "field": "rule",
                        "parent_stable_id": None,
                    },
                    "parent": parent_block,
                }

                w.write(json.dumps(rule_chunk, ensure_ascii=False) + "\n")
                n_out += 1
                continue

            # ---- item 폭발(품목 리스트 분리) ----
            items = split_by_comma_outside_brackets(item_clean)
            if not items:
                continue

            for i, it in enumerate(items):
                it = norm_spaces(it)
                if not it:
                    continue

                n_item += 1

                h = md5_10(it)
                base_id = f"table3:item:{doc_id}:{table_id}:{row_index}:{i}:h{h}"

                # 기본 item_chunk 텍스트
                item_text = build_embed_text(
                    item=it,
                    warranty=warranty,
                    parts=parts,
                    note=note,
                    item_group_meta=item_group_meta,
                )

                # 길이 기준으로 분기
                if len(item_text) <= MAX_ITEM_CHARS:
                    # 짧으면 item_chunk 그대로 1개만
                    chunk = {
                        "source": "table3",
                        "record_type": "item_chunk",
                        "stable_id": base_id,
                        "embed_text": item_text,
                        "metadata": {
                            **base_meta,
                            "item": it,
                            "item_level": detect_item_level(it),
                            "field": "item",
                            "parent_stable_id": None,
                        },
                        "parent": parent_block,
                    }
                    w.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                    n_out += 1
                    continue

                # 길면 parent + detail 생성 (parent는 앵커/조회용, detail이 검색용)
                source_meta = {
                    **base_meta,
                    "item": it,
                    "item_level": detect_item_level(it),
                }

                chunks = make_parent_and_details(
                    base_id=base_id,
                    source_meta=source_meta,
                    parent_block=parent_block,
                    item=it,
                    item_group_meta=item_group_meta,
                    warranty=warranty,
                    parts=parts,
                    note=note,
                )

                for ch in chunks:
                    w.write(json.dumps(ch, ensure_ascii=False) + "\n")
                    n_out += 1
                    if ch["record_type"] == "item_parent_chunk":
                        n_parent += 1
                    elif ch["record_type"] == "item_detail_chunk":
                        n_detail += 1

    print("[DONE]")
    print(f"- input_rows       : {n_in}")
    print(f"- output_chunks    : {n_out}")
    print(f"- item_exploded    : {n_item}")
    print(f"- rule_chunks      : {n_rule}")
    print(f"- parent_chunks    : {n_parent}")
    print(f"- detail_chunks    : {n_detail}")
    print(f"[OUT] {OUT_PATH}")

if __name__ == "__main__":
    main()
