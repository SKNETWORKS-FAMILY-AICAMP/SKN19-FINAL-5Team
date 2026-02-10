"""
[별표 4] 품목별 내용연수표 PDF 파싱 스크립트 (Google Gemini Vision)

파싱 전략:
1. PDF를 이미지로 변환
2. Gemini 2.5 Flash Vision API를 사용하여 구조화된 JSON으로 추출
3. 품목은 쉼표로 구분하여 각각 별도 항목으로 분리
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
PDF_PATH = r"C:\Users\Playdata\Desktop\project\05_5th_project\data_n_db\raw\02_Guide\소비자분쟁해결기준_별표\[별표 4] 품목별 내용연수표.pdf"
# 출력 디렉토리: PDF와 같은 폴더
OUTPUT_DIR = os.path.dirname(PDF_PATH)
# 출력 파일명: PDF 파일명과 동일하게 .json으로만 변경
pdf_basename = os.path.splitext(os.path.basename(PDF_PATH))[0]
OUTPUT_FILE = f"{pdf_basename}.json"

# Gemini API 키
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# JSON 스키마 정의
PARSING_INSTRUCTION = """
이 이미지는 소비자분쟁해결기준 PDF의 한 페이지입니다. "품목별 내용연수표" 표를 분석하여 정확한 JSON으로 변환해주세요.

**중요 규칙:**

1. **표 구조 인식**:
   - 2개 열로 구성: 품목 | 내용연수
   - 품목 열에는 쉼표로 구분된 여러 품목이 나열되어 있음

2. **품목 파싱 - 매우 중요**:
   - 품목 열의 각 행에서 쉼표로 구분된 품목을 각각 별도 항목으로 분리
   - 예: "침대, 책상, 장롱, 장식장, 책장" → 5개의 별도 항목
   - 괄호 안의 쉼표는 분리하지 않음
   - 예: "난로(전기, 가스, 기름), 선풍기" → "난로(전기, 가스, 기름)", "선풍기"

3. **내용연수 매핑**:
   - 품목 열의 여러 행이 하나의 내용연수를 공유할 수 있음
   - 내용연수가 명시된 행을 찾아서 해당 그룹의 모든 품목에 적용
   - 예: "농업용기기" → 특정 내용연수 (긴 텍스트)
   - 예: "침대, 책상..." ~ "라켓..." → 같은 내용연수 그룹 (내용연수가 중간에 명시됨)
   - 예: "별도의 기간을 정하지 않은 경우..." → "5년"

4. **내용연수 그룹 인식**:
   - 표를 보면 여러 행이 세로로 병합되어 하나의 내용연수를 공유함
   - 병합된 셀 범위의 모든 품목에 동일한 내용연수 적용
   - 내용연수가 비어있으면 위 또는 아래 행의 내용연수를 찾아서 적용

5. **출력 형식**:
   - 유효한 JSON만 출력 (마크다운 블록 없이)
   - 각 품목마다 별도 객체로 배열 반환

JSON 스키마:
{
  "items": [
    {
      "품목": "품목명 (예: 침대, 에어컨, 농업용기기)",
      "내용연수": "내용연수 텍스트 (예: 5년, 사업자가 품질보증서에 표시한...)"
    }
  ]
}

**예시**:

입력 표:
| 품목 | 내용연수 |
|------|---------|
| 농업용기기 | 사업자가 품질보증서에 표시한 부품보유기간으로 함... |
| 침대, 책상, 장롱 | (병합된 셀 - 아래에 내용연수가 있음) |
| TV, 냉장고 | (병합된 셀 - 아래에 내용연수가 있음) |
| ... | 10년 |

출력 JSON:
{
  "items": [
    {
      "품목": "농업용기기",
      "내용연수": "사업자가 품질보증서에 표시한 부품보유기간으로 함..."
    },
    {
      "품목": "침대",
      "내용연수": "10년"
    },
    {
      "품목": "책상",
      "내용연수": "10년"
    },
    {
      "품목": "장롱",
      "내용연수": "10년"
    },
    {
      "품목": "TV",
      "내용연수": "10년"
    },
    {
      "품목": "냉장고",
      "내용연수": "10년"
    }
  ]
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

        # 각 항목에 source_page 추가
        if "items" in parsed:
            for item in parsed["items"]:
                item["source_page"] = page_num

        # 통계 계산
        total_items = len(parsed.get("items", []))
        print(f"[Page {page_num}] OK - {total_items} items parsed")

        return parsed

    except json.JSONDecodeError as e:
        print(f"[Page {page_num}] JSON parse error: {e}")
        with open(f"error_page_{page_num}.txt", "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[Page {page_num}] Raw response saved to error_page_{page_num}.txt")
        return {
            "items": [],
            "error": f"JSON parse error: {e}"
        }
    except Exception as e:
        print(f"[Page {page_num}] ERROR: {e}")
        return {
            "items": [],
            "error": str(e)
        }


def parse_pdf(pdf_path: str, output_dir: str) -> dict:
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

    # 결과 구조
    results = {
        "document_title": "소비자분쟁해결기준 별표4 품목별 내용연수표",
        "data": [],
        "parsing_metadata": {
            "parsing_date": "2026-01-18",
            "total_pages": len(images),
            "parsing_strategy": "Google Gemini 2.5 Flash Vision API",
            "structure": "품목(쉼표 구분 시 분리) + 내용연수"
        }
    }

    print(f"Gemini API를 사용하여 {len(images)}개 페이지 파싱 시작...\n")

    # 각 페이지 파싱
    for img in images:
        parsed_data = parse_page_with_gemini(img["data"], img["page"], client)

        # items 배열의 각 항목을 data에 추가
        if "items" in parsed_data:
            results["data"].extend(parsed_data["items"])

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
    print("[별표 4] 품목별 내용연수표 PDF 파싱")
    print("Google Gemini 2.5 Flash Vision API")
    print("=" * 80)
    print()

    results = parse_pdf(pdf_path=PDF_PATH, output_dir=OUTPUT_DIR)

    if results:
        print("파싱 통계:")
        print(f"  - 총 페이지 수: {results['parsing_metadata']['total_pages']}")
        print(f"  - 파싱 방식: {results['parsing_metadata']['parsing_strategy']}")

        # 에러 확인
        error_items = [item for item in results["data"] if "error" in item]
        if error_items:
            print(f"  [!] 파싱 오류 항목: {len(error_items)}개")
        else:
            print(f"  [OK] 모든 항목 파싱 성공")

        total_items = len([item for item in results["data"] if "error" not in item])
        print(f"  - 총 품목 개수: {total_items}")


if __name__ == "__main__":
    main()
