# Database Migrations

이 폴더는 **기존 DB를 최신 스키마로 업그레이드**하기 위한 migration 스크립트들입니다.

## ⚠️ 주의사항

**새로 DB를 구축하는 경우 이 폴더의 스크립트를 실행하지 마세요!**

새로 구축할 때는 상위 폴더의 스크립트만 실행하면 됩니다:
```bash
python 02_01_run_schema.py
python 02_02_insert_law_guide.py
python 02_03_insert_case.py
```

## Migration 스크립트 목록

### check_migration_status.py
**목적**: Migration 필요 여부 확인

**기능**:
- article_number 컬럼 존재 여부 확인
- normalize_article_number() 함수 확인
- 트리거 확인
- 인덱스 확인
- 샘플 데이터 확인

**실행 방법**:
```bash
# migrations 폴더에서
python check_migration_status.py

# 또는 상위 폴더에서
python migrations/check_migration_status.py
```

**결과**:
- Migration 필요 여부 판단
- 구체적인 실행 가이드 제공

---

### migration_add_article_columns.py
**목적**: `article_number`, `article_number_normalized` 컬럼 추가

**실행 조건**:
- 기존 DB에 article_number 컬럼이 없는 경우

**수행 작업**:
1. `article_number` 컬럼 추가
2. `article_number_normalized` 컬럼 추가
3. `normalize_article_number()` 함수 생성
4. 자동 정규화 트리거 생성
5. 인덱스 생성 (idx_article_number, idx_article_number_normalized)
6. 기존 데이터에서 조문번호 추출 및 정규화

**실행 방법**:
```bash
python migrations/migration_add_article_columns.py
```

---

### migration_add_document_type.py
**목적**: `document_type` 컬럼 추가

**실행 조건**:
- 기존 DB에 document_type 컬럼이 없는 경우

**수행 작업**:
1. `document_type` 컬럼 추가
2. 인덱스 생성 (idx_document_type, idx_dataset_document_type)

**실행 방법**:
```bash
python migrations/migration_add_document_type.py
```

**참고**: 이 스크립트는 컬럼만 추가하고 데이터 분류는 하지 않습니다.

---

### fix_document_type_classification.py
**목적**: 기존 데이터의 `document_type` 분류

**실행 조건**:
- document_type 컬럼은 있지만 데이터가 NULL인 경우
- migration_add_document_type.py 실행 후 반드시 실행해야 함

**수행 작업**:
1. chunk_id 기반 별표 분류
2. law_name 기반 행정규칙/시행령/시행규칙 분류
3. 나머지는 법률로 분류

**분류 로직**:
```
1. chunk_id에 '별표' 포함 → 별표
2. law_name에 '지침' 포함 → 행정규칙
3. law_name에 '시행령' 포함 → 시행령
4. law_name에 '시행규칙' 포함 → 시행규칙
5. 그 외 → 법률
```

**실행 방법**:
```bash
python migrations/fix_document_type_classification.py
```

---

### migration_add_title_weighting.py
**목적**: 제목 가중치 시스템 적용

**실행 조건**:
- 검색 성능 최적화를 위한 제목 가중치 적용

**수행 작업**:
1. 가중치 적용 tsvector 함수 생성 (`update_text_tsv_with_weights()`)
2. 트리거 업데이트 (제목/본문 분리 및 가중치 적용)
3. case 데이터 text 필드에 제목 추가 (32,602개)
4. 전체 tsvector 재생성 (38,680개)
5. 검색 함수 업데이트 (가중치 배열 적용)

**가중치 적용**:
- 제목: 'A' 가중치 (0.6)
- 본문: 'B' 가중치 (0.4)
- 효과: 제목 매칭 시 1.5배 높은 점수

**실행 방법**:
```bash
python migrations/migration_add_title_weighting.py
```

**소요 시간**: 약 4분 (32,602개 텍스트 업데이트 + 38,680개 tsvector 재생성)

**효과**:
- case 데이터 제목 검색 가능
- 제목 매칭 시 높은 우선순위
- law_guide 조문 제목 중요도 반영
- 검색 정확도 향상

---

## 전체 Migration 순서 (기존 DB 업그레이드)

기존 DB를 최신 버전으로 업그레이드하려면 다음 순서로 실행:

```bash
# 1. article_number 추가
python migrations/migration_add_article_columns.py

# 2. document_type 컬럼 추가
python migrations/migration_add_document_type.py

# 3. document_type 데이터 분류
python migrations/fix_document_type_classification.py

# 4. 제목 가중치 시스템 적용 (선택 사항, 검색 최적화)
python migrations/migration_add_title_weighting.py
```

**참고**:
- Migration 1~3: 필수 (스키마 업데이트)
- Migration 4: 선택 (검색 성능 최적화, 권장)

## 상태 확인

Migration이 필요한지 확인:

```bash
# migrations 폴더에서 실행
python check_migration_status.py

# 또는 상위 폴더에서
python migrations/check_migration_status.py

# 전체 스키마 검증
python 03_00_db_diagnostics.py --full
```

---

## 새 DB 구축 vs Migration

### 새로 구축하는 경우 (권장)
```bash
cd ..  # DB 폴더로 이동
python 02_01_run_schema.py
python 02_02_insert_law_guide.py
python 02_03_insert_case.py
```
- ✅ 빠름 (한 번에 올바르게 삽입)
- ✅ 간단함 (3개 스크립트만)
- ✅ 성능 좋음 (UPDATE 없음)

### 기존 DB 업그레이드하는 경우
```bash
python migrations/migration_add_article_columns.py
python migrations/migration_add_document_type.py
python migrations/fix_document_type_classification.py
```
- ⚠️ 느림 (기존 데이터 UPDATE)
- ⚠️ 복잡함 (3개 migration 실행)
- ✅ 데이터 보존 (기존 데이터 유지)

---

## 문의

Migration 관련 문제가 있다면:
1. `migrations/check_migration_status.py`로 현재 상태 확인
2. 에러 메시지 확인
3. 팀 채널에 문의

**작성일**: 2026-01-28
**버전**: 1.0.0
