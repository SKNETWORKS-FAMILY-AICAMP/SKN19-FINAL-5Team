"""
[별표 1] 대상풍목 PDF 파싱 스크립트 (Google Gemini Vision)

파싱 전략:
1. PDF를 이미지로 변환
2. Gemini 2.5 Flash Vision API를 사용하여 구조화된 JSON으로 추출
"""

import os
import sys
import json
import time
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai

# Windows 콘솔 인코딩 설정
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# .env 파일 로드
load_dotenv()


class PDFToJSONParser:
    """Gemini API를 사용한 PDF to JSON 파서"""

    def __init__(self, api_key: str = None):
        """
        Args:
            api_key: Gemini API 키 (없으면 환경변수에서 로드)
        """
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다. 환경변수에 설정하거나 인자로 전달해주세요.")

        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        print("✓ Gemini API 초기화 완료")

    def upload_pdf(self, pdf_path: Path):
        """PDF 파일을 Gemini에 업로드"""
        print(f"PDF 파일 업로드 중: {pdf_path.name}")

        uploaded_file = genai.upload_file(path=str(pdf_path))
        print(f"✓ 업로드 완료: {uploaded_file.name}")

        # 파일 처리 대기
        while uploaded_file.state.name == "PROCESSING":
            print("파일 처리 중...")
            time.sleep(2)
            uploaded_file = genai.get_file(uploaded_file.name)

        if uploaded_file.state.name == "FAILED":
            raise ValueError(f"파일 처리 실패: {uploaded_file.name}")

        print("✓ 파일 처리 완료")
        return uploaded_file

    def create_parsing_prompt(self) -> str:
        """파싱을 위한 프롬프트 생성"""
        prompt = """
이 PDF 문서는 "소비자분쟁해결기준 별표 1 - 대상 품목" 표입니다.
PDF의 모든 데이터를 아래 JSON 구조로 정확하게 변환해주세요.

**중요 지침:**
1. 모든 데이터를 빠짐없이 추출해주세요
2. 품목은 "등"을 포함하여 정확히 추출해주세요
3. 섹션 I은 "상품(재화) 부문", 섹션 II는 "서비스업 부문"입니다
4. 카테고리 번호는 각 섹션 내에서 1부터 시작합니다
5. items 배열이 비어있는 경우 빈 배열 []로 표시해주세요

**JSON 구조 예시:**
{
  "document_title": "소비자분쟁해결기준 별표 1 - 대상 품목",
  "sections": [
    {
      "section_id": "I",
      "section_name": "상품(재화) 부문",
      "categories": [
        {
          "category_number": 1,
          "category_name": "농·수·축산물",
          "subcategories": [
            {
              "subcategory_name": "란류",
              "items": ["계란", "메추리알 등"]
            },
            {
              "subcategory_name": "육류",
              "items": ["소고기", "돼지고기", "닭고기 등"]
            }
          ]
        }
      ]
    },
    {
      "section_id": "II",
      "section_name": "서비스업 부문",
      "categories": [
        {
          "category_number": 1,
          "category_name": "전기·통신·가스서비스 관련",
          "subcategories": [
            {
              "subcategory_name": "전기서비스",
              "items": []
            },
            {
              "subcategory_name": "이동통신서비스업",
              "items": ["무선호출서비스", "이동전화서비스"]
            }
          ]
        }
      ]
    }
  ]
}

**응답은 JSON 코드만 출력해주세요. 다른 설명이나 마크다운 코드블록 없이 순수 JSON만 출력하세요.**
"""
        return prompt

    def parse_pdf_to_json(self, pdf_path: Path) -> dict:
        """PDF 파일을 JSON으로 파싱"""
        print("\n=== PDF 파싱 시작 ===\n")

        # PDF 업로드
        uploaded_file = self.upload_pdf(pdf_path)

        # 프롬프트 생성
        prompt = self.create_parsing_prompt()

        # Gemini API 호출
        print("\nGemini API 호출 중...")
        response = self.model.generate_content([uploaded_file, prompt])

        print("✓ 응답 받기 완료")

        # JSON 파싱
        response_text = response.text.strip()

        # 마크다운 코드블록 제거 (혹시 모를 경우 대비)
        if response_text.startswith('```'):
            lines = response_text.split('\n')
            response_text = '\n'.join(lines[1:-1])
            if response_text.startswith('json'):
                response_text = response_text[4:].strip()

        try:
            parsed_data = json.loads(response_text)
            print("✓ JSON 파싱 완료")
            return parsed_data
        except json.JSONDecodeError as e:
            print(f"✗ JSON 파싱 실패: {e}")
            print(f"\n응답 내용:\n{response_text[:500]}...")
            raise

    def save_json(self, data: dict, output_path: Path):
        """JSON 데이터를 파일로 저장"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✓ JSON 파일 저장 완료: {output_path}")

    def validate_json_structure(self, data: dict) -> bool:
        """JSON 구조 검증"""
        print("\n=== JSON 구조 검증 ===")

        required_keys = ['document_title', 'sections']
        for key in required_keys:
            if key not in data:
                print(f"✗ 필수 키 누락: {key}")
                return False

        total_categories = 0
        total_subcategories = 0
        total_items = 0

        for section in data['sections']:
            print(f"\n섹션: {section['section_id']} - {section['section_name']}")
            print(f"  카테고리 수: {len(section['categories'])}")

            total_categories += len(section['categories'])

            for category in section['categories']:
                total_subcategories += len(category['subcategories'])
                for subcategory in category['subcategories']:
                    total_items += len(subcategory['items'])

        print(f"\n[전체 통계]")
        print(f"  총 섹션: {len(data['sections'])}")
        print(f"  총 카테고리: {total_categories}")
        print(f"  총 서브카테고리: {total_subcategories}")
        print(f"  총 품목: {total_items}")

        print("\n✓ JSON 구조 검증 완료")
        return True


def main():
    """메인 실행 함수"""
    # 경로 설정
    base_dir = Path(__file__).parent
    pdf_path = base_dir / 'raw' / '02_Guide' / '소비자분쟁해결기준_별표' / '[별표 1] 대상품목.pdf'
    output_path = base_dir / 'raw' / '02_Guide' / '소비자분쟁해결기준_별표' / '[별표 1] 대상품목.json'

    # PDF 파일 존재 확인
    if not pdf_path.exists():
        print(f"✗ PDF 파일을 찾을 수 없습니다: {pdf_path}")
        return

    print(f"대상 PDF: {pdf_path.name}\n")

    # API 키 설정 확인
    if not os.getenv('GEMINI_API_KEY'):
        print("=" * 60)
        print("✗ GEMINI_API_KEY를 찾을 수 없습니다.")
        print("\n.env 파일에 GEMINI_API_KEY가 설정되어 있는지 확인하세요.")
        print("=" * 60)
        return

    try:
        # 파서 초기화
        parser = PDFToJSONParser()

        # PDF 파싱
        parsed_data = parser.parse_pdf_to_json(pdf_path)

        # 구조 검증
        if parser.validate_json_structure(parsed_data):
            # JSON 저장
            parser.save_json(parsed_data, output_path)
            print(f"\n✓ 모든 작업 완료!")
            print(f"출력 파일: {output_path}")
        else:
            print("\n✗ JSON 구조 검증 실패")

    except Exception as e:
        print(f"\n✗ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
