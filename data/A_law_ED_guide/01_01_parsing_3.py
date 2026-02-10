"""
[별표 3] 품목별 품질보증기간 및 부품보유기간 PDF 파싱 스크립트 (Google Gemini Vision)

파싱 전략:
1. PDF 각 페이지를 이미지로 변환
2. Gemini 2.5 Flash Vision API를 사용하여 구조화된 JSON으로 추출
3. 품목 = 소분류, 품질보증기간 내 ◦는 condition, */**는 note
"""

import json
import base64
import os
from dotenv import load_dotenv
import fitz  # PyMuPDF
from google import genai
from google.genai import types
import time

# .env 파일에서 환경변수 로드
load_dotenv()

# 설정
PDF_PATH = r"C:\Users\Playdata\Desktop\project\05_5th_project\data_n_db\raw\02_Guide\소비자분쟁해결기준_별표\[별표 3] 품목별 품질보증기간 및 부품보유기간.pdf"
# 출력 디렉토리: PDF와 같은 폴더
OUTPUT_DIR = os.path.dirname(PDF_PATH)
# 출력 파일명: PDF 파일명과 동일하게 .json으로만 변경
pdf_basename = os.path.splitext(os.path.basename(PDF_PATH))[0]
OUTPUT_FILE = f"{pdf_basename}.json"

# Gemini API 키
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Rate limit 대응
DELAY_BETWEEN_PAGES = 1

# JSON 스키마 정의
PARSING_INSTRUCTION = """
이 이미지는 소비자분쟁해결기준 PDF의 한 페이지입니다. "품목별 품질보증기간 및 부품보유기간" 표를 분석하여 정확한 JSON으로 변환해주세요.

**중요 규칙:**

1. **표 구조 인식**:
   - 3개 열로 구성: 품목 | 품질보증기간 | 부품보유기간

2. **품목 계층 구조 - 매우 중요**:
   - **품목**: 숫자로 시작하는 최상위 항목 (예: "1. 자동차", "5. 가전제품, 사무용기기...")
   - **하위카테고리1**: 괄호 숫자로 시작 (예: "1) 완제품", "2) 핵심부품", "1) 농업용기기")
   - **하위카테고리2**: "-"로 시작하는 세부 품목 (예: "- 에어컨(냉방 전용)", "- TV, 냉장고")

3. **쉼표 구분 처리 - 매우 중요**:
   - 하위카테고리2에서 쉼표로 구분된 품목은 각각 별도 항목으로 분리
   - 예: "- TV, 냉장고" → 두 개의 별도 항목: "TV", "냉장고"
   - 예: "- 난로(전기, 가스, 기름), 선풍기" → "난로(전기, 가스, 기름)", "선풍기" (괄호 안의 쉼표는 분리 안함)

4. **품질보증기간 파싱**:
   - ◦ (원 기호)로 시작하는 줄 = 하나의 notes (내용)
   - * 또는 ** 로 시작하는 줄 = sub_notes (하위 비고)

5. **부품보유기간 파싱 - 매우 중요**:
   - ◦로 시작하는 줄 = 하나의 notes
   - 한 셀에 ◦가 1개만 있으면 → 해당 품목/하위카테고리의 모든 하위 항목에 공통 적용
   - 예: "자동차" 품목의 부품보유기간 1개 → 모든 품질보증기간 조건에 공통 적용
   - 여러 개 있으면 각 품질보증기간 조건과 1:1 매칭

6. **특수 처리**:
   - "〃" (동일 기호) → 위 항목과 동일한 값
   - 표 상단 "※" 주석은 notes 필드에 포함
   - 빈 셀은 빈 배열 또는 빈 문자열

7. **출력 형식**:
   - 유효한 JSON만 출력 (마크다운 블록 없이)
   - 각 세부 품목마다 별도 객체로 배열 반환
   - 하위카테고리2에서 쉼표로 구분된 것은 각각 별도 객체로

JSON 스키마:
{
  "items": [
    {
      "품목": "최상위 품목 (예: 1. 자동차, 5. 가전제품...). 없으면 빈 문자열",
      "하위카테고리1": "중간 카테고리 (예: 1) 완제품, 2) 핵심부품). 없으면 빈 문자열",
      "하위카테고리2": "세부 품목 (예: 에어컨(냉방 전용), TV). 쉼표 구분시 분리. 없으면 빈 문자열",
      "품질보증기간": [
        {
          "notes": "◦로 시작하는 내용 전체 텍스트",
          "sub_notes": [
            {"content": "* 또는 **로 시작하는 비고"}
          ]
        }
      ],
      "부품보유기간": [
        {
          "notes": "◦로 시작하는 내용 전체 텍스트",
          "sub_notes": []
        }
      ]
    }
  ],
  "table_notes": ["표 전체 비고 (※로 시작하는 주석 등)"]
}

**예시 1 - 단순 품목**:
| 1. 자동차 | ◦ 차체 및 일반부품: 2년<br>* 차량 출고 시 장착된... | ◦ 동일한 형식의 자동차를... |
→ {
  "품목": "1. 자동차",
  "하위카테고리1": "",
  "하위카테고리2": "",
  "품질보증기간": [{...}],
  "부품보유기간": [{...}]
}

**예시 2 - 계층 구조**:
| 5. 가전제품...<br>1) 완제품<br>- TV, 냉장고 | ◦ 1년 | ◦ 제조일로부터 9년 |
→ 두 개의 객체:
{
  "품목": "5. 가전제품...",
  "하위카테고리1": "1) 완제품",
  "하위카테고리2": "TV",
  "품질보증기간": [{...}],
  "부품보유기간": [{...}]
},
{
  "품목": "5. 가전제품...",
  "하위카테고리1": "1) 완제품",
  "하위카테고리2": "냉장고",
  "품질보증기간": [{...}],
  "부품보유기간": [{...}]
}
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
        print(f"[Page {page_num}] OK - {total_items} items parsed")

        return tables

    except json.JSONDecodeError as e:
        print(f"[Page {page_num}] JSON parse error: {e}")
        with open(f"error_page_{page_num}.txt", "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[Page {page_num}] Raw response saved to error_page_{page_num}.txt")
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
        "document_title": "소비자분쟁해결기준 별표3 품목별 품질보증기간 및 부품보유기간",
        "data": [],
        "parsing_metadata": {
            "parsing_date": "2026-01-18",
            "total_pages": len(images),
            "parsed_pages": f"{start_page}-{end_page}",
            "parsing_strategy": "Google Gemini 2.5 Flash Vision API",
            "structure": "품목(최상위) > 하위카테고리1(중간) > 하위카테고리2(세부품목, 쉼표 구분 시 분리), 품질보증기간/부품보유기간 내 ◦=notes, */**=sub_notes. 부품보유기간이 1개면 모든 하위 항목에 공통 적용"
        }
    }

    print(f"Gemini API를 사용하여 {len(images_to_parse)}개 페이지 파싱 시작...\n")
    print(f"Rate limit protection: {DELAY_BETWEEN_PAGES}s delay between requests\n")

    # 각 페이지 파싱
    page_count = 0
    for img in images_to_parse:
        tables = parse_page_with_gemini(img["data"], img["page"], client)

        # 각 테이블의 items를 data 배열에 추가
        for table in tables:
            if "error" in table:
                # 에러가 있으면 테이블 전체 추가
                results["data"].append(table)
            else:
                # items 배열의 각 항목에 source_page 추가하고 data에 추가
                for item in table.get("items", []):
                    item["source_page"] = table["source_page"]
                    # 테이블 레벨 notes가 있으면 추가
                    if table.get("notes") and not item.get("notes"):
                        item["table_notes"] = table["notes"]
                    results["data"].append(item)

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

    # Forward fill: 빈 품목/하위카테고리1을 이전 값으로 채우기
    print("\n품목/하위카테고리 forward fill 시작...")
    last_품목 = ""
    last_하위카테고리1 = ""
    for item in results["data"]:
        if "error" not in item:
            if item.get("품목"):
                last_품목 = item["품목"]
            else:
                item["품목"] = last_품목

            if item.get("하위카테고리1"):
                last_하위카테고리1 = item["하위카테고리1"]
            else:
                # 품목이 바뀌면 하위카테고리1 리셋
                if item.get("품목") != last_품목:
                    last_하위카테고리1 = ""
                item["하위카테고리1"] = last_하위카테고리1
    print("품목/하위카테고리 forward fill 완료\n")

    # 부품보유기간 공통 적용 로직
    print("\n부품보유기간 공통 적용 시작...")
    품목별_부품보유기간 = {}

    # 1단계: 품목별로 부품보유기간 수집
    for item in results["data"]:
        if "error" in item:
            continue

        품목 = item.get("품목", "")
        하위카테고리1 = item.get("하위카테고리1", "")
        부품보유기간 = item.get("부품보유기간", [])

        # 부품보유기간이 있으면 저장
        if 부품보유기간 and len(부품보유기간) > 0:
            key = f"{품목}||{하위카테고리1}"
            if key not in 품목별_부품보유기간:
                품목별_부품보유기간[key] = 부품보유기간

    # 2단계: 부품보유기간이 없는 항목에 공통 적용
    for item in results["data"]:
        if "error" in item:
            continue

        품목 = item.get("품목", "")
        하위카테고리1 = item.get("하위카테고리1", "")
        부품보유기간 = item.get("부품보유기간", [])

        # 부품보유기간이 없거나 비어있으면 공통 부품보유기간 적용
        if not 부품보유기간 or len(부품보유기간) == 0:
            # 하위카테고리1 레벨에서 찾기
            key = f"{품목}||{하위카테고리1}"
            if key in 품목별_부품보유기간:
                item["부품보유기간"] = 품목별_부품보유기간[key]
            # 품목 레벨에서 찾기 (하위카테고리1이 빈 문자열인 경우)
            elif f"{품목}||" in 품목별_부품보유기간:
                item["부품보유기간"] = 품목별_부품보유기간[f"{품목}||"]

    print("부품보유기간 공통 적용 완료\n")

    # 최종 저장
    output_path = os.path.join(output_dir, OUTPUT_FILE)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*80}")
    print(f"파싱 완료! 결과 저장: {output_path}")
    total_items = len([item for item in results["data"] if "error" not in item])
    print(f"총 {total_items}개 품목 파싱 완료")
    print(f"{'='*80}\n")

    return results


def main():
    """메인 함수"""
    print("=" * 80)
    print("[별표 3] 품목별 품질보증기간 및 부품보유기간 PDF 파싱")
    print("Google Gemini 2.5 Flash Vision API")
    print("=" * 80)
    print()

    # 전체 페이지 파싱
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

        # 파싱된 품목 개수 확인
        total_items = len([item for item in results["data"] if "error" not in item])
        print(f"  - 총 품목 개수: {total_items}")


if __name__ == "__main__":
    main()
