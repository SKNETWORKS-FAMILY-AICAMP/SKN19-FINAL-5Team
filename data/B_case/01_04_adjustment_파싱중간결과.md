# 조정사례 PDF 데이터 분석 결과

## 개요
조정사례 PDF 데이터 2개 파일을 분석한 결과를 정리한 문서입니다.
- 한국소비자원 PDF 데이터
- 한국인터넷진흥원 PDF 데이터

---

## 1. 전체 통계

### 1-1. 사례 개수 요약

| 데이터 소스 | 사례 개수 | 구조 유형 |
|-----------|---------|---------|
| 한국소비자원_PDF | 313 | dict |
| 한국인터넷진흥원_PDF | 123 | dict |
| **전체 합계** | **436** | - |

---

## 2. 키값(메타데이터) 상세 비교

### 2-1. 각 파일의 키값 개수

| 데이터 소스 | 키값 개수 |
|-----------|---------|
| 한국소비자원_PDF | 12개 |
| 한국인터넷진흥원_PDF | 14개 |

### 2-2. 각 파일의 키값을 순서대로 비교 (JSON 저장 순서)

| 순서 | 한국소비자원_PDF | 한국인터넷진흥원_PDF |
|:----:|:--------:|:--------:|
| 1 | `case_number` | `case_number` |
| 2 | `method` | `method` |
| 3 | `title` | `title` |
| 4 | `case_type` | `case_type` |
| 5 | `printed_page_number` | `printed_page_number` |
| 6 | `overview` | `overview` |
| 7 | `result` | `claims` |
| 8 | `claims` | `judgement` |
| 9 | `judgement` | `result` |
| 10 | `page` | `parsing_method` |
| 11 | `raw_text` | `number` |
| 12 | `source` | `page_start` |
| 13 | - | `page_end` |
| 14 | - | `source_file` |

### 2-3. 키값 유형별 분류 분석

#### 공통 키값 (모든 파일에 존재)
공통으로 포함된 키값 개수: 9개

- `case_number`
- `case_type`
- `claims`
- `judgement`
- `method`
- `overview`
- `printed_page_number`
- `result`
- `title`

#### 고유 키값 (특정 파일에만 존재)

**한국소비자원_PDF** 에만 존재하는 키값 (3개):
- `page`
- `raw_text`
- `source`

**한국인터넷진흥원_PDF** 에만 존재하는 키값 (5개):
- `number`
- `page_end`
- `page_start`
- `parsing_method`
- `source_file`

---

## 3. 파일별 상세 분석

### 한국소비자원_PDF

**파일 경로**: `C:\Users\Playdata\Desktop\project\05_5th_project\data_n_db\B_case\01_B_parsed\02_02_AdjustmentCase\kca_p_adjustment_case.json`

**사례 개수**: 313개

**데이터 구조 타입**: dict

**전체 키값 개수**: 12개

**메타데이터 (Key값)**:

1. `case_number`
2. `method`
3. `title`
4. `case_type`
5. `printed_page_number`
6. `overview`
7. `result`
8. `claims`
9. `judgement`
10. `page`
11. `raw_text`
12. `source`

### 한국인터넷진흥원_PDF

**파일 경로**: `C:\Users\Playdata\Desktop\project\05_5th_project\data_n_db\B_case\01_B_parsed\02_02_AdjustmentCase\kisa_p_adjustment_case.json`

**사례 개수**: 123개

**데이터 구조 타입**: dict

**전체 키값 개수**: 14개

**메타데이터 (Key값)**:

1. `case_number`
2. `method`
3. `title`
4. `case_type`
5. `printed_page_number`
6. `overview`
7. `claims`
8. `judgement`
9. `result`
10. `parsing_method`
11. `number`
12. `page_start`
13. `page_end`
14. `source_file`

---

## 4. 조정사례 PDF 데이터 특징

### 4-1. 한국소비자원 PDF

**사례 개수**: 313개

**특징**:
- 한국소비자원 공식 발행 PDF에서 파싱
- 공정거래위원회 분쟁조정위원회의 조정사례 포함
- 인쇄된 페이지 번호 정보 보존
- 원본 텍스트(raw_text) 포함으로 정확한 정보 유지
- 당사자 주장과 판단 결정 정보 포함

### 4-2. 한국인터넷진흥원 PDF

**사례 개수**: 123개

**특징**:
- 한국인터넷진흥원(KISA) 공식 발행 PDF에서 파싱
- 전자거래 분쟁조정 사례 집중
- 연도별 통계 정보 포함
- 파싱 방법 메타데이터 포함
- 출처 파일명 추적 정보 포함

---

## 5. 데이터 비교 분석

| 항목 | 한국소비자원_PDF | 한국인터넷진흥원_PDF |
|-----|----------|----------|
| **사례 개수** | 313개 | 123개 |
| **키값 개수** | 12개 | 14개 |
| **데이터 구조** | dict | dict |
| **기본 ID** | `case_number`, `method` | `case_number`, `method` |
| **사례 설명** | `overview` | `overview` |
| **당사자주장** | `claims` | `claims` |
| **판단결정** | `judgement`+`result` | `judgement`+`result` |
| **고유 키값** | `page`, `raw_text`, `source` | `parsing_method`, `page_start`, `page_end`, `source_file` |

---

## 6. 주요 차이점

### 6-1. 구조 차이

**한국소비자원_PDF**:
- 기본 메타정보만 포함
- `page`: 페이지 정보 (dict 형식)
- `raw_text`: 원본 텍스트 보존

**한국인터넷진흥원_PDF**:
- 상세한 파싱 메타정보 포함
- `page_start`: 시작 페이지
- `page_end`: 종료 페이지
- `parsing_method`: 파싱 방법 (예: pdfplumber)
- `source_file`: 원본 파일명
- `number`: 순서 번호

### 6-2. 데이터 추적성

- **한국소비자원_PDF**: `source` 필드로 출처 표기
- **한국인터넷진흥원_PDF**: `source_file` 필드로 원본 파일명 명시

---

## 7. 데이터 통합 고려사항

### 7-1. 키값 매핑

```
- case_number → 사건번호
- method → 처리 방법
- title → 사건제목
- case_type → 사건유형
- printed_page_number → 인쇄된 페이지 번호
- overview → 사건개요
- claims → 당사자주장
- judgement → 판단
- result → 결정
- page → 페이지 정보
- raw_text → 원본텍스트
- source → 출처
- parsing_method → 파싱 방법
- page_start / page_end → 페이지 범위
- source_file → 원본 파일명
```

### 7-2. 데이터 품질

- **완성도**: 두 파일 모두 완전한 메타정보 포함
- **원본 보존**: raw_text로 원본 텍스트 유지
- **추적성**: source/source_file로 출처 명확히 기록
- **정확성**: PDF에서 직접 파싱하여 높은 정확도

---

## 8. 최종 요약

**총 조정사례 PDF 데이터**: 436개

**구성**:
- 한국소비자원: 313개 (75.9%)
- 한국인터넷진흥원: 123개 (24.1%)

**데이터 특성**:
- 모두 dict(객체) 구조로 메타정보 포함
- 공식 발행 문서에서 파싱된 신뢰도 높은 데이터
- 원본 텍스트 보존으로 정확한 정보 유지
- 상세한 파싱 메타정보로 데이터 추적 용이

**통합 가능성**:
- 핵심 필드 일치로 통합 데이터셋 구성 용이
- 출처 추적 정보 보존으로 중복 제거 가능
- PDF 특성상 정적이고 신뢰도 높은 데이터