import os
import glob
import json
import time
from typing import Any, Dict, Iterable, List, Optional

from dotenv import load_dotenv
from tqdm import tqdm

import psycopg
from psycopg.rows import dict_row

# pgvector adapter
from pgvector.psycopg import register_vector

# OpenAI SDK (new-style)
from openai import OpenAI


# ----------------------------
# Config
# ----------------------------
DEFAULT_EMBED_MODEL = "text-embedding-3-small"
BATCH_SIZE=128
SLEEP_SECS=0

# 너무 긴 텍스트 방지(나중에는 tiktoken으로 계산)
MAX_CHARS = 30000


# ----------------------------
# SQL
# ----------------------------
UPSERT_SQL = """
INSERT INTO law_unit_chunks_stage (
  unit_id, law_id, law_name, unit_level, path,
  article_no, paragraph_no, item_no, subitem_no,
  index_text, node_refs, source_type,
  embedding_model, embedding
)
VALUES (
  %(unit_id)s, %(law_id)s, %(law_name)s, %(unit_level)s, %(path)s,
  %(article_no)s, %(paragraph_no)s, %(item_no)s, %(subitem_no)s,
  %(index_text)s, %(node_refs)s::jsonb, %(source_type)s,
  %(embedding_model)s, %(embedding)s
)
ON CONFLICT (unit_id) DO UPDATE SET
  law_id=EXCLUDED.law_id,
  law_name=EXCLUDED.law_name,
  unit_level=EXCLUDED.unit_level,
  path=EXCLUDED.path,
  article_no=EXCLUDED.article_no,
  paragraph_no=EXCLUDED.paragraph_no,
  item_no=EXCLUDED.item_no,
  subitem_no=EXCLUDED.subitem_no,
  index_text=EXCLUDED.index_text,
  node_refs=EXCLUDED.node_refs,
  source_type=EXCLUDED.source_type,
  embedding_model=EXCLUDED.embedding_model,
  embedding=EXCLUDED.embedding,
  indexed_at=now();
"""


# ----------------------------
# Helpers
# ----------------------------
def conninfo_from_env() -> str:
    return (
        f"host={os.environ.get('PGHOST','localhost')} "
        f"port={os.environ.get('PGPORT','5433')} "
        f"dbname={os.environ.get('PGDATABASE','postgres')} "
        f"user={os.environ.get('PGUSER','postgres')} "
        f"password={os.environ.get('PGPASSWORD','postgres')}"
    )


def iter_jsonl_files(pattern: str) -> List[str]:
    # e.g. data/law_chunks/*.jsonl
    files = sorted(glob.glob(pattern))
    if not files:
        raise RuntimeError(f"No jsonl files matched: {pattern}")
    return files


def read_jsonl_rows(paths: List[str]) -> Iterable[Dict[str, Any]]:
    for p in paths:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield json.loads(line)


def clean_text(s: Optional[str]) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    if len(s) > MAX_CHARS:
        s = s[:MAX_CHARS]
    return s


def chunked(lst: List[Any], n: int) -> Iterable[List[Any]]:
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


# ----------------------------
# Embedding
# ----------------------------
def embed_texts(client: OpenAI, model: str, texts: List[str]) -> List[List[float]]:
    """
    OpenAI embeddings: 한 요청에 여러 input 가능.
    """
    # 빈 문자열은 API에서 에러날 수 있으니 사전에 제거/대체
    # 여기선 호출 전에 필터링한다고 가정
    resp = client.embeddings.create(
        model=model,
        input=texts,
    )
    # resp.data[i].embedding
    return [d.embedding for d in resp.data]


# ----------------------------
# Main
# ----------------------------
def main():
    load_dotenv()

    jsonl_glob = os.environ.get("JSONL_GLOB", "law_chunks/*.jsonl")
    embed_model = DEFAULT_EMBED_MODEL

    # OpenAI key
    # .env에 OPENAI_API_KEY=... 권장
    client = OpenAI()

    files = iter_jsonl_files(jsonl_glob)
    print(f"[1/3] JSONL files: {len(files)} matched")
    print(f"      pattern={jsonl_glob}")
    
    # 먼저 전부 읽지 않고, BATCH_SIZE 단위로 스트리밍 처리(메모리 절약)
    conninfo = conninfo_from_env()

    print("[2/3] Connect DB")
    with psycopg.connect(conninfo, row_factory=dict_row) as conn:
        register_vector(conn)  # pgvector adapter
        with conn.cursor() as cur:
            print("[3/3] Embed + Upsert")

            buffer_rows: List[Dict[str, Any]] = []
            buffer_texts: List[str] = []

            total = 0
            upserted = 0
            skipped = 0

            def flush():
                nonlocal upserted, buffer_rows, buffer_texts
                if not buffer_rows:
                    return

                # 임베딩
                vectors = embed_texts(client, embed_model, buffer_texts)

                # DB upsert
                for r, vec in zip(buffer_rows, vectors):
                    payload = {
                        "unit_id": r["unit_id"],
                        "law_id": r["law_id"],
                        "law_name": r.get("law_name"),
                        "unit_level": r["unit_level"],
                        "path": r.get("path"),
                        "article_no": r.get("article_no"),
                        "paragraph_no": r.get("paragraph_no"),
                        "item_no": r.get("item_no"),
                        "subitem_no": r.get("subitem_no"),
                        "index_text": r["index_text"],
                        "node_refs": json.dumps(r.get("node_refs"), ensure_ascii=False),
                        "source_type": r.get("source_type", "statute"),
                        "embedding_model": embed_model,
                        "embedding": vec,  # pgvector adapter가 list[float] 처리
                    }
                    cur.execute(UPSERT_SQL, payload)

                conn.commit()
                upserted += len(buffer_rows)

                buffer_rows = []
                buffer_texts = []

                if SLEEP_SECS > 0:
                    time.sleep(SLEEP_SECS)

            # 진행바는 파일 단위가 아니라 레코드 단위가 좋아서, 대충 카운팅 없이 tqdm 업데이트
            pbar = tqdm(desc="Rows", unit="row")

            for row in read_jsonl_rows(files):
                total += 1

                # 필수값 체크
                unit_id = row.get("unit_id")
                law_id = row.get("law_id")
                unit_level = row.get("unit_level")
                text = clean_text(row.get("index_text"))

                if not unit_id or not law_id or not unit_level or not text:
                    skipped += 1
                    pbar.update(1)
                    continue

                # DB 적재용 row 정규화
                row["index_text"] = text
                if "source_type" not in row:
                    row["source_type"] = "statute"

                buffer_rows.append(row)
                buffer_texts.append(text)

                if len(buffer_rows) >= BATCH_SIZE:
                    flush()

                pbar.update(1)

            # 마지막 flush
            flush()
            pbar.close()

    print("Done.")
    print(f"Total rows seen: {total}")
    print(f"Upserted: {upserted}")
    print(f"Skipped (missing fields / empty text): {skipped}")
    print("Table: law_unit_chunks_stage")


if __name__ == "__main__":
    main()
