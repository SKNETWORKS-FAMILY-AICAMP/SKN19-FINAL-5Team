import os
import json
import re
from collections import defaultdict
from typing import Dict, Any, List, Optional, Tuple

# =========================
# 0) 파일 경로들 지정
# =========================
# need_laws.json: { "법령 한글명": "파일코드" } 형태
NEED_LAWS_JSON = r"../data/need_laws.json"

IN_DIR  = r"../data/law_jsonldata"   # jsonl 폴더 (입력)
OUT_DIR = r"../data/law_chunks"      # 청킹 결과 폴더 (출력)
os.makedirs(OUT_DIR, exist_ok=True)

# 입력 파일명 규칙
# - 기본: <CODE>.jsonl (xml→jsonl 최종 산출물)
# - fallback: <CODE>.jsonl (기존 파일명이 이 형태라면 자동 인식)
INPUT_SUFFIX = ".jsonl"

# ----- 핵심 옵션 -----
SKIP_NON_INDEXABLE = True

# I 아래 M은 항상 병합 (I+M*)
MERGE_SUBITEMS_UNDER_ITEM = True

# (목이 없는) A/P 아래 I들을 "전체 병합"할지 여부
# - "auto": parent가 나열 프레임 + I가 2개 이상일 때만 병합
# - "never": 절대 병합 안 함 (항목 개별)
MERGE_ITEMS_UNDER_PARENT = "auto"   # "auto" | "never"

# 병합 시 길이 상한(너무 길면 개별로 fallback)
PARENT_ITEM_MERGE_MAX_CHARS = 2500

# "항/조 prefix"를 I 또는 M unit에 붙일지
# - 목이 달린 I(I+M*)에는 prefix를 항상 붙임(권장)
# - 그 외에는 leaf가 약하면(prefix 필요) 붙임
PREFIX_MODE = "conditional"   # "conditional" or "none"


# =========================================================
# 1) 패턴/휴리스틱
# =========================================================
PARA_LIST_FRAME_RE = re.compile(r"(다음|각\s*호|각호|사유|사항|어느\s*하나|각\s*목|각목)")
WEAK_HINT_RE = re.compile(r"(다음\s*각\s*(호|목)|각\s*(호|목)|다음과\s*같다|사항)")
STRONG_ENDING_RE = re.compile(r"(하여야\s*한다|할\s*수\s*있다|할\s*수\s*없다|하지\s*아니한다|금지한다|취소할\s*수\s*있다|청구할\s*수\s*있다)")

def is_list_frame(parent_text: str) -> bool:
    return bool(PARA_LIST_FRAME_RE.search((parent_text or "").strip()))

def needs_context(leaf_text: str) -> bool:
    t = (leaf_text or "").strip()
    if not t:
        return True
    if len(t) < 40:
        return True
    if WEAK_HINT_RE.search(t):
        if STRONG_ENDING_RE.search(t):
            return False
        return True
    if STRONG_ENDING_RE.search(t):
        return False
    return False

def maybe_prefix(parent_text: str, leaf_text: str, mode: str) -> Tuple[str, bool]:
    p = (parent_text or "").strip()
    l = (leaf_text or "").strip()
    if mode == "none" or not p:
        return l, False
    if needs_context(l):
        return p + "\n" + l, True
    return l, False


# =========================================================
# 2) IO
# =========================================================
def read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

def write_jsonl(path: str, rows: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# =========================================================
# 3) 트리 구성 (doc_id 중복 안전)
# =========================================================
def build_tree(nodes: List[Dict[str, Any]]):
    by_id: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    children: Dict[str, List[str]] = defaultdict(list)

    for n in nodes:
        by_id[n["doc_id"]].append(n)

    for n in nodes:
        pid = n.get("parent_id")
        if pid:
            children[pid].append(n["doc_id"])

    for pid in children:
        children[pid].sort()

    return by_id, children

def choose_node_for_meta(candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None
    trues = [c for c in candidates if c.get("is_indexable") is True]
    return trues[0] if trues else candidates[0]

def choose_text_node(candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None
    trues = [c for c in candidates if c.get("is_indexable") is True]
    pool = trues if trues else candidates
    return max(pool, key=lambda x: len((x.get("text") or "").strip()))


# =========================================================
# 4) 청킹 로직
#    목표:
#    - leaf 우선: I가 있으면 I unit (I+M*), 없고 M만 있으면 M unit
#    - "부모 아래 I 전체 병합"은 (목 없는 I들)일 때만 고려
#      * 단, 그 부모 아래 I 중 M을 가진 I가 하나라도 있으면 전체 병합 금지
#    - prefix는 leaf의 직계 부모(A 또는 P)를 사용
#      * 목이 있는 I(I+M*)에는 prefix를 "항상" 붙임 (검색 안정성)
#      * 그 외는 conditional
# =========================================================
def chunk(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id, children = build_tree(nodes)

    def meta(did: str) -> Optional[Dict[str, Any]]:
        return choose_node_for_meta(by_id.get(did, []))

    def text_node(did: str) -> Optional[Dict[str, Any]]:
        return choose_text_node(by_id.get(did, []))

    def text_of(did: str) -> str:
        n = text_node(did) or meta(did)
        return (n.get("text") or "").strip() if n else ""

    def ok(did: str) -> bool:
        n = meta(did) or text_node(did)
        if not n:
            return False
        return bool(n.get("is_indexable", True))

    def level_of(did: str) -> str:
        n = meta(did) or text_node(did)
        return (n.get("level") or "") if n else ""

    def parent_id_of(did: str) -> Optional[str]:
        n = meta(did) or text_node(did)
        return n.get("parent_id") if n else None

    def has_subitems(iid: str) -> bool:
        # iid 아래 subitem이 하나라도(그리고 indexable) 있으면 True
        i_child = children.get(iid, [])
        for cid in i_child:
            if level_of(cid) == "subitem" and ((not SKIP_NON_INDEXABLE) or ok(cid)):
                return True
        return False

    chunks: List[Dict[str, Any]] = []

    def emit(unit_id: str, unit_level: str, index_text: str, node_refs: List[str], ref_node: Dict[str, Any]):
        if not index_text.strip():
            return
        chunks.append({
            "unit_id": unit_id,
            "law_id": ref_node.get("law_id"),
            "law_name": ref_node.get("law_name"),
            "unit_level": unit_level,
            "path": ref_node.get("path"),
            "article_no": ref_node.get("article_no"),
            "paragraph_no": ref_node.get("paragraph_no"),
            "item_no": ref_node.get("item_no"),
            "subitem_no": ref_node.get("subitem_no"),
            "index_text": index_text,
            "node_refs": node_refs,
            "source_type": "statute",
        })

    # ---------- 루트 article doc_id 수집 ----------
    root_articles = []
    for did, cand in by_id.items():
        if any((c.get("level") == "article" and c.get("parent_id") is None) for c in cand):
            root_articles.append(did)
    root_articles = sorted(set(root_articles))

    # ---------- helper: 부모 아래 I들 처리 (부모는 A 또는 P 가능) ----------
    def handle_items_under_parent(parent_id: str):
        """
        parent_id 아래 item(I)들이 있는 경우 처리.
        - I 중 M이 달린 I가 있으면: 전체 병합 금지, I별로 (prefix=parent) + I + M*
        - 모두 M이 없으면: MERGE_ITEMS_UNDER_PARENT에 따라 (auto면 list frame일 때만) parent+I들을 병합하거나 I별 처리
        """
        parent_meta = meta(parent_id)
        if not parent_meta:
            return

        if SKIP_NON_INDEXABLE and not ok(parent_id):
            return

        parent_text = text_of(parent_id)

        # item 자식 수집
        child_ids = children.get(parent_id, [])
        item_ids = [cid for cid in child_ids if level_of(cid) == "item"]
        if not item_ids:
            return

        # indexable item만
        item_ids_ok = [iid for iid in item_ids if (not SKIP_NON_INDEXABLE) or ok(iid)]
        if not item_ids_ok:
            return

        # M이 달린 I가 하나라도 있으면 => 강제 분리(I 단위)
        any_item_has_m = any(has_subitems(iid) for iid in item_ids_ok)

        # ---- Case 1) 목이 있는 I가 존재 => I별 분리, prefix는 parent를 "항상" 붙임 ----
        if any_item_has_m:
            for iid in item_ids_ok:
                i_meta = meta(iid)
                if not i_meta:
                    continue

                i_text = text_of(iid)
                refs = [iid]

                # I 아래 M 병합
                if MERGE_SUBITEMS_UNDER_ITEM:
                    i_child = children.get(iid, [])
                    sub_ids = [cid for cid in i_child if level_of(cid) == "subitem" and ((not SKIP_NON_INDEXABLE) or ok(cid))]
                    if sub_ids:
                        sub_txts = [text_of(mid).strip() for mid in sub_ids if text_of(mid).strip()]
                        if sub_txts:
                            i_text = i_text + "\n" + "\n".join(sub_txts)
                            refs = [iid] + sub_ids

                # ✅ 이 케이스에서는 parent prefix를 항상 붙임(검색 안정성)
                idx = parent_text.strip() + "\n" + i_text.strip() if parent_text.strip() else i_text.strip()
                refs = [parent_id] + refs

                emit(iid, "item", idx, refs, i_meta)
            return

        # ---- Case 2) 목이 없는 I들만 존재 => parent+I 전체 병합을 고려(옵션) ----
        do_merge = False
        if MERGE_ITEMS_UNDER_PARENT == "never":
            do_merge = False
        else:  # auto
            do_merge = (len(item_ids_ok) >= 2 and is_list_frame(parent_text))

        if do_merge:
            merged_lines = [parent_text]
            merged_refs = [parent_id]
            for iid in item_ids_ok:
                it = text_of(iid).strip()
                if it:
                    merged_lines.append(it)
                    merged_refs.append(iid)
            merged_text = "\n".join([x for x in merged_lines if x.strip()])

            if len(merged_text) <= PARENT_ITEM_MERGE_MAX_CHARS:
                emit(parent_id, level_of(parent_id), merged_text, merged_refs, parent_meta)
                return
            # 길면 병합 포기하고 개별로 fallthrough

        # 개별 I 처리(conditional prefix)
        for iid in item_ids_ok:
            i_meta = meta(iid)
            if not i_meta:
                continue
            leaf = text_of(iid)
            refs = [iid]
            idx, used = maybe_prefix(parent_text, leaf, mode=PREFIX_MODE)
            if used:
                refs = [parent_id] + refs
            emit(iid, "item", idx, refs, i_meta)

    # ---------- helper: 부모 아래 M들 처리 (부모는 A 또는 P 가능) ----------
    def handle_subitems_under_parent(parent_id: str):
        parent_meta = meta(parent_id)
        if not parent_meta:
            return
        if SKIP_NON_INDEXABLE and not ok(parent_id):
            return
        parent_text = text_of(parent_id)

        child_ids = children.get(parent_id, [])
        sub_ids = [cid for cid in child_ids if level_of(cid) == "subitem"]
        if not sub_ids:
            return

        for mid in sub_ids:
            if SKIP_NON_INDEXABLE and not ok(mid):
                continue
            m_meta = meta(mid)
            if not m_meta:
                continue

            m_text = text_of(mid)
            # 목은 대체로 맥락이 약하니 conditional prefix가 사실상 자주 붙음
            idx, used = maybe_prefix(parent_text, m_text, mode=PREFIX_MODE)
            refs = ([parent_id, mid] if used else [mid])

            emit(mid, "subitem", idx, refs, m_meta)

    # ---------- 메인: article에서 내려가며 처리 ----------
    for aid in root_articles:
        a_meta = meta(aid)
        if not a_meta:
            continue

        child_ids = children.get(aid, [])

        # A leaf
        if not child_ids:
            if (not SKIP_NON_INDEXABLE) or ok(aid):
                emit(aid, "article", text_of(aid), [aid], a_meta)
            continue

        # A 아래 paragraph가 있으면 paragraph 단위로 처리 (그 아래에서 item/subitem 분기)
        para_ids = [cid for cid in child_ids if level_of(cid) == "paragraph"]
        if para_ids:
            for pid in para_ids:
                p_meta = meta(pid)
                if not p_meta:
                    continue
                if SKIP_NON_INDEXABLE and not ok(pid):
                    continue

                p_child = children.get(pid, [])
                p_item_ids = [cid for cid in p_child if level_of(cid) == "item"]
                p_sub_ids  = [cid for cid in p_child if level_of(cid) == "subitem"]

                # P leaf
                if not p_item_ids and not p_sub_ids:
                    emit(pid, "paragraph", text_of(pid), [pid], p_meta)
                    continue

                # P 아래 item이 있으면 "부모=pid"로 item 처리(여기서 A-P-I 및 A-P-I-M 모두 처리됨)
                if p_item_ids:
                    handle_items_under_parent(pid)

                # P 아래 subitem이 있으면 (A-P-M)
                if p_sub_ids:
                    handle_subitems_under_parent(pid)

            continue

        # A 아래 바로 item이 있으면 (A-I 또는 A-I-M)
        item_ids = [cid for cid in child_ids if level_of(cid) == "item"]
        if item_ids:
            handle_items_under_parent(aid)
            # A 아래 subitem도 동시에 있을 수 있으니(드물지만) 같이 처리
            sub_ids = [cid for cid in child_ids if level_of(cid) == "subitem"]
            if sub_ids:
                handle_subitems_under_parent(aid)
            continue

        # A 아래 바로 subitem이 있으면 (A-M)
        sub_ids = [cid for cid in child_ids if level_of(cid) == "subitem"]
        if sub_ids:
            handle_subitems_under_parent(aid)
            continue

    return chunks


# =========================================================
# 5) 실행
# =========================================================
def load_need_laws(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

need_laws = load_need_laws(NEED_LAWS_JSON)
law_codes = list(need_laws.values())

print(f"[need_laws] {len(need_laws)} laws loaded")
# print(law_codes)  # 필요하면 주석 해제

for code in law_codes:
    in_path = os.path.join(IN_DIR, f"{code}{INPUT_SUFFIX}")
    if not os.path.exists(in_path):
        in_path = os.path.join(IN_DIR, f"{code}.jsonl")

    if not os.path.exists(in_path):
        print(f"[SKIP] {code}: input not found ({in_path})")
        continue

    rows = read_jsonl(in_path)
    if not rows:
        print(f"[SKIP] {code}: empty ({in_path})")
        continue

    chunks = chunk(rows)

    out_path = os.path.join(OUT_DIR, f"{code}_chunks.jsonl")
    write_jsonl(out_path, chunks)

    by_level = defaultdict(int)
    for c in chunks:
        by_level[c["unit_level"]] += 1

    # 한글명도 같이 보여주기(가독성)
    name_ko = next((k for k,v in need_laws.items() if v == code), "")
    header = f"{name_ko} ({code})" if name_ko else code

    print(f"=== {header} ===")
    print(f"source rows: {len(rows)}")
    print(f"chunk rows : {len(chunks)}")
    print("by level  :", dict(by_level))
    print(f"saved     : {os.path.abspath(out_path)}")
