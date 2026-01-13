import json
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# =========================
# Paths
# =========================
DATA_DIR = Path("./data")

# year: 1900~2099
YEAR_RE = re.compile(r"(19\d{2}|20\d{2})")

# month/day patterns (loose)
YM_DOT_RE = re.compile(r"(?P<y>19\d{2}|20\d{2})\s*[.\-/년]\s*(?P<m>\d{1,2})\s*(?:[.\-/월]\s*(?P<d>\d{1,2}))?")
YM_WORD_RE = re.compile(r"(?P<y>19\d{2}|20\d{2})\s*년\s*(?P<m>\d{1,2})\s*월")


def now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_str(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, (dict, list)):
        return json.dumps(x, ensure_ascii=False)
    return str(x)


def as_int(x: Any) -> Optional[int]:
    s = safe_str(x).strip()
    if not s:
        return None
    try:
        return int(re.sub(r"[^\d]", "", s))
    except Exception:
        return None


def ensure_metadata(rec: Dict[str, Any]) -> Dict[str, Any]:
    md = rec.get("metadata") or {}
    return md if isinstance(md, dict) else {}


def normalize_url_into_metadata(rec: Dict[str, Any], md: Dict[str, Any]) -> Dict[str, Any]:
    url = safe_str(rec.get("url")).strip() or safe_str(md.get("url")).strip()
    if url:
        md["url"] = url
    return md


def normalize_views(md: Dict[str, Any]) -> Dict[str, Any]:
    # views can come from md["views"] or md["views_list"] etc.
    v = md.get("views")
    if v is None and "views_list" in md:
        v = md.get("views_list")
    vi = as_int(v)
    if vi is not None:
        md["views"] = vi
    return md


def normalize_category_path(rec: Dict[str, Any], md: Dict[str, Any]) -> Tuple[List[str], Optional[str]]:
    """
    우선순위:
    1) metadata.field/item (있으면 가장 신뢰)
    2) rec.category_path(list)
    3) rec.category(str "A > B")
    return: (category_path, category_raw)
    """
    field = safe_str(md.get("field")).strip()
    item = safe_str(md.get("item")).strip()
    if field and item:
        return [field, item], f"{field} > {item}"

    cp = rec.get("category_path")
    if isinstance(cp, list):
        parts = [safe_str(x).strip() for x in cp if safe_str(x).strip()]
        raw = " > ".join(parts) if parts else None
        return parts, raw

    cat = safe_str(rec.get("category")).strip()
    if cat:
        # allow "A > B" or "A/B"
        if ">" in cat:
            parts = [p.strip() for p in cat.split(">") if p.strip()]
            return parts, cat
        if "/" in cat:
            parts = [p.strip() for p in cat.split("/") if p.strip()]
            return parts, cat
        return [cat], cat

    return [], None


def infer_doc_type(rec: Dict[str, Any], md: Dict[str, Any]) -> str:
    """
    표준 doc_type(서비스 내부용)로 맞춤.
    우선순위: metadata.doc_type -> url 패턴 -> source 키워드
    """
    dt_raw = safe_str(md.get("doc_type")).strip()
    url = safe_str(md.get("url")).strip()

    # 1) metadata 기반 매핑 (가능하면 이게 가장 정확)
    if dt_raw:
        # 너희 팀에서 쓰는 표준명을 여기서 통일
        if dt_raw in ("consumer_counsel_case", "consumer_cnslt_case", "consumer_counsel"):
            return "consumer_counsel_case"
        if "dmgerlifcase" in dt_raw or "relief" in dt_raw:
            return "consumer_relief_case"
        if "mediation" in dt_raw or "odr" in dt_raw:
            return "mediation_case"
        if "law" in dt_raw or "regulation" in dt_raw:
            return "law"
        # 이미 표준이면 그대로
        return dt_raw

    # 2) url 기반
    if "cnsltcase/114" in url or "selectCnsltCaseView" in url:
        return "consumer_counsel_case"
    if "dmgerlifcase" in url:
        return "consumer_relief_case"

    # 3) source fallback
    source = safe_str(rec.get("source") or md.get("source_list")).lower()
    if "상담" in source:
        return "consumer_counsel_case"
    if "피해" in source or "피해구제" in source:
        return "consumer_relief_case"
    if "조정" in source:
        return "mediation_case"
    if "법" in source or "law" in source:
        return "law"
    return "unknown"


def build_text_for_embedding(rec: Dict[str, Any], doc_type: str, category_raw: Optional[str]) -> str:
    title = safe_str(rec.get("title")).strip()
    source = safe_str(rec.get("source")).strip()

    question = safe_str(rec.get("question")).strip()
    answer = safe_str(rec.get("answer")).strip()
    body = safe_str(rec.get("content") or rec.get("body") or rec.get("text")).strip()

    header = []
    if doc_type:
        header.append(f"[문서유형] {doc_type}")
    if title:
        header.append(f"[제목] {title}")
    if source:
        header.append(f"[출처] {source}")
    if category_raw:
        header.append(f"[분류] {category_raw}")

    main = []
    # 상담/QA 문서는 question+answer가 핵심
    if question:
        main.append("[질문]\n" + question)
    if answer:
        main.append("[답변]\n" + answer)
    # 둘 다 없으면 본문
    if not main and body:
        main.append("[본문]\n" + body)

    return ("\n".join(header) + "\n\n" + "\n\n".join(main)).strip()


def extract_years(text: str) -> List[int]:
    years = [int(y) for y in YEAR_RE.findall(text)]
    return sorted(set(years))


def extract_raw_date_text(text: str, max_len: int = 120) -> Optional[str]:
    """
    룰 개선/검증용: 본문에서 날짜 표현을 '짧게' 남김.
    - 너무 길게 저장하지 않도록 1~2개만 캡처
    """
    if not text:
        return None
    hits = []
    for m in YM_DOT_RE.finditer(text):
        hits.append(m.group(0).strip())
        if len(hits) >= 2:
            break
    if not hits:
        for m in YM_WORD_RE.finditer(text):
            hits.append(m.group(0).strip())
            if len(hits) >= 2:
                break
    if not hits:
        return None
    s = ", ".join(hits)
    return s[:max_len]


def pick_event_year(doc_type: str, years: List[int], text: str) -> Optional[int]:
    """
    대표 연도 규칙 (doc_type별)
    - counsel: 최신 연도
    - mediation: '결정/결론' 근처 연도 우선 시도, 실패하면 최신
    - law: '시행/개정' 근처 연도 우선 시도, 실패하면 None(오염 방지)
    """
    if not years:
        return None

    if doc_type == "consumer_counsel_case":
        return years[-1]

    if doc_type == "mediation_case":
        # 결론 키워드 근처에서 연도 찾기 (아주 보수적으로)
        tail = text[-1500:] if text else ""
        if any(k in tail for k in ["결정", "결론", "조정", "결정사항"]):
            tail_years = extract_years(tail)
            if tail_years:
                return tail_years[-1]
        return years[-1]

    if doc_type == "law":
        # 법령은 예시연도(2007 등)가 섞일 수 있어 최신 연도를 대표로 잡으면 오염될 수 있음
        # 시행/개정 근처에서만 뽑고, 없으면 None
        if text:
            window = []
            for kw in ["시행", "개정", "공포", "제정"]:
                idx = text.find(kw)
                if idx != -1:
                    seg = text[max(0, idx - 200): idx + 200]
                    window.extend(extract_years(seg))
            window = sorted(set(window))
            if window:
                return window[-1]
        return None

    # default: 최신
    return years[-1]


def build_time_note(years: List[int], chosen: Optional[int]) -> Optional[str]:
    if not years:
        return "연도 정보 없음"
    if chosen is None:
        return "대표 연도 미확정"
    if len(years) == 1:
        return None
    return f"복수 연도 존재: {years} / 대표값={chosen}"


# 이벤트는 "정확도 우선": 문장 안에 키워드 + 연도가 같이 있을 때만 뽑는다(보수적)
EVENT_RULES = [
    ("purchase_or_signup", [r"구매", r"구입", r"계약", r"가입", r"결제"]),
    ("delivery_or_install", [r"배송", r"설치", r"개통", r"이전설치", r"방문\s*설치"]),
    ("defect_found", [r"하자", r"불량", r"고장", r"파손", r"오류", r"불편"]),
    ("repair_or_service", [r"수리", r"as", r"A/S", r"점검", r"교체"]),
    ("cancel_or_refund_request", [r"해지", r"환불", r"취소", r"반품", r"위약금"]),
    ("move_or_relocate", [r"이사", r"이전", r"전출", r"전입", r"주소\s*변경"]),
    ("dispute_raised", [r"분쟁", r"민원", r"신고", r"조정", r"피해구제", r"상담\s*신청"]),
    ("decision_or_result", [r"결정", r"조정\s*성립", r"조정\s*불성립", r"합의", r"결론", r"결과"]),
]


def split_sentences(text: str) -> List[str]:
    # 아주 단순 split (한국어 문장/불릿 섞인 데이터용)
    if not text:
        return []
    parts = re.split(r"[\n\r]+|(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p and p.strip()]


def extract_events_conservative(text: str) -> List[Dict[str, Any]]:
    """
    - 문장 단위로: (키워드 매칭) AND (해당 문장에 연도 존재) 할 때만 이벤트 생성
    - date는 year만 우선 (월까지 있으면 ym로 저장)
    """
    out: List[Dict[str, Any]] = []
    for sent in split_sentences(text):
        sent_years = extract_years(sent)
        if not sent_years:
            continue
        # ym raw도 같이 남겨두면 나중에 개선 쉬움
        raw_dt = extract_raw_date_text(sent, max_len=60)
        y = sent_years[-1]
        for ev_type, patterns in EVENT_RULES:
            if any(re.search(p, sent, flags=re.IGNORECASE) for p in patterns):
                out.append({
                    "type": ev_type,
                    "year": y,
                    "original_text": sent[:180],
                    "raw_date_text": raw_dt,
                    "source": "rule",
                    "confidence": 0.9
                })
                break
        if len(out) >= 6:
            break
    return out


def make_doc_id(md: Dict[str, Any], doc_type: str) -> str:
    """
    100점 핵심: 결정적 키 우선
    - site + raw_doc_type + sn(case_sn 등) 있으면 그걸로 doc_id 생성
    - 없으면 url 해시 fallback
    """
    site = safe_str(md.get("site")).strip() or "unknown_site"
    raw_doc_type = safe_str(md.get("doc_type")).strip() or doc_type
    sn = safe_str(md.get("case_sn") or md.get("sn") or md.get("raw_id") or md.get("id")).strip()

    if site and raw_doc_type and sn:
        return f"{site}:{raw_doc_type}:{sn}"

    url = safe_str(md.get("url")).strip()
    base = f"{site}|{raw_doc_type}|{url}|{doc_type}".strip()
    h = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
    return f"{doc_type}:{h}"


def content_hash_from_embedding_text(text_for_embedding: str) -> str:
    # 중복/변경 감지용
    h = hashlib.sha1(text_for_embedding.encode("utf-8")).hexdigest()
    return h


def canonicalize(rec: Dict[str, Any]) -> Dict[str, Any]:
    md = ensure_metadata(rec)
    md = normalize_url_into_metadata(rec, md)
    md = normalize_views(md)

    # site/source 보강
    site = safe_str(md.get("site")).strip()
    if site:
        md["site"] = site

    # doc_type 결정
    doc_type = infer_doc_type(rec, md)

    # category 정규화
    category_path, category_raw = normalize_category_path(rec, md)

    # 기본 필드
    title = safe_str(rec.get("title")).strip() or None
    source = safe_str(rec.get("source")).strip() or safe_str(md.get("source_list")).strip() or None

    collected_at = safe_str(rec.get("collected_at")).strip() or now_iso_utc()

    # embedding text
    text_for_embedding = safe_str(rec.get("text_for_embedding")).strip()
    if not text_for_embedding:
        text_for_embedding = build_text_for_embedding(rec, doc_type, category_raw)

    years = extract_years(text_for_embedding)
    raw_date_text = safe_str(rec.get("raw_date_text")).strip() or extract_raw_date_text(text_for_embedding)

    # event_year: doc_type별
    event_year = rec.get("event_year")
    if event_year is None:
        event_year = pick_event_year(doc_type, years, text_for_embedding)
    else:
        try:
            event_year = int(event_year)
        except Exception:
            event_year = pick_event_year(doc_type, years, text_for_embedding)

    time_note = rec.get("time_note")
    if time_note is None:
        time_note = build_time_note(years, event_year)

    # events: 옵션 + 보수적 추출
    events = rec.get("events")
    if events is None:
        # 연도 2개 이상이면서, 문장 레벨로 확실할 때만
        events = extract_events_conservative(text_for_embedding) if len(years) >= 2 else []

    # doc_id 결정
    doc_id = safe_str(rec.get("doc_id")).strip() or make_doc_id(md, doc_type)

    # url: processed에서는 metadata.url만 single source of truth
    # top-level url은 제거(원하면 유지해도 되지만 통일이 더 좋음)
    # 여기서는 아예 출력에 넣지 않음.

    # content_hash
    c_hash = content_hash_from_embedding_text(text_for_embedding)

    # metadata 보강
    md["doc_type_std"] = doc_type
    if category_raw:
        md["category_raw"] = category_raw
    if category_path:
        md["category_path"] = category_path
    md["taxonomy_version"] = md.get("taxonomy_version") or "v1"

    return {
        "doc_id": doc_id,
        "doc_type": doc_type,
        "title": title,
        "category_path": category_path,
        "source": source,
        "collected_at": collected_at,
        "event_year": event_year,
        "time_note": time_note,
        "raw_date_text": raw_date_text,
        "text_for_embedding": text_for_embedding,
        "events": events,
        "content_hash": c_hash,
        "metadata": md,
    }


def iter_target_jsonl_files() -> List[Path]:
    """
    data/*/*.jsonl
    - processed 폴더 제외
    - *_errors.jsonl 제외
    """
    files: List[Path] = []
    for p in DATA_DIR.glob("*/*.jsonl"):
        if "processed" in p.parts:
            continue
        if p.name.endswith("_errors.jsonl") or "errors" in p.name:
            continue
        files.append(p)
    return sorted(files)


def process_file(in_path: Path) -> None:
    out_dir = in_path.parent / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{in_path.stem}.processed.jsonl"

    n_in = n_ok = n_err = 0
    with in_path.open("r", encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
        for line_no, line in enumerate(fin, start=1):
            line = line.strip()
            if not line:
                continue
            n_in += 1
            try:
                rec = json.loads(line)
                if not isinstance(rec, dict):
                    raise ValueError("record is not dict")
                canon = canonicalize(rec)
                fout.write(json.dumps(canon, ensure_ascii=False) + "\n")
                n_ok += 1
            except Exception:
                n_err += 1
                continue

    print(f"[DONE] {in_path} -> {out_path} | in={n_in} ok={n_ok} err={n_err}")


def main():
    targets = iter_target_jsonl_files()
    if not targets:
        print(f"[WARN] No jsonl found in {DATA_DIR.resolve()} (pattern: data/*/*.jsonl)")
        return
    for fp in targets:
        process_file(fp)


if __name__ == "__main__":
    main()
