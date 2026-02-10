"""
스키마 실행 스크립트
"""
import psycopg2
import os
from pathlib import Path
from dotenv import load_dotenv

# .env 파일 로드 (상위 폴더에서)
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# PostgreSQL 연결 정보 (환경변수 우선, 없으면 기본값)
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost").strip(),
    "port": int(os.getenv("DB_PORT", "5432").strip()),
    "database": os.getenv("DB_NAME", "ddoksori").strip(),
    "user": os.getenv("DB_USER", "postgres").strip(),
    "password": os.getenv("DB_PASSWORD", "postgres").strip()
}

print("=" * 80)
print("[INFO] 스키마 실행 시작")
print("=" * 80)

try:
    # 데이터베이스 연결
    print(f"[INFO] 연결 중... {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    cursor = conn.cursor()
    print("[OK] 연결 성공\n")

    # 스키마 파일 읽기 (psql 메타 명령어 제외)
    print("[INFO] 스키마 파일 읽기 중...")
    with open("01_00_unified_schema.sql", "r", encoding="utf-8") as f:
        lines = f.readlines()

    # psql 메타 명령어 (\로 시작하는 라인) 제외
    filtered_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('\\'):
            filtered_lines.append(line)

    schema_sql = ''.join(filtered_lines)
    print("[OK] 스키마 파일 로드 완료\n")

    # 스키마 실행
    print("[INFO] 스키마 실행 중...")
    cursor.execute(schema_sql)
    conn.commit()
    print("[OK] 스키마 실행 완료\n")

    # 테이블 확인
    print("[INFO] 테이블 생성 확인...")
    cursor.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name;
    """)
    tables = cursor.fetchall()
    print(f"[OK] 생성된 테이블: {len(tables)}개")
    for table in tables:
        print(f"  - {table[0]}")
    print()

    # 뷰 확인
    print("[INFO] 뷰 생성 확인...")
    cursor.execute("""
        SELECT table_name
        FROM information_schema.views
        WHERE table_schema = 'public'
        ORDER BY table_name;
    """)
    views = cursor.fetchall()
    print(f"[OK] 생성된 뷰: {len(views)}개")
    for view in views:
        print(f"  - {view[0]}")
    print()

    # 함수 확인
    print("[INFO] 함수 생성 확인...")
    cursor.execute("""
        SELECT routine_name
        FROM information_schema.routines
        WHERE routine_schema = 'public'
        ORDER BY routine_name;
    """)
    functions = cursor.fetchall()
    print(f"[OK] 생성된 함수: {len(functions)}개")
    for func in functions:
        print(f"  - {func[0]}")
    print()

    print("=" * 80)
    print("[SUCCESS] 스키마 실행 완료!")
    print("=" * 80)

    cursor.close()
    conn.close()

except Exception as e:
    print(f"[ERROR] 오류 발생: {e}")
    if 'conn' in locals():
        conn.rollback()
