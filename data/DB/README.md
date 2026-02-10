# Consumer RAG Database

PostgreSQL + pgvector 기반 벡터 데이터베이스

**✅ 현재 상태 (2026-01-28)**
- **AWS RDS 구축 완료**: PostgreSQL 17.2 + pgvector 0.8.1
- **데이터 삽입 완료**: 총 38,680건 (법령 6,077건 + 사례 32,603건)
- **검색 API 구축 완료**: FastAPI 기반 하이브리드 검색 시스템
- **검색 최적화 완료**: 제목 가중치 시스템 적용 (제목 0.6, 본문 0.4)
- **백업 완료**: AWS RDS 스냅샷 생성 (`ddoksori-final-2026-01-28-ver2`)
- **팀원 접속 가능**: 아래 로컬 연결 방법 참고

**환경 선택:**
- **팀 프로젝트 (운영 중)**: AWS RDS 사용 → 아래 팀원 로컬 연결 가이드 참고
- **로컬 개발/테스트**: Docker 사용 → 하단 Docker 가이드 참고

---

## 🔗 팀원 로컬 연결 가이드 (AWS RDS)

### 1️⃣ DBeaver로 DB 연결

**DBeaver 설치**: [다운로드](https://dbeaver.io/download/)

**연결 정보**:
```
Host: ddoksori-postgres.czocsimuw0dc.ap-northeast-2.rds.amazonaws.com
Port: 5432
Database: ddoksori
Username: postgres
Password: 별도 공유
```

**연결 순서**:
1. DBeaver 실행
2. 좌측 상단 "새 데이터베이스 연결" 클릭
3. PostgreSQL 선택
4. 위 연결 정보 입력
5. "Test Connection" 클릭하여 성공 확인
6. "완료" 클릭

---

### 2️⃣ Python에서 DB 연결

#### (1) 환경 변수 설정

프로젝트 루트의 `.env` 파일에 다음 정보 입력:

```env
# AWS RDS 연결 정보
DB_HOST=ddoksori-postgres.czocsimuw0dc.ap-northeast-2.rds.amazonaws.com
DB_PORT=5432
DB_NAME=ddoksori
DB_USER=postgres
DB_PASSWORD=별도 공유

# OpenAI API Key (임베딩 생성용)
OPENAI_API_KEY=sk-proj-...
```

⚠️ **주의**: `.env` 파일은 절대 GitHub에 업로드하지 마세요!

#### (2) Python 패키지 설치

```bash
# 가상환경 활성화
conda activate ddoksori

# 필수 패키지 설치
pip install psycopg2-binary python-dotenv openai
```

#### (3) Python 코드 예시

```python
import psycopg2
from pathlib import Path
from dotenv import load_dotenv
import os

# .env 파일 로드
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

# RDS 연결
conn = psycopg2.connect(
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT")),
    database=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD")
)

cursor = conn.cursor()

# 데이터 확인
cursor.execute("SELECT COUNT(*) FROM vector_chunks;")
total_chunks = cursor.fetchone()[0]
print(f"총 청크 수: {total_chunks}")

cursor.close()
conn.close()
```

---

### 3️⃣ 검색 API 사용

#### (1) API 서버 실행

```bash
# 가상환경 활성화
conda activate ddoksori

# DB 폴더로 이동
cd data_n_db/DB

# API 서버 실행
python 03_01_search_api.py
```

서버가 실행되면:
- **API 엔드포인트**: http://localhost:8000
- **Swagger UI**: http://localhost:8000/docs

#### (2) API 테스트

**Health Check**:
```bash
curl http://localhost:8000/health
```

**검색 요청 예시**:
```bash
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "환불 거부 해결 방법",
    "search_type": "hybrid",
    "top_k": 10
  }'
```

**Python으로 테스트**:
```python
import requests

response = requests.post(
    "http://localhost:8000/search",
    json={
        "query": "환불 거부 해결 방법",
        "search_type": "hybrid",
        "category_filter": "해결",
        "top_k": 5
    }
)

results = response.json()
for result in results["results"]:
    print(f"Score: {result['score']:.4f}")
    print(f"Text: {result['text'][:100]}...\n")
```

---

### 4️⃣ 데이터 현황 (2026-01-26 기준)

**전체 데이터**:
- **총 청크**: 40,285건
- **법령 데이터 (law_guide)**: 6,077건
- **사례 데이터 (case)**: 34,208건

**사례 카테고리별**:
- 조정: 20,992건 (61.3%)
- 상담: 11,342건 (33.2%)
- 해결: 1,874건 (5.5%)

**사례 데이터 소스별**:
- Crawling: 32,603건
- PDF: 168건
- Unknown: 1,437건

**연도별 사례**:
- 2010-2020년: 168건 (PDF 해결사례집)
- 2022-2024년: 209건 (온라인 우수해결사례)

---

### 5️⃣ RDS 인스턴스 정보

**사양**:
- DB 엔진: PostgreSQL 17.2
- 인스턴스: db.r7g.xlarge (4 vCPU, 32 GiB RAM)
- 스토리지: 100GB gp3
- 리전: ap-northeast-2 (서울)

**성능**:
- 데이터 삽입: 40,285건 / 11분 36초
- 검색 속도: 약 2.4초/쿼리 (임베딩 생성 포함)

---

## 🏗️ 처음부터 DB 구축하기 (AWS RDS 또는 로컬)

**새로 데이터베이스를 구축하는 경우 이 순서대로 진행하세요.**

### 실행 순서

```bash
# 1. 스키마 생성
python DB/02_01_run_schema.py

# 2. 법령 데이터 삽입 (약 1-2분)
python DB/02_02_insert_law_guide.py

# 3. 사례 데이터 삽입 (약 5-10분)
python DB/02_03_insert_case.py
```

### 완료 후 확인

```bash
# 빠른 연결 테스트
python DB/03_00_db_diagnostics.py

# 상세 스키마 검증
python DB/03_00_db_diagnostics.py --full
```

### 포함된 기능

위 3개 스크립트 실행만으로 다음이 모두 설정됩니다:

- ✅ 전체 스키마 (테이블, 인덱스, 뷰, 함수)
- ✅ document_type 분류 (법률, 시행령, 행정규칙, 별표)
- ✅ article_number 추출 (조문번호)
- ✅ article_number_normalized (자동 정규화)
- ✅ 제목 가중치 시스템 (제목 0.6, 본문 0.4)
- ✅ 모든 인덱스 (HNSW, BM25, 필터링용)
- ✅ 검색 함수 (hybrid, bm25, vector)
- ✅ Re-ranking 로직 (분할된 청크 병합)

**참고**:
- Migration 폴더의 스크립트는 **기존 DB 업그레이드용**입니다
- 새로 구축할 때는 실행하지 마세요!

---

## 🔄 기존 DB 업그레이드 (Migration)

**이미 운영 중인 DB를 최신 버전으로 업그레이드하는 경우**

### 상태 확인

```bash
# Migration이 필요한지 확인
python DB/check_migration_status.py
python DB/03_00_db_diagnostics.py --full
```

### Migration 실행

필요한 경우에만 실행:

```bash
# article_number 컬럼 추가
python DB/migrations/migration_add_article_columns.py

# document_type 컬럼 추가
python DB/migrations/migration_add_document_type.py

# document_type 데이터 분류
python DB/migrations/fix_document_type_classification.py

# 제목 가중치 시스템 적용 (검색 최적화, 권장)
python DB/migrations/migration_add_title_weighting.py
```

자세한 내용은 `migrations/README.md` 참고

**제목 가중치 시스템 (최신)**:
- case 데이터 제목이 text 필드에 포함되어 제목 검색 가능
- 제목에 매칭된 결과가 본문보다 1.5배 높은 점수
- 분할된 사례의 청크들을 자동 병합하여 완전한 컨텍스트 제공
- 소요 시간: 약 4분 (32,602개 업데이트)

---

## 🚀 빠른 시작 (Docker - 로컬 개발)

### 1. 사전 준비

- Docker Desktop 설치 ([다운로드](https://www.docker.com/products/docker-desktop/))
- Windows 사용자: WSL 2 활성화 필요

### 2. 환경 변수 설정

`.env.example`을 복사하여 `.env` 파일 생성 후 Docker 설정 사용:

```bash
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ddoksori
DB_USER=postgres
DB_PASSWORD=postgres  # 변경 권장
```

### 3. Docker 컨테이너 실행

```bash
# DB 디렉토리로 이동 (프로젝트 루트에서)
cd data_n_db/DB

# Docker 컨테이너 시작
docker run --name postgres-ddoksori \
  -e POSTGRES_DB=ddoksori \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  -v pgdata:/var/lib/postgresql/data \
  -d pgvector/pgvector:pg17
```

### 4. 스키마 및 데이터 삽입

```bash
# Python 가상환경에서 실행
python 02_01_run_schema.py           # 스키마 생성
python 02_02_insert_law_guide.py     # 법령 데이터 삽입 (약 6,000건)
python 02_03_insert_case.py          # 사례 데이터 삽입 (약 34,000건)
```

### 5. DBeaver 연결

- Host: localhost
- Port: 5432
- Database: ddoksori
- Username: postgres
- Password: .env 파일의 DB_PASSWORD

---

## 📋 주요 명령어

```bash
# 컨테이너 시작
docker-compose up -d

# 컨테이너 중지
docker-compose stop

# 컨테이너 중지 및 삭제 (볼륨 유지)
docker-compose down

# 컨테이너 및 볼륨 모두 삭제 (주의!)
docker-compose down -v

# 로그 확인
docker-compose logs -f postgres

# PostgreSQL 접속
docker exec -it ddoksori_db psql -U postgres -d ddoksori

# 백업
docker exec ddoksori_db pg_dump -U postgres ddoksori > backup.sql

# 복원
docker exec -i ddoksori_db psql -U postgres -d ddoksori < backup.sql
```

---

## 📖 상세 가이드

### 환경별 구축 가이드

- **팀 프로젝트 (AWS RDS)**: `01_02_AWS_RDS구축방법.md`
  - AWS CLI 기반 RDS 인스턴스 생성
  - 보안 그룹 설정
  - pgvector 확장 설치
  - 팀원 공유 방법
  - 비용 관리 및 트러블슈팅

- **로컬 개발 (Docker)**: `01_01_DB구축방법.md`
  - Docker 상세 설정
  - 로컬 설치 방법 (Windows)
  - 크로스 플랫폼 주의사항
  - 문제 해결 (Troubleshooting)

### 전략 및 설계

DB 전략 및 스키마 설계는 `01_00_DB전략.md` 파일을 참고하세요.

---

## 🗂️ 파일 구조

```
DB/
├── .env                         # 환경 변수 (비밀번호, Git 제외)
├── .env.example                 # 환경 변수 템플릿
├── .gitignore                   # Git 제외 파일
│
├── 01_00_DB전략.md             # DB 전략 문서
├── 01_01_DB구축방법.md         # Docker 로컬 구축 가이드
├── 01_02_AWS_RDS구축방법.md   # AWS RDS 구축 가이드
├── 01_00_unified_schema.sql    # 통합 스키마 정의 ⭐
│
├── 02_01_run_schema.py          # 스키마 실행 스크립트
├── 02_02_insert_law_guide.py   # 법령 데이터 삽입 (6,077건) ⭐
├── 02_03_insert_case.py         # 사례 데이터 삽입 (34,208건)
│
├── 03_00_db_diagnostics.py      # DB 진단 도구 (연결 테스트 + 스키마 검증)
├── 03_01_search_api.py          # FastAPI 검색 서버
├── 03_02_test_search_api.py    # API 테스트 스크립트
├── 03_03_DB_n_API결과.md       # 구축 완료 결과 보고서
├── 03_04_DB연결및테스트안내.md # DB 연결 및 테스트 가이드
│
├── migrations/                  # 기존 DB 업그레이드용 Migration 스크립트
│   ├── README.md                # Migration 가이드
│   ├── check_migration_status.py    # Migration 상태 확인
│   ├── migration_add_article_columns.py
│   ├── migration_add_document_type.py
│   ├── fix_document_type_classification.py
│   └── migration_add_title_weighting.py  # 제목 가중치 시스템 ⭐
│
└── README.md                    # 이 파일
```

**⭐ 최근 업데이트 (2026-01-28)**:
- **제목 가중치 시스템**: 검색 정확도 향상 (제목 0.6, 본문 0.4)
- **Re-ranking 로직**: 분할된 사례 청크 자동 병합
- `02_03_insert_case.py`: case 데이터 text 필드에 제목 추가
- `03_01_search_api.py`: Re-ranking 함수 추가
- `01_00_unified_schema.sql`: 가중치 적용 tsvector 함수
- `migrations/migration_add_title_weighting.py`: 제목 가중치 마이그레이션

**실행 순서**:
- 새 DB 구축: `02_01` → `02_02` → `02_03`
- 기존 DB 업그레이드: `migrations/` 폴더 스크립트

---

## ⚠️ 주의사항

### 보안
1. **`.env` 파일 관리**:
   - 절대 GitHub에 커밋하지 마세요 (비밀번호 포함)
   - `.gitignore`에 이미 추가되어 있음
   - 팀원과 공유 시 Slack DM 등 비공개 채널 사용

2. **RDS 비밀번호**:
   - 팀원에게 별도로 공유됩니다
   - `.env` 파일에 입력 후 사용

### AWS RDS 비용 관리 💰

**현재 구성 비용** (db.r7g.xlarge):
- **월 약 $380-390** (시간당 $0.50)
- 프로덕션급 성능 인스턴스

**비용 절감 방법**:
1. **사용 시간만 켜기** (권장):
   ```bash
   # 사용 안 할 때 중지 (GUI 또는 CLI)
   aws rds stop-db-instance --db-instance-identifier ddoksori-postgres

   # 재시작
   aws rds start-db-instance --db-instance-identifier ddoksori-postgres
   ```
   - 최대 7일까지 중지 가능
   - 월 14일만 사용 시 → 약 $180-200/월

2. **프로젝트 종료 후**:
   - 스냅샷 생성 후 인스턴스 삭제
   - 스냅샷 보관 비용: 월 $2-3
   - 필요 시 스냅샷에서 복원 가능

### Docker 사용 시
- 볼륨 삭제 시 모든 데이터가 삭제됩니다 (`docker rm -v`)
- 로컬 개발/테스트 전용으로 사용
- 팀 공유는 AWS RDS 사용 (이미 구축됨)

---

## 🆘 문제 해결

### AWS RDS 연결 실패

**증상**: `connection refused` 또는 타임아웃

**해결 방법**:
1. RDS 인스턴스 상태 확인 (AWS 콘솔에서 "사용 가능" 상태 확인)
2. 보안 그룹 인바운드 규칙 확인:
   - 포트 5432가 개방되어 있는지 확인
   - 소스: 0.0.0.0/0 (모든 IP 허용)
3. 퍼블릭 액세스가 "예"로 설정되어 있는지 확인
4. 엔드포인트 주소가 정확한지 확인

### 비밀번호 인증 실패

**증상**: `password authentication failed`

**해결 방법**:
1. `.env` 파일의 비밀번호 확인 (팀원에게 별도 공유됨)
2. 비밀번호에 공백이 없는지 확인
3. 팀 채널에서 최신 비밀번호 확인

### DBeaver 연결 안 됨

**해결 방법**:
1. 연결 정보 재확인:
   ```
   Host: ddoksori-postgres.czocsimuw0dc.ap-northeast-2.rds.amazonaws.com
   Port: 5432
   Database: ddoksori
   Username: postgres
   Password: 별도 공유
   ```
2. "Test Connection" 클릭하여 오류 메시지 확인
3. PostgreSQL JDBC 드라이버가 설치되어 있는지 확인

### API 서버 실행 오류

**증상**: `ModuleNotFoundError: No module named 'fastapi'`

**해결 방법**:
```bash
# 가상환경 활성화 확인
conda activate ddoksori

# 패키지 재설치
pip install fastapi uvicorn psycopg2-binary openai python-dotenv
```

### 검색 속도가 느림

**원인**: RDS 네트워크 지연 (정상)

**예상 속도**:
- 첫 검색: 약 2.4초 (임베딩 생성 포함)
- 이후 검색: 약 2.4초

---

## 🐳 Docker 로컬 개발 (선택사항)

### Docker 데몬이 실행되지 않음

```
Cannot connect to the Docker daemon
```

→ Docker Desktop을 시작하세요.

### 포트가 이미 사용 중

```
Bind for 0.0.0.0:5432 failed
```

→ `.env` 파일에서 `POSTGRES_PORT=5433`으로 변경

### Docker DBeaver 연결

→ 연결 정보:
- Host: `localhost` (또는 `127.0.0.1`)
- Port: `5432`
- Database: `ddoksori`
- Username: `postgres`
- Password: `.env` 파일의 DB_PASSWORD

---

## 💡 환경별 추천

| 상황 | 권장 환경 | 이유 | 상태 |
|------|----------|------|------|
| 팀 프로젝트 (현재) | AWS RDS | 모든 팀원이 동일한 DB 접근 가능 | ✅ 구축 완료 |
| 로컬 개발/테스트 | Docker | 빠른 환경 구성, 비용 무료 | 선택 사항 |
| 프로덕션 배포 | AWS RDS | 안정성, 백업, 확장성 | 운영 중 |

---

## 📚 추가 참고 자료

**구축 가이드**:
- `01_00_DB전략.md`: DB 전략 및 스키마 설계
- `01_01_DB구축방법.md`: Docker 로컬 구축 가이드
- `01_02_AWS_RDS구축방법.md`: AWS RDS 구축 가이드 (GUI/CLI)
- `03_03_DB_n_API결과.md`: **AWS RDS 구축 완료 보고서** ⭐

**스크립트 파일**:
- `02_01_run_schema.py`: 스키마 실행
- `02_02_insert_law_guide.py`: 법령 데이터 삽입
- `02_03_insert_case.py`: 사례 데이터 삽입
- `03_01_search_api.py`: FastAPI 검색 서버
- `03_02_test_search_api.py`: API 테스트

---

## 🎯 빠른 참고

**팀원이 처음 시작할 때**:
1. `.env` 파일 생성 및 RDS 연결 정보 입력 (팀 채널에서 비밀번호 확인)
2. DBeaver 설치 및 연결 테스트
3. Python 가상환경 설정 및 패키지 설치
4. API 서버 실행 및 검색 테스트

**데이터 확인**:
- DBeaver에서 `SELECT COUNT(*) FROM vector_chunks;` 실행
- 결과: 40,285건 확인

**검색 테스트**:
```bash
# API 서버 실행
python 03_01_search_api.py

# 테스트 스크립트 실행
python 03_02_test_search_api.py
```

---

**최종 수정일**: 2026-01-28
**작성자**: DDoksori 팀
**버전**: 3.1.0 (AWS RDS 구축 완료, 데이터 삽입 완료, 검색 API 완료, 제목 가중치 시스템 적용)
