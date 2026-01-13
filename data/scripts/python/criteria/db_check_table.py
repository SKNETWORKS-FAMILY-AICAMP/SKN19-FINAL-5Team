# 테이블 존재 여부 확인

import os
from dotenv import load_dotenv
import psycopg

load_dotenv()

conninfo = (
    f"host={os.environ.get('PGHOST')} "
    f"port={os.environ.get('PGPORT')} "
    f"dbname={os.environ.get('PGDATABASE')} "
    f"user={os.environ.get('PGUSER')} "
    f"password={os.environ.get('PGPASSWORD')}"
)

SQL = """
SELECT to_regclass('public.law_unit_chunks_stage') AS table_name;
"""

with psycopg.connect(conninfo) as conn:
    with conn.cursor() as cur:
        cur.execute(SQL)
        print(cur.fetchone()[0])
