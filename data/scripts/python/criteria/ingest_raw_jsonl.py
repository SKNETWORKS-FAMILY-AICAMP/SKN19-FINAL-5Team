# JSONL 적재 스크립트(실험용) - 오류 없이 동작하도록 정리본
# - dict/list가 들어오는 필드는 안전하게 문자열/JSON 문자열로 변환
# - inserted 카운트는 "INSERT 성공 시"에만 증가
# - JSON 파싱/INSERT 실패는 해당 줄만 스킵하고 계속 진행(실험용)

import os
import json
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row

load_dotenv()

conninfo = (
    f"host={os.environ['PGHOST']} "
    f"port={os.environ['PGPORT']} "
    f"dbname={os.environ['PGDATABASE']} "
    f"user={os.environ['PGUSER']} "
    f"password={os.environ['PGPASSWORD']}"
)

INSERT_SQL = """
INSERT INTO lab.raw_records (source, record_type, source_id, page, doc, text)
VALUES (%s, %s, %s, %s, %s::jsonb, %s)
"""

def safe_get(d, key):
    if not isinstance(d, dict):
        return None
    v = d.get(key)
    return v if v is not None else None

def to_text(v):
    """TEXT 컬럼에 안전하게 넣기 위한 변환"""
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)

def extract_preview_text(obj):
    # 파일마다 텍스트 필드 이름이 다를 수 있어 후보를 넓게 둠
    candidates = ["text", "content", "index_text", "body", "title", "summary"]

    for k in candidates:
        v = safe_get(obj, k)
        if v is None:
            continue

        # 1) 문자열이면 그대로
        if isinstance(v, str):
            return v.strip() if v.strip() else None

        # 2) dict면 normalized/raw 우선
        if isinstance(v, dict):
            if isinstance(v.get("normalized"), str) and v["normalized"].strip():
                return v["normalized"].strip()
            if isinstance(v.get("raw"), str) and v["raw"].strip():
                return v["raw"].strip()
            # 그 외는 통째로 문자열화
            return json.dumps(v, ensure_ascii=False)

        # 3) list면 문자열화
        if isinstance(v, list):
            return json.dumps(v, ensure_ascii=False)

        # 4) 기타 타입은 문자열로
        return str(v)

    return None

def main():
    # 여기만 바꾸면 다른 파일도 동일 로직으로 적재 가능
    jsonl_path = r"criteria_jsonl_data/content_guideline.jsonl"
    source_name = "content_guideline"  # 파일 라벨(조회용)

    inserted = 0
    skipped_parse = 0
    skipped_insert = 0

    with psycopg.connect(conninfo, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue

                    # 1) JSON 파싱
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError as e:
                        skipped_parse += 1
                        print(f"[SKIP][PARSE] line {line_no}: {e}")
                        continue

                    if not isinstance(obj, dict):
                        skipped_parse += 1
                        print(f"[SKIP][PARSE] line {line_no}: not a JSON object")
                        continue

                    # 2) 메타 필드 추출(파일마다 다를 수 있으니 후보 키)
                    record_type = safe_get(obj, "type") or safe_get(obj, "record_type")
                    source_id = safe_get(obj, "id") or safe_get(obj, "ref_id") or safe_get(obj, "unit_id")
                    page = safe_get(obj, "page")

                    # 3) preview_text는 TEXT 컬럼이므로 반드시 문자열화되게 처리
                    preview_text = extract_preview_text(obj)

                    # 4) doc는 jsonb에 넣을 "JSON 문자열"로 변환
                    doc_json = json.dumps(obj, ensure_ascii=False)

                    # 5) TEXT 컬럼 들어갈 값들 안전 변환
                    record_type = to_text(record_type)
                    source_id = to_text(source_id)
                    page = int(page) if isinstance(page, int) else (int(page) if isinstance(page, str) and page.isdigit() else None)
                    preview_text = to_text(preview_text)

                    # 6) INSERT (실패해도 다음 줄 계속)
                    try:
                        cur.execute(
                            INSERT_SQL,
                            (
                                source_name,
                                record_type,
                                source_id,
                                page,
                                doc_json,
                                preview_text,
                            ),
                        )
                        inserted += 1
                    except Exception as e:
                        skipped_insert += 1
                        print(f"[SKIP][INSERT] line {line_no}: {e}")
                        continue

        conn.commit()

    print(
        f"Inserted {inserted} rows into lab.raw_records (source='{source_name}'). "
        f"Skipped parse={skipped_parse}, skipped insert={skipped_insert}"
    )

if __name__ == "__main__":
    main()
