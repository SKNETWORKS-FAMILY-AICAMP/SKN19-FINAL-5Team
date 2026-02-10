"""
[별표 2] 품목별 해결기준 1 PDF 파싱 스크립트 (Google Gemini Vision)

파싱 전략:
1. PDF 각 페이지를 이미지로 변환
2. Gemini 2.5 Flash Vision API를 사용하여 구조화된 JSON으로 추출
3. 비고 매핑: 키워드 기반 우선, 위치 기반 폴백
"""

import json
import base64
import os
from pathlib import Path
from dotenv import load_dotenv
import fitz  # PyMuPDF
from google import genai
from google.genai import types
import time

# .env 파일에서 환경변수 로드
load_dotenv()

# 설정
PDF_PATH = r"C:\Users\Playdata\Desktop\project\05_5th_project\data_n_db\raw\02_Guide\소비자분쟁해결기준_별표\[별표 2] 품목별 해결기준 1.pdf"
# 출력 디렉토리: PDF와 같은 폴더
OUTPUT_DIR = os.path.dirname(PDF_PATH)
# 출력 파일명: PDF 파일명 + "_gemini.json"
pdf_basename = os.path.splitext(os.path.basename(PDF_PATH))[0]
OUTPUT_FILE = f"{pdf_basename}_gemini.json"

# Gemini API 키
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Rate limit 대응
DELAY_BETWEEN_PAGES = 1

# JSON 스키마 정의
PARSING_INSTRUCTION = """
이 이미지는 소비자분쟁해결기준 PDF의 한 페이지입니다. 표를 분석하여 정확한 JSON으로 변환해주세요.

**중요 규칙:**

1. **여러 표 처리**: 한 페이지에 여러 표가 있으면 각 표를 별도의 객체로 만들어 배열로 반환하세요.
   - 표 최상단의 텍스트(분쟁유형/해결기준/비고가 아닌 것) = "소분류"
   - 예: "⑦종묘 등", "③도서ㆍ음반", "①귀금속ㆍ보석"

2. **대분류/중분류 처리**:
   - 대분류: "Ⅰ. 상품(재화)", "Ⅱ. 서비스업" 등이 명시된 경우에만 입력
   - 중분류: "1. 농ㆍ수ㆍ축산물", "2. 문화용품류" 등이 명시된 경우에만 입력
   - 명시되지 않으면 빈 문자열로 설정 (이전 페이지 값을 계승한다는 의미)

3. **특수 표 처리 - 비고만 있는 경우**:
   - "분쟁유형" 컬럼이 없고 "비고"란만 있는 표는 이전 페이지 소분류의 비고 연장입니다
   - 이 경우 items는 빈 배열 [], notes만 채웁니다
   - 예: "③ 도서ㆍ음반 (2-2)" - 이전 페이지 "② 악기ㆍ완구류 (2-1)"의 비고 연장

4. **계층 구조 인식**:
   - 숫자) (1), 2), 3)...) → 최상위 분쟁유형 (id, dispute_type)
   - - (대시) → 2단계 조건 (conditions 배열)
   - ㆍ · • (중점) → 3단계 하위 조건 (sub_conditions 배열)

5. **병합 셀(rowspan) 처리**: 비고 열이 여러 행에 걸쳐 병합되어 있으면, 해당 비고를 모든 관련 분쟁유형에 복사하세요.

6. **비고 구조 인식**:
   - **단순 텍스트**: {"keyword": "...", "content": "...", "matched_by": "..."}
   - **복잡한 구조** (※, □ 등으로 시작하는 섹션):
     {
       "note_title": "섹션 제목 (예: ※ 통상사용률, □ 도서류)",
       "content": ["단순 텍스트 배열"] 또는 생략,
       "sub_notes": [
         {
           "condition": "하위 조건 (예: 가. 통상사용률)",
           "resolution": "해당되는 경우 값",
           "sub_conditions": [
             {"condition": "...", "resolution": "...", "notes": []}
           ],
           "notes": []
         }
       ]
     }
   - **비고 내부 표 파싱 시 중요**: 각 행의 condition과 resolution에 컬럼 헤더를 포함하세요
     * 예: 테이블 헤더가 "사용기간 | 통상사용률(%)"일 때
       - ❌ 잘못: {"condition": "1개월 미만", "resolution": "20"}
       - ✅ 올바름: {"condition": "사용기간: 1개월 미만", "resolution": "통상사용률(%): 20"}
     * 이렇게 해야 각 데이터가 독립적으로 의미를 가집니다

7. **비고 키워드 매핑**:
   - 비고에 "발아 불량", "직접경비", "예상수익", "구독료" 등 키워드가 있으면 keyword 필드에 추출
   - 키워드가 있으면 matched_by는 "keyword"
   - 키워드가 없으면 keyword는 빈 문자열, matched_by는 "position"

8. **출력 형식**:
   - 표가 1개: 단일 객체 {...}
   - 표가 2개 이상: 배열 [{...}, {...}]
   - 반드시 유효한 JSON만 출력하세요. 마크다운 블록 없이 순수 JSON만 반환하세요.

JSON 스키마:
{
  "대분류": "대분류명 (예: Ⅰ. 상품(재화)). 명시되지 않으면 빈 문자열",
  "중분류": "중분류명 (예: 1. 농ㆍ수ㆍ축산물(7개 업종)). 명시되지 않으면 빈 문자열",
  "소분류": "표 최상단 텍스트 (예: ⑦종묘 등, ①귀금속ㆍ보석). 여러 업종이 쉼표로 나열되어 있으면 그대로",
  "items": [
    {
      "id": "분쟁유형 번호 (1, 2, 3...)",
      "dispute_type": "분쟁유형 텍스트",
      "resolution": "바로 적용되는 해결기준 (조건이 없는 경우). 없으면 빈 문자열",
      "conditions": [
        {
          "condition": "조건 텍스트 (- 로 시작)",
          "resolution": "해결기준",
          "sub_conditions": [
            {
              "condition": "하위 조건 (ㆍ로 시작)",
              "resolution": "해결기준",
              "notes": []
            }
          ],
          "notes": [
            {
              "keyword": "매핑된 키워드 (없으면 빈 문자열)",
              "content": "비고 전체 내용",
              "matched_by": "keyword 또는 position"
            }
          ]
        }
      ],
      "notes": [
        // 단순 텍스트 비고
        {
          "keyword": "키워드 (없으면 빈 문자열)",
          "content": "비고 내용",
          "matched_by": "keyword 또는 position"
        },
        // 복잡한 구조 비고 (※, □ 등 섹션 제목이 있는 경우)
        {
          "note_title": "섹션 제목 (예: ※ 통상사용률, □ 도서류)",
          "content": ["단순 설명 텍스트 배열"],  // 선택사항
          "sub_notes": [
            {
              "condition": "하위 조건",
              "resolution": "해결기준",
              "sub_conditions": [
                {"condition": "...", "resolution": "...", "notes": []}
              ],
              "notes": []
            }
          ]
        }
      ]
    }
  ],
  "notes": [
    // 표 레벨 비고 (items 없이 비고만 있는 특수 표)
    // 동일한 구조: 단순 텍스트 또는 복잡한 구조
  ],
  "reference": {
    "근거법령": "근거 법령. 없으면 빈 문자열",
    "기타법령": "기타 법령. 없으면 빈 문자열"
  }
}

**예시**:
- 표 1개: {"대분류": "...", "소분류": "...", "items": [...]}
- 표 2개: [{"대분류": "...", "소분류": "⑦종묘 등", ...}, {"대분류": "", "소분류": "⑧...", ...}]
- 비고만 있는 표: {"소분류": "③ 도서ㆍ음반 (2-2)", "items": [], "notes": [...]}
"""


def pdf_to_base64_images(pdf_path: str, dpi: int = 200) -> list:
    """PDF의 각 페이지를 base64 인코딩된 이미지로 변환"""
    print(f"PDF를 이미지로 변환 중: {pdf_path}")

    doc = fitz.open(pdf_path)
    images = []

    for page_num in range(len(doc)):
        print(f"  페이지 {page_num + 1}/{len(doc)} 변환 중...")
        page = doc[page_num]

        # 페이지를 이미지로 변환
        pix = page.get_pixmap(dpi=dpi)
        img_bytes = pix.tobytes("png")
        base64_data = base64.b64encode(img_bytes).decode("utf-8")

        images.append({
            "page": page_num + 1,
            "data": base64_data
        })

    doc.close()
    print(f"총 {len(images)}개 페이지 변환 완료\n")
    return images


def parse_page_with_gemini(image_data: str, page_num: int, client) -> dict:
    """Gemini Vision API를 사용하여 페이지 파싱"""
    print(f"[Page {page_num}] Parsing with Gemini...")

    try:
        # 이미지 파트 준비
        image_part = types.Part.from_bytes(
            data=base64.b64decode(image_data),
            mime_type="image/png"
        )

        # Gemini API 호출
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[PARSING_INSTRUCTION, image_part],
            config=types.GenerateContentConfig(
                temperature=0.2,  # JSON syntax error 방지
                response_mime_type="application/json"
            )
        )

        # JSON 파싱
        content = response.text.strip()

        # 마크다운 블록 제거 (혹시 모를 경우)
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        parsed = json.loads(content)

        # 단일 객체면 배열로 변환
        if isinstance(parsed, dict):
            tables = [parsed]
        else:
            tables = parsed

        # 각 테이블에 source_page 추가
        for table in tables:
            table["source_page"] = page_num

        # 통계 계산
        total_items = sum(len(t.get("items", [])) for t in tables)

        if len(tables) > 1:
            items_per_table = [len(t.get("items", [])) for t in tables]
            print(f"[Page {page_num}] OK - {len(tables)} tables, {total_items} items total ({items_per_table})")
        else:
            print(f"[Page {page_num}] OK - {total_items} items parsed")

        return tables

    except json.JSONDecodeError as e:
        print(f"[Page {page_num}] JSON parse error: {e}")
        print(f"[Page {page_num}] Raw response: {content[:500]}")
        return [{
            "source_page": page_num,
            "error": f"JSON parse error: {e}",
            "items": []
        }]
    except Exception as e:
        print(f"[Page {page_num}] ERROR: {e}")
        return [{
            "source_page": page_num,
            "error": str(e),
            "items": []
        }]


def parse_pdf(pdf_path: str, output_dir: str, start_page: int = 1, end_page: int = None) -> dict:
    """PDF 전체를 파싱"""

    # 출력 디렉토리 생성
    os.makedirs(output_dir, exist_ok=True)

    # API 키 확인
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not found in .env")
        print("Get your API key from: https://aistudio.google.com/apikey")
        return None

    # Gemini 클라이언트 초기화
    client = genai.Client(api_key=GEMINI_API_KEY)

    # PDF를 이미지로 변환
    images = pdf_to_base64_images(pdf_path)

    # 파싱 범위 설정
    if end_page is None:
        end_page = len(images)

    images_to_parse = images[start_page - 1:end_page]

    # 결과 구조
    results = {
        "document_title": "소비자분쟁해결기준 별표2 품목별 해결기준",
        "data": [],
        "parsing_metadata": {
            "parsing_date": "2026-01-18",
            "total_pages": len(images),
            "parsed_pages": f"{start_page}-{end_page}",
            "parsing_strategy": "Google Gemini 2.5 Flash Vision API",
            "note_mapping_method": "AI-based keyword extraction with position fallback",
            "structure": "Each table as separate entry, forward-fill for empty 대분류/중분류"
        }
    }

    print(f"Gemini API를 사용하여 {len(images_to_parse)}개 페이지 파싱 시작...\n")
    print(f"Rate limit protection: {DELAY_BETWEEN_PAGES}s delay between requests\n")

    # 각 페이지 파싱
    page_count = 0
    for img in images_to_parse:
        tables = parse_page_with_gemini(img["data"], img["page"], client)

        # 각 테이블을 data 배열에 추가
        results["data"].extend(tables)
        page_count += 1

        # 중간 저장 (5페이지마다)
        if page_count % 5 == 0:
            temp_file = os.path.join(output_dir, f"temp_gemini_{start_page}-{img['page']}.json")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"[SAVE] Temp file: {temp_file}\n")

        # Rate limit 대응
        if img["page"] < end_page:
            print(f"[WAIT] {DELAY_BETWEEN_PAGES}s before next page...\n")
            time.sleep(DELAY_BETWEEN_PAGES)

    # Forward fill: 빈 대분류/중분류를 이전 값으로 채우기
    last_대분류 = ""
    last_중분류 = ""
    for table in results["data"]:
        if "error" not in table:
            if table.get("대분류"):
                last_대분류 = table["대분류"]
            else:
                table["대분류"] = last_대분류

            if table.get("중분류"):
                last_중분류 = table["중분류"]
            else:
                table["중분류"] = last_중분류

    # 최종 저장
    output_path = os.path.join(output_dir, OUTPUT_FILE)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*80}")
    print(f"파싱 완료! 결과 저장: {output_path}")
    print(f"총 {len(results['data'])}개 테이블 파싱 완료")
    print(f"{'='*80}\n")

    return results


def main():
    """메인 함수"""
    print("=" * 80)
    print("소비자분쟁해결기준 PDF 파싱 (Google Gemini 1.5 Pro Vision)")
    print("=" * 80)
    print()

    # 전체 37페이지 파싱
    results = parse_pdf(
        pdf_path=PDF_PATH,
        output_dir=OUTPUT_DIR,
        start_page=1,
        end_page=None  # 전체 파싱
    )

    if results:
        print("파싱 통계:")
        print(f"  - 총 페이지 수: {results['parsing_metadata']['total_pages']}")
        print(f"  - 파싱된 페이지: {results['parsing_metadata']['parsed_pages']}")
        print(f"  - 파싱 방식: {results['parsing_metadata']['parsing_strategy']}")

        # 에러가 있는 테이블 확인
        error_tables = [t for t in results["data"] if "error" in t]
        if error_tables:
            error_pages = list(set([t["source_page"] for t in error_tables]))
            print(f"  [!] 파싱 오류 페이지: {error_pages}")
        else:
            print(f"  [OK] 모든 테이블 파싱 성공")

        # 파싱된 테이블 및 아이템 개수 확인
        total_tables = len(results["data"])
        total_items = sum(len(t.get("items", [])) for t in results["data"] if "error" not in t)
        print(f"  - 총 테이블 개수: {total_tables}")
        print(f"  - 총 분쟁유형 개수: {total_items}")


if __name__ == "__main__":
    main()
