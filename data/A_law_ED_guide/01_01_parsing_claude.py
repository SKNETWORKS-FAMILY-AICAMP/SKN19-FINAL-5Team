"""
소비자분쟁해결기준 PDF 파싱 스크립트

파싱 전략:
1. PDF 각 페이지를 이미지로 변환
2. Claude API를 사용하여 구조화된 JSON으로 추출
3. 비고 매핑: 키워드 기반 우선, 위치 기반 폴백
"""

import json
import base64
import os
from pathlib import Path
import anthropic
import fitz  # PyMuPDF

# 설정
PDF_PATH = r"C:\Users\Playdata\Desktop\project\05_5th_project\data_n_db\raw\02_Guide\소비자분쟁해결기준_별표\[별표 2] 품목별 해결기준 1.pdf"
OUTPUT_DIR = r"C:\Users\Playdata\Desktop\project\05_5th_project\data_n_db\parsed"
OUTPUT_FILE = "parsed_full.json"

# Claude API 키 (환경변수에서 가져오기)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# JSON 스키마 정의
PARSING_SCHEMA = """
파싱할 JSON 구조:
{
  "page": 페이지 번호,
  "대분류": "대분류명 (예: Ⅰ. 상품(재화))",
  "중분류": "중분류명 (예: 1. 농ㆍ수ㆍ축산물)",
  "소분류": "소분류명 (예: ⑦종묘 등)",
  "업종목록": "업종 목록 (해당되는 경우)",
  "items": [
    {
      "id": "번호",
      "dispute_type": "분쟁유형",
      "resolution": "바로 적용되는 해결기준 (조건이 없는 경우, 없으면 null)",
      "conditions": [
        {
          "condition": "조건 텍스트 (- 로 시작하는 2단계)",
          "resolution": "해결기준",
          "notes": [
            {
              "keyword": "매핑된 키워드 (키워드로 매핑된 경우, 없으면 null)",
              "content": "비고 내용",
              "matched_by": "keyword 또는 position"
            }
          ],
          "sub_conditions": [
            {
              "condition": "하위 조건 (ㆍ로 시작하는 3단계)",
              "resolution": "해결기준",
              "notes": []
            }
          ]
        }
      ],
      "notes": [
        {
          "keyword": "키워드",
          "content": "비고 내용",
          "matched_by": "keyword"
        }
      ]
    }
  ],
  "reference": {
    "근거법령": "근거 법령",
    "기타법령": "기타 법령"
  }
}

비고 매핑 규칙:
1. 비고에 특정 키워드가 있으면 해당 키워드가 등장하는 분쟁유형/해결기준/조건에 매핑
2. 같은 키워드가 여러 곳에 있으면 모두에 매핑
3. 키워드 매칭 실패 시 같은 행에 있는 항목에 매핑 (matched_by: "position")
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
    print(f"총 {len(images)}개 페이지 변환 완료")
    return images


def parse_page_with_claude(image_data: str, page_num: int, client: anthropic.Anthropic) -> dict:
    """Claude Vision API를 사용하여 페이지 파싱"""
    print(f"페이지 {page_num} 파싱 중...")

    prompt = f"""이 이미지는 소비자분쟁해결기준 문서의 {page_num}페이지입니다.

표 형식으로 구성된 이 페이지를 다음 JSON 스키마에 맞게 파싱해주세요:

{PARSING_SCHEMA}

중요한 사항:
1. 분쟁유형의 계층 구조를 정확히 인식하세요:
   - 숫자) → Level 1 (최상위)
   - - → Level 2 (조건)
   - ㆍ · • → Level 3 (하위 조건)

2. 비고(맨 오른쪽 컬럼)는 여러 행에 걸쳐 병합되어 있습니다:
   - 비고 내용에 키워드가 있으면 해당 키워드가 등장하는 항목에 매핑
   - 예: "발아 불량은..." → "발아불량"이 있는 dispute_type에 매핑
   - 예: "직접경비: 인건비..." → "직접경비"가 있는 resolution에 매핑
   - 키워드 매칭 불가시 같은 행 기준으로 매핑

3. 해결기준은 "o " 또는 "ㅇ "로 시작합니다.

4. 페이지 상단의 대분류/중분류/소분류도 추출하세요.

5. 페이지 하단의 【참고】 부분은 reference 필드에 넣으세요.

JSON만 출력하고 다른 설명은 하지 마세요."""

    message = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=4000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_data
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ]
    )

    # 응답에서 JSON 추출
    response_text = message.content[0].text

    # JSON 파싱
    try:
        # 코드 블록 제거
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        parsed_data = json.loads(response_text.strip())
        print(f"  페이지 {page_num} 파싱 완료")
        return parsed_data
    except json.JSONDecodeError as e:
        print(f"  페이지 {page_num} JSON 파싱 오류: {e}")
        print(f"  응답 내용: {response_text[:500]}...")
        return {
            "page": page_num,
            "error": str(e),
            "raw_response": response_text
        }


def parse_pdf(pdf_path: str, output_dir: str, start_page: int = 1, end_page: int = None) -> dict:
    """PDF 전체를 파싱"""

    # 출력 디렉토리 생성
    os.makedirs(output_dir, exist_ok=True)

    # Claude 클라이언트 초기화
    if not ANTHROPIC_API_KEY:
        print("오류: ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
        print("다음 명령으로 설정하세요:")
        print('  Windows: set ANTHROPIC_API_KEY=your-api-key')
        print('  Linux/Mac: export ANTHROPIC_API_KEY=your-api-key')
        return None

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # PDF를 이미지로 변환
    images = pdf_to_base64_images(pdf_path)

    # 파싱 범위 설정
    if end_page is None:
        end_page = len(images)

    images_to_parse = images[start_page - 1:end_page]

    # 각 페이지 파싱
    results = {
        "document_title": "소비자분쟁해결기준 별표2 품목별 해결기준",
        "pages": [],
        "parsing_metadata": {
            "parsing_date": "2026-01-18",
            "total_pages": len(images),
            "parsed_pages": f"{start_page}-{end_page}",
            "parsing_strategy": "Claude Vision API with structured JSON schema",
            "note_mapping_method": "Keyword-based priority, position-based fallback"
        }
    }

    for img in images_to_parse:
        page_data = parse_page_with_claude(img["data"], img["page"], client)
        results["pages"].append(page_data)

        # 중간 저장 (10페이지마다)
        if len(results["pages"]) % 10 == 0:
            temp_file = os.path.join(output_dir, f"temp_pages_{start_page}-{img['page']}.json")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"중간 저장: {temp_file}")

    # 최종 저장
    output_path = os.path.join(output_dir, OUTPUT_FILE)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n파싱 완료! 결과 저장: {output_path}")
    print(f"총 {len(results['pages'])}개 페이지 파싱 완료")

    return results


def main():
    """메인 함수"""
    print("=" * 80)
    print("소비자분쟁해결기준 PDF 파싱")
    print("=" * 80)

    # 전체 파싱 실행
    results = parse_pdf(
        pdf_path=PDF_PATH,
        output_dir=OUTPUT_DIR,
        start_page=1,
        end_page=None  # None이면 전체, 숫자 지정하면 해당 페이지까지
    )

    if results:
        print("\n파싱 통계:")
        print(f"  - 총 페이지 수: {results['parsing_metadata']['total_pages']}")
        print(f"  - 파싱된 페이지: {results['parsing_metadata']['parsed_pages']}")
        print(f"  - 파싱 방식: {results['parsing_metadata']['parsing_strategy']}")


if __name__ == "__main__":
    main()
