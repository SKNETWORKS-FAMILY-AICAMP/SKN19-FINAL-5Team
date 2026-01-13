import json
import re
import hashlib
from pathlib import Path

# =========================
# INPUT / OUTPUT
# =========================
# ✅ 네가 criteria_jsonl_data 폴더에 둔 "수정본"을 입력으로 사용
TABLE1_PATH = r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_jsonl_data\consumer_dispute_resolution_criteria_table1_items.jsonl"

# ✅ 출력 폴더/이름은 네가 쓰던 흐름에 맞춰서
OUT_PATH = r"C:\Users\Playdata\OneDrive\Desktop\criteria_data\criteria_data_chunks\table1_item_chunks.jsonl"

# 동의어(alias) 확장: 기존 유지(필요 시 계속 추가)
SYNONYM_MAP = {
    "렌탈": ["대여", "임대"],
    "대여": ["렌탈", "임대"],
    "임대": ["렌탈", "대여"],
    "AS": ["A/S", "수리"],
    "A/S": ["AS", "수리"],
}

# -----------------------------
# utils
# -----------------------------
def md5_10(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:10]

def norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def iter_jsonl_records(file_path: str):
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)

# -----------------------------
# ✅ 핵심 수정: 괄호/대괄호/중괄호 "밖의 콤마"만 split
# - payload.items (오염 가능) 사용 금지
# - payload.items_raw를 신뢰해서 재분해
# -----------------------------
def split_by_comma_outside_brackets(s: str):
    s = norm_spaces(s)
    if not s:
        return []
    if "," not in s:
        return [s]

    out = []
    buf = []
    depth_round = depth_square = depth_curly = 0

    for ch in s:
        if ch == "(":
            depth_round += 1
        elif ch == ")":
            depth_round = max(0, depth_round - 1)
        elif ch == "[":
            depth_square += 1
        elif ch == "]":
            depth_square = max(0, depth_square - 1)
        elif ch == "{":
            depth_curly += 1
        elif ch == "}":
            depth_curly = max(0, depth_curly - 1)

        depth0 = (depth_round == 0 and depth_square == 0 and depth_curly == 0)

        if ch == "," and depth0:
            token = "".join(buf).strip()
            if token:
                out.append(token)
            buf = []
            continue

        buf.append(ch)

    tail = "".join(buf).strip()
    if tail:
        out.append(tail)

    return [t for t in (norm_spaces(x) for x in out) if t]

# -----------------------------
# 1) item_name 정규화
# - 기존 코드 유지(괄호는 제거하지 않음)
# -----------------------------
LEADING_TRAILING_SYMBOLS = r"[\u2022\u00B7\-\—\–\*\•\·\・\▶\▷\◦\▪\■\□\▣\※\●\○\☆\★\[\]\{\}<>\"'“”‘’]+"
MID_DOT_VARIANTS = r"[·・‧∙ㆍ]"

def normalize_item_name(raw: str) -> str:
    s = raw or ""
    s = s.replace("（", "(").replace("）", ")")
    s = s.replace("【", "[").replace("】", "]")
    s = s.replace("〈", "<").replace("〉", ">")
    s = s.replace("《", "<").replace("》", ">")

    s = norm_spaces(s)

    # 1) 앞뒤 기호만 제거(괄호는 제거하지 않음)
    s = re.sub(rf"^{LEADING_TRAILING_SYMBOLS}", "", s)
    s = re.sub(rf"{LEADING_TRAILING_SYMBOLS}$", "", s)

    # 2) 중간점 통일
    s = re.sub(MID_DOT_VARIANTS, " ", s)
    s = norm_spaces(s)

    # 3) 괄호 찌꺼기(짝 불일치) 최소 보정
    if s.endswith(")") and s.count("(") == 0:
        s = s[:-1].rstrip()
    if s.startswith("(") and s.count(")") == 0:
        s = s[1:].lstrip()

    return norm_spaces(s)

# -----------------------------
# 2) "... 등" alias (공백 + 등만)
# -----------------------------
def extract_alias_no_etc(item_name: str):
    s = norm_spaces(item_name)
    s2 = re.sub(r"\s+등$", "", s)
    if s2 != s and s2:
        return s2
    return None

# -----------------------------
# 3) 동의어/alias 확장 (기존 유지)
# -----------------------------
def extract_paren_parts(s: str):
    s = norm_spaces(s)
    parens = re.findall(r"\(([^)]{1,50})\)", s)  # 너무 긴 괄호는 제외
    base = re.sub(r"\s*\([^)]*\)\s*", " ", s)
    base = norm_spaces(base)
    return base, parens

def expand_synonyms(token: str):
    token = norm_spaces(token)
    out = [token]
    for k, vs in SYNONYM_MAP.items():
        if token == k:
            out.extend(vs)
    seen = set()
    res = []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            res.append(x)
    return res

def generate_aliases(item_name_raw: str, max_aliases: int = 8):
    raw = norm_spaces(item_name_raw)
    base, parens = extract_paren_parts(raw)

    aliases = []
    if base:
        aliases.append(base)

    for p in parens:
        p = norm_spaces(p)
        if not p:
            continue

        variants = []
        if "/" in p:
            variants = [norm_spaces(x) for x in p.split("/") if norm_spaces(x)]
        else:
            variants = [p]

        for v in variants:
            for vv in expand_synonyms(v):
                if base:
                    aliases.append(f"{base} {vv}")
                    aliases.append(f"{vv} {base}")
                else:
                    aliases.append(vv)

    alias_no_etc = extract_alias_no_etc(raw)
    if alias_no_etc:
        aliases.append(alias_no_etc)

    cleaned = []
    seen = set()
    for a in aliases:
        a = normalize_item_name(a)
        if not a:
            continue
        if a not in seen:
            seen.add(a)
            cleaned.append(a)

    return cleaned[:max_aliases]

# -----------------------------
# embed_text (alias 포함)
# -----------------------------
def make_embed_text(item_name_norm: str, aliases: list, category: str, industry: str, item_group: str):
    parts = [item_name_norm]

    alias_top = [a for a in aliases if a and a != item_name_norm][:5]
    if alias_top:
        parts.append("동의어: " + ", ".join(alias_top))

    cls = " / ".join([p for p in [industry, item_group] if p])
    if cls:
        parts.append(f"분류: {cls}")
    if category:
        parts.append(f"카테고리: {category}")

    return "\n".join(parts).strip()

# -----------------------------
# main
# -----------------------------
def main():
    if not Path(TABLE1_PATH).exists():
        raise FileNotFoundError(f"Input not found: {TABLE1_PATH}")

    out = Path(OUT_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)

    n_in = 0
    n_chunks = 0
    n_skipped_empty = 0

    with out.open("w", encoding="utf-8") as w:
        for rec in iter_jsonl_records(TABLE1_PATH):
            n_in += 1

            payload = rec.get("payload") or {}
            doc = rec.get("doc") or {}
            loc = rec.get("loc") or {}

            category = payload.get("category")
            industry = payload.get("industry")
            item_group = payload.get("item_group")
            division = payload.get("division")

            # ✅ 핵심: items_raw만 사용해서 items를 재구성
            items_raw = payload.get("items_raw") or ""
            items = split_by_comma_outside_brackets(items_raw)

            if not items:
                n_skipped_empty += 1
                continue

            for idx, item_name_raw in enumerate(items):
                item_name_raw = norm_spaces(item_name_raw)
                if not item_name_raw:
                    continue

                item_name_norm = normalize_item_name(item_name_raw)
                if not item_name_norm:
                    continue

                aliases = generate_aliases(item_name_raw, max_aliases=8)
                alias_no_etc = extract_alias_no_etc(item_name_raw)

                doc_id = doc.get("doc_id")
                table_id = loc.get("table_id")
                row_index = loc.get("row_index")
                h = md5_10(item_name_raw)

                stable_id = f"table1:item:{doc_id}:{table_id}:{row_index}:{idx}:h{h}"

                chunk = {
                    "source": "table1",
                    "record_type": "item_chunk",
                    "stable_id": stable_id,
                    "embed_text": make_embed_text(
                        item_name_norm=item_name_norm,
                        aliases=aliases,
                        category=category,
                        industry=industry,
                        item_group=item_group,
                    ),
                    "metadata": {
                        "item_name_raw": item_name_raw,
                        "item_name": item_name_norm,
                        "aliases": aliases,
                        "alias_no_etc": alias_no_etc,

                        "category": category,
                        "industry": industry,
                        "item_group": item_group,
                        "division": division,

                        "page": loc.get("page"),
                        "doc_id": doc_id,
                        "table_id": table_id,
                        "row_index": row_index,
                        "parent_element_id": loc.get("element_id"),
                        "parent_record_type": rec.get("record_type"),
                    },
                    "parent": {
                        "source_path": TABLE1_PATH,
                        "loc": loc,
                        "text": rec.get("text"),
                    },
                }

                w.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                n_chunks += 1

    print(f"[DONE] input_rows={n_in}, item_chunks={n_chunks}, skipped_empty_rows={n_skipped_empty}")
    print(f"[OUT] {OUT_PATH}")

if __name__ == "__main__":
    main()
