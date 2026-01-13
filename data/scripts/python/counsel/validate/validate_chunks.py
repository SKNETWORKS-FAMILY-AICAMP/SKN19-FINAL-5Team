# scripts/preprocess/validate/validate_chunks.py
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional


BASE_DIR = Path(__file__).resolve().parents[3]  # -> ism/

# ✅ 네 프로젝트 폴더 구조에 맞춰 "chunks" 경로만 맞춰주면 됨
CHUNK_FILES = [
    BASE_DIR / "data" / "cnslt" / "chunks" / "cnslt_cases_114_chunks_v2.jsonl",
    BASE_DIR / "data" / "dmge_rlif" / "chunks" / "dmge_rlif_cases_115_chunks_v2.jsonl",
    BASE_DIR / "data" / "trubl_mdat" / "chunks" / "trubl_mdat_cases_116_chunks_v2.jsonl",
    BASE_DIR / "data" / "kca_00000006" / "chunks" / "kca_00000006_chunks_v2.jsonl",
]

# ✅ 116 같은 긴 문서에서 권장: 헤더가 text 맨 위에 있는지 체크하고 싶으면 True
CHECK_HEADER_PREFIX = True
HEADER_MARKERS = ["[문서유형]", "[제목]", "[분류]"]  # 너 포맷 기준


@dataclass
class FileStats:
    path: Path
    chunk_count: int = 0
    dup_chunk_id: int = 0
    empty_text: int = 0
    missing_doc_id: int = 0
    missing_chunk_index: int = 0
    missing_chunk_total: int = 0
    len_min: int = 0
    len_p50: int = 0
    len_p90: int = 0
    len_max: int = 0
    doc_type_counts: Dict[str, int] = None
    suspicious_docs: int = 0
    header_missing_chunks: int = 0


def percentile(sorted_list: List[int], p: float) -> int:
    if not sorted_list:
        return 0
    idx = int(len(sorted_list) * p) - 1
    idx = max(0, min(idx, len(sorted_list) - 1))
    return sorted_list[idx]


def has_header(text: str) -> bool:
    # ✅ 세 마커 중 2개 이상 있으면 "헤더 있다"로 판단(너무 빡세게 하면 116 섹션 청크에 걸릴 수 있어서)
    hit = sum(1 for m in HEADER_MARKERS if m in text[:300])
    return hit >= 2


def validate_one_file(path: Path) -> FileStats:
    st = FileStats(path=path, doc_type_counts=Counter())
    if not path.exists():
        print(f"[SKIP] not found: {path}")
        return st

    seen_chunk_ids = set()
    lengths: List[int] = []
    by_doc: Dict[str, List[Tuple[int, int]]] = defaultdict(list)

    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            st.chunk_count += 1
            try:
                obj = json.loads(line)
            except Exception as e:
                print(f"[ERROR] JSON parse failed at {path}:{line_no} ({e})")
                continue

            chunk_id = obj.get("chunk_id")
            doc_id = obj.get("doc_id")
            text = (obj.get("text") or "").strip()
            cidx = obj.get("chunk_index")
            ctot = obj.get("chunk_total")
            dtype = obj.get("doc_type") or ""

            st.doc_type_counts[dtype] += 1

            if chunk_id:
                if chunk_id in seen_chunk_ids:
                    st.dup_chunk_id += 1
                else:
                    seen_chunk_ids.add(chunk_id)

            if not text:
                st.empty_text += 1
            else:
                lengths.append(len(text))

            if not doc_id:
                st.missing_doc_id += 1
            if not isinstance(cidx, int):
                st.missing_chunk_index += 1
            if not isinstance(ctot, int):
                st.missing_chunk_total += 1

            if doc_id and isinstance(cidx, int) and isinstance(ctot, int):
                by_doc[doc_id].append((cidx, ctot))

            if CHECK_HEADER_PREFIX and text:
                if not has_header(text):
                    st.header_missing_chunks += 1

    if lengths:
        lengths.sort()
        st.len_min = lengths[0]
        st.len_max = lengths[-1]
        st.len_p50 = lengths[len(lengths) // 2]
        st.len_p90 = percentile(lengths, 0.90)

    # ✅ doc_id별 연속성/총합 체크
    suspicious = 0
    for doc_id, items in by_doc.items():
        items.sort(key=lambda x: x[0])
        idxs = [i for i, _ in items]
        totals = [t for _, t in items]
        # chunk_total이 doc_id 내에서 동일해야 함
        if len(set(totals)) != 1:
            suspicious += 1
            continue
        # chunk_index 연속(0..total-1)인지 체크
        total = totals[0]
        if idxs != list(range(0, total)):
            suspicious += 1

    st.suspicious_docs = suspicious
    return st


def print_report(st: FileStats) -> None:
    print("\n" + "=" * 80)
    print(f"[FILE] {st.path}")
    print(f"[COUNT] chunks={st.chunk_count}")
    print(f"[DUP] chunk_id duplicates={st.dup_chunk_id}")
    print(f"[EMPTY] empty_text={st.empty_text}")
    print(f"[MISSING] doc_id={st.missing_doc_id} chunk_index={st.missing_chunk_index} chunk_total={st.missing_chunk_total}")
    print(f"[LEN] min={st.len_min} p50={st.len_p50} p90={st.len_p90} max={st.len_max}")
    print(f"[DOC_TYPE] {dict(st.doc_type_counts)}")
    print(f"[DOC_CHECK] suspicious_docs={st.suspicious_docs}")
    if CHECK_HEADER_PREFIX:
        print(f"[HEADER] chunks_missing_header={st.header_missing_chunks}")
    print("=" * 80)


def main():
    any_found = False
    for p in CHUNK_FILES:
        st = validate_one_file(p)
        if st.chunk_count > 0:
            any_found = True
        print_report(st)

    if not any_found:
        print("\n[INFO] No chunk files found. Check CHUNK_FILES paths.\n")


if __name__ == "__main__":
    main()
