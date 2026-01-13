# DB 접속 테스트용 파일

import os
from dotenv import load_dotenv
import psycopg

load_dotenv()  # .env 로드

conninfo = (
    f"host={os.environ.get('PGHOST')} "
    f"port={os.environ.get('PGPORT')} "
    f"dbname={os.environ.get('PGDATABASE')} "
    f"user={os.environ.get('PGUSER')} "
    f"password={os.environ.get('PGPASSWORD')}"
)

with psycopg.connect(conninfo) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_user, inet_server_addr(), inet_server_port();")
        print(cur.fetchone())
