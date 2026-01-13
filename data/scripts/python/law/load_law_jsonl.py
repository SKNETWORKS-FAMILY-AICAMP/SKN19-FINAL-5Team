import os
import json
from typing import Any, Dict, Iterable, List, Optional
from datetime import date
from dotenv import load_dotenv

load_dotenv()

import psycopg


def conninfo_from_env() -> str:
    return (
        f"host={os.environ.get('PGHOST','localhost')} "
        f"port={os.environ.get('PGPORT','5433')} "
        f"dbname={os.environ.get('PGDATABASE','postgres')} "
        f"user={os.environ.get('PGUSER','postgres')} "
        f"password={os.environ.get('PGPASSWORD','postgres')}"
    )


DDL_SQL = """
CREATE TABLE IF NOT EXISTS laws (
  law_id              TEXT PRIMARY KEY,
  law_name            TEXT NOT NULL,
  law_type            TEXT,
  ministry            TEXT,
  promulgation_date   DATE,
  enforcement_date    DATE,
  revision_type       TEXT,
  domain              TEXT
);

CREATE TABLE IF NOT EXISTS law_units (
  doc_id                 TEXT PRIMARY KEY,
  law_id                 TEXT NOT NULL REFERENCES laws(law_id) ON DELETE CASCADE,
  parent_id              TEXT,

  level                  TEXT NOT NULL,
  is_indexable           BOOLEAN NOT NULL DEFAULT TRUE,

  article_no             TEXT,
  article_title          TEXT,
  paragraph_no           TEXT,
  item_no                TEXT,
  subitem_no             TEXT,

  path                   TEXT,
  text                   TEXT NOT NULL,
  amendment_note         TEXT,

  ref_citations_internal JSONB NOT NULL DEFAULT '[]'::jsonb,
  ref_citations_external JSONB NOT NULL DEFAULT '[]'::jsonb,
  mentioned_laws         JSONB NOT NULL DEFAULT '[]'::jsonb
);

-- indexes (권장)
CREATE INDEX IF NOT EXISTS idx_law_units_law_id ON law_units(law_id);
CREATE INDEX IF NOT EXISTS idx_law_units_parent_id ON law_units(parent_id);
CREATE INDEX IF NOT EXISTS idx_law_units_level ON law_units(level);
CREATE INDEX IF NOT EXISTS idx_law_units_is_indexable ON law_units(is_indexable);
"""


UPSERT_LAW_SQL = """
INSERT INTO laws (
  law_id, law_name, law_type, ministry,
  promulgation_date, enforcement_date, revision_type,
  domain
) VALUES (
  %(law_id)s, %(law_name)s, %(law_type)s, %(ministry)s,
  %(promulgation_date)s, %(enforcement_date)s, %(revision_type)s,
  %(domain)s
)
ON CONFLICT (law_id) DO UPDATE SET
  law_name=EXCLUDED.law_name,
  law_type=COALESCE(EXCLUDED.law_type, laws.law_type),
  ministry=COALESCE(EXCLUDED.ministry, laws.ministry),
  promulgation_date=COALESCE(EXCLUDED.promulgation_date, laws.promulgation_date),
  enforcement_date=COALESCE(EXCLUDED.enforcement_date, laws.enforcement_date),
  revision_type=COALESCE(EXCLUDED.revision_type, laws.revision_type),
  domain=COALESCE(EXCLUDED.domain, laws.domain);
"""


UPSERT_UNIT_SQL = """
INSERT INTO law_units (
  doc_id, law_id, parent_id,
  level, is_indexable,
  article_no, article_title, paragraph_no, item_no, subitem_no,
  path, text, amendment_note,
  ref_citations_internal, ref_citations_external, mentioned_laws
) VALUES (
  %(doc_id)s, %(law_id)s, %(parent_id)s,
  %(level)s, %(is_indexable)s,
  %(article_no)s, %(article_title)s, %(paragraph_no)s, %(item_no)s, %(subitem_no)s,
  %(path)s, %(text)s, %(amendment_note)s,
  %(ref_citations_internal)s::jsonb, %(ref_citations_external)s::jsonb, %(mentioned_laws)s::jsonb
)
ON CONFLICT (doc_id) DO UPDATE SET
  law_id=EXCLUDED.law_id,
  parent_id=EXCLUDED.parent_id,
  level=EXCLUDED.level,
  is_indexable=EXCLUDED.is_indexable,
  article_no=EXCLUDED.article_no,
  article_title=EXCLUDED.article_title,
  paragraph_no=EXCLUDED.paragraph_no,
  item_no=EXCLUDED.item_no,
  subitem_no=EXCLUDED.subitem_no,
  path=EXCLUDED.path,
  text=EXCLUDED.text,
  amendment_note=EXCLUDED.amendment_note,
  ref_citations_internal=EXCLUDED.ref_citations_internal,
  ref_citations_external=EXCLUDED.ref_citations_external,
  mentioned_laws=EXCLUDED.mentioned_laws;
"""


def ensure_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(DDL_SQL)
    conn.commit()


def iter_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"JSON decode error at {path}:{line_no}: {e}") from e


def _json_dumps(v: Any) -> str:
    return json.dumps(v if v is not None else [], ensure_ascii=False)


def parse_yyyymmdd_to_date(s: Optional[str]) -> Optional[date]:
    """
    JSONL의 날짜 문자열이 '20260102' 형태로 들어옴.
    - None/빈값이면 None
    - 길이/형식 이상하면 ValueError
    """
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    if len(s) != 8 or not s.isdigit():
        raise ValueError(f"Invalid YYYYMMDD date string: {s}")
    y = int(s[0:4])
    m = int(s[4:6])
    d = int(s[6:8])
    return date(y, m, d)


def extract_law_row(row: Dict[str, Any]) -> Dict[str, Any]:
    eff = row.get("effective") or {}
    return {
        "law_id": (row.get("law_id") or "").strip(),
        "law_name": (row.get("law_name") or "").strip(),
        "law_type": row.get("law_type"),
        "ministry": row.get("ministry"),
        "promulgation_date": parse_yyyymmdd_to_date(eff.get("promulgation_date")),
        "enforcement_date": parse_yyyymmdd_to_date(eff.get("enforcement_date")),
        "revision_type": eff.get("revision_type"),
        "domain": row.get("domain"),
    }


def extract_unit_row(row: Dict[str, Any]) -> Dict[str, Any]:
    # item_no/subitem_no가 숫자로 들어올 수도 있어서 TEXT로 저장하려면 str로 정규화하는 게 안전
    def to_text_or_none(x: Any) -> Optional[str]:
        if x is None:
            return None
        s = str(x).strip()
        return s if s else None

    return {
        "doc_id": row.get("doc_id"),
        "law_id": row.get("law_id"),
        "parent_id": row.get("parent_id"),

        "level": row.get("level") or "",
        "is_indexable": bool(row.get("is_indexable", True)),

        "article_no": row.get("article_no"),
        "article_title": row.get("article_title"),
        "paragraph_no": to_text_or_none(row.get("paragraph_no")),
        "item_no": to_text_or_none(row.get("item_no")),
        "subitem_no": to_text_or_none(row.get("subitem_no")),

        "path": row.get("path"),
        "text": row.get("text") or "",
        "amendment_note": row.get("amendment_note"),

        "ref_citations_internal": _json_dumps(row.get("ref_citations_internal") or []),
        "ref_citations_external": _json_dumps(row.get("ref_citations_external") or []),
        "mentioned_laws": _json_dumps(row.get("mentioned_laws") or []),
    }


def load_law_jsonl_to_db(jsonl_paths: List[str], *, batch_size: int = 2000) -> None:
    """
    jsonl_paths: 법령 jsonl 파일 경로 리스트 (예: 11개)
    """
    conninfo = conninfo_from_env()

    with psycopg.connect(conninfo) as conn:
        ensure_schema(conn)

        with conn.cursor() as cur:
            law_seen_global: set[str] = set()
            unit_buffer: List[Dict[str, Any]] = []

            for jsonl_path in jsonl_paths:
                for row in iter_jsonl(jsonl_path):
                    # 1) laws upsert
                    law_row = extract_law_row(row)
                    law_id = law_row["law_id"]
                    if not law_id:
                        continue

                    # 같은 세션에서 law_id는 한 번만 upsert해도 충분(다른 파일에도 중복 등장할 수 있음)
                    if law_id not in law_seen_global:
                        cur.execute(UPSERT_LAW_SQL, law_row)
                        law_seen_global.add(law_id)

                    # 2) law_units upsert (batch)
                    unit_row = extract_unit_row(row)
                    if not unit_row["doc_id"]:
                        continue
                    unit_buffer.append(unit_row)

                    if len(unit_buffer) >= batch_size:
                        cur.executemany(UPSERT_UNIT_SQL, unit_buffer)
                        unit_buffer.clear()

            # flush
            if unit_buffer:
                cur.executemany(UPSERT_UNIT_SQL, unit_buffer)

        conn.commit()


if __name__ == "__main__":
    import json
    from pathlib import Path

    # 프로젝트 기준 경로 (필요하면 여기만 바꾸면 됨)
    need_laws_path = Path("../data/need_laws.json")
    jsonl_dir = Path("../data/law_jsonldata")

    # need_laws.json 로드: {"민법": "Civil_Law", ...}
    with need_laws_path.open("r", encoding="utf-8") as f:
        need_laws = json.load(f)

    # value들로 jsonl 경로 생성
    # 예: "../data/law_jsonldata/Civil_Law.jsonl"
    paths = [str(jsonl_dir / f"{code}.jsonl") for code in need_laws.values()]

    # (선택) 파일 존재 여부 체크: 없으면 즉시 에러로 알려줌
    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        raise FileNotFoundError("다음 jsonl 파일이 없습니다:\n" + "\n".join(missing))

    load_law_jsonl_to_db(paths, batch_size=2048)
