import re
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional
from io import BytesIO

import fitz  # PyMuPDF
import google.generativeai as genai
from dotenv import load_dotenv
from PIL import Image

# Load environment variables
load_dotenv()

# Configure Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# =========================================================
# Path config
# =========================================================
BASE_DIR = Path(__file__).resolve().parent
KCA_DIR = BASE_DIR / "01_B_parsed" / "02_01_SolutionCase" / "01_kca"

# PDF 파일 목록
PDF_FILES = [
    "2022년 우수 소비자분쟁 해결사례 22선.pdf",
    "2023년 우수 소비자분쟁 해결사례 23선.pdf",
    "2024년 우수 소비자분쟁 해결사례 24선.pdf",
]


# =========================================================
# Helpers
# =========================================================
def extract_year_from_filename(filename: str) -> Optional[str]:
    """파일명에서 연도 추출"""
    match = re.search(r"(20\d{2})년", filename)
    if match:
        return match.group(1)
    return None


def pdf_page_to_image(page, dpi=200) -> Image.Image:
    """PDF 페이지를 PIL Image로 변환"""
    mat = fitz.Matrix(dpi/72, dpi/72)
    pix = page.get_pixmap(matrix=mat)
    img_data = pix.tobytes("png")
    return Image.open(BytesIO(img_data))


# =========================================================
# Gemini API with improved prompt
# =========================================================
def extract_case_from_page_with_gemini(image: Image.Image, page_num: int, retry_count=3) -> Optional[Dict]:
    """Gemini Vision API를 사용하여 한 페이지에서 케이스 추출"""

    # Gemini 2.0 Flash 사용
    model = genai.GenerativeModel('gemini-2.0-flash-exp')

    # 개선된 프롬프트 v4: Few-shot 예시 추가
    prompt = """이 이미지는 소비자분쟁 해결사례 문서의 한 페이지입니다.

**CRITICAL 규칙:**
1. 표(table) 안의 내용만 추출 (페이지 하단 텍스트 무시)
2. 모든 bullet point (●, ㅇ, ○, -) 기호를 절대 삭제하지 말 것
3. 왼쪽 열의 헤더로 섹션을 구분할 것

**페이지 구조:**
- 상단: 번호 + 제목
- 중앙: 2열 표
  - 왼쪽 열: "신청 내용", "처리 과정", "처리 결과", "성과 및 의의"
  - 오른쪽 열: 각 섹션의 전체 내용
- 하단: 추가 텍스트 (표 외부) → 무시

**올바른 추출 예시 (Few-shot Example):**

예시 입력 (표 구조):
┌──────────┬────────────────────────────────┐
│ 신청 내용  │ ● 신청인은 A회사에서 상품 구매  │
│          │ ● 상품 수령 후 하자 발견        │
├──────────┼────────────────────────────────┤
│ 처리 과정  │ ● 사실관계 확인                │
│          │ ㅇ 업체에 연락                  │
│          │ - 하자 여부 검증                │
│          │ ● 합의권고안 제시              │
├──────────┼────────────────────────────────┤
│ 처리 결과  │ ● 환급 완료                    │
│          │ - 소비자에게 10만 원 환급       │
└──────────┴────────────────────────────────┘

올바른 출력 JSON:
{
  "신청 내용": "● 신청인은 A회사에서 상품 구매\n● 상품 수령 후 하자 발견",
  "처리 과정": "● 사실관계 확인\nㅇ 업체에 연락\n- 하자 여부 검증\n● 합의권고안 제시",
  "처리 결과": "● 환급 완료\n- 소비자에게 10만 원 환급"
}

주의: 모든 ●, ㅇ, ○, - 기호가 그대로 유지됩니다!

**추출 단계:**

STEP 1: 표 찾기
- 왼쪽에 "신청 내용", "처리 과정", "처리 결과"가 있는 표 확인

STEP 2: 오른쪽 셀 전체 복사
- "신청 내용" 행의 오른쪽 셀 전체 → "신청 내용"
- "처리 과정" 행의 오른쪽 셀 전체 → "처리 과정"
- "처리 결과" 행의 오른쪽 셀 전체 → "처리 결과"
- "성과 및 의의" 행 → 무시

STEP 3: 모든 기호 유지
- ● (검은 동그라미) - 절대 삭제 금지!
- ㅇ (한글 자모) - 절대 삭제 금지!
- ○ (빈 동그라미) - 절대 삭제 금지!
- - (하이픈) - 절대 삭제 금지!
- ①②③④⑤⑥⑦⑧⑨ - 그대로 유지
- 줄바꿈, 들여쓰기 - 그대로 유지

**절대 금지 사항:**
❌ 표 밖의 하단 텍스트 포함 금지
❌ bullet point (●, ㅇ, ○, -) 삭제 금지
❌ 내용 요약/생략 금지
❌ 섹션 잘못 구분 금지 (왼쪽 열 헤더만 기준)
❌ "성과 및 의의" 포함 금지

**출력 JSON:**
{
  "번호": <숫자>,
  "제목": "<제목>",
  "신청 내용": "<오른쪽 셀 내용 전체>",
  "처리 과정": "<오른쪽 셀 내용 전체>",
  "처리 결과": "<오른쪽 셀 내용 전체>"
}

케이스 페이지가 아니면 null 반환."""

    for attempt in range(retry_count):
        try:
            # Gemini API 호출
            response = model.generate_content([prompt, image])

            # JSON 파싱
            response_text = response.text.strip()

            # null 체크
            if response_text.lower() == "null":
                return None

            # Markdown 코드 블록 제거
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1])

            # JSON 파싱
            data = json.loads(response_text)

            # 번호를 int로 변환
            if "번호" in data:
                data["번호"] = int(data["번호"])

            # 유효성 검사
            required_fields = ["번호", "제목", "신청 내용", "처리 과정", "처리 결과"]
            if all(field in data and data[field] for field in required_fields):
                return data
            else:
                print(f"  [WARNING] Page {page_num}: Missing required fields")
                return None

        except json.JSONDecodeError as e:
            print(f"  [ERROR] Page {page_num}: JSON parse error - {e}")
            print(f"    Response: {response_text[:200]}")
            return None
        except Exception as e:
            error_message = str(e).lower()
            # Rate limit 에러면 재시도
            if "429" in error_message or "resource exhausted" in error_message:
                if attempt < retry_count - 1:
                    wait_time = (attempt + 1) * 5  # 5초, 10초, 15초
                    print(f"  [RETRY] Waiting {wait_time}s...", end='')
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"  [ERROR] Page {page_num}: {type(e).__name__}: {e}")
                    return None
            else:
                print(f"  [ERROR] Page {page_num}: {type(e).__name__}: {e}")
                return None

    return None


# =========================================================
# PDF parsing
# =========================================================
def parse_pdf_with_gemini(pdf_path: Path) -> Dict:
    """Gemini Vision API를 사용하여 PDF 파싱 (페이지별)"""
    print(f"Processing: {pdf_path.name}")

    # 파일명에서 연도 추출
    year = extract_year_from_filename(pdf_path.name)

    # PDF 열기
    doc = fitz.open(str(pdf_path))

    print(f"  Total pages: {len(doc)}")

    all_cases = []

    # 각 페이지를 개별 처리
    for page_num, page in enumerate(doc):
        if page_num == 0:  # 표지 스킵
            continue

        print(f"  Processing page {page_num + 1}...", end='')

        # 페이지를 이미지로 변환
        img = pdf_page_to_image(page)

        # Gemini로 케이스 추출
        case = extract_case_from_page_with_gemini(img, page_num + 1)

        if case:
            print(f" [OK] Case #{case['번호']}")
            all_cases.append(case)
        else:
            print(f" [SKIP]")

        # API Rate Limit 방지 (매 요청마다 1초 대기)
        time.sleep(1)

    doc.close()

    # 번호순 정렬
    all_cases.sort(key=lambda x: x.get("번호", 0))

    result = {
        "연도": year,
        "파일명": pdf_path.name,
        "사례": all_cases
    }

    return result


# =========================================================
# Main
# =========================================================
def main():
    """메인 실행 함수"""
    for pdf_filename in PDF_FILES:
        pdf_path = KCA_DIR / pdf_filename

        if not pdf_path.exists():
            print(f"[SKIP] 파일을 찾을 수 없습니다: {pdf_path}")
            continue

        try:
            print(f"\n{'='*80}")
            print(f"Processing: {pdf_filename}")
            print(f"{'='*80}\n")

            # PDF 파싱 (Gemini Vision API 사용)
            data = parse_pdf_with_gemini(pdf_path)

            # JSON 파일명 생성
            year = data.get("연도", "Unknown")
            output_filename = f"{year}년_우수해결사례.json"
            output_path = KCA_DIR / output_filename

            # JSON 저장
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"\n{'='*80}")
            print(f"[OK] {output_filename} 저장 완료")
            print(f"     사례 수: {len(data.get('사례', []))}")
            print(f"{'='*80}\n")

            # 케이스 2번 검증
            if len(data.get('사례', [])) >= 2:
                case2 = data['사례'][1]
                print(f"\n케이스 2번 검증:")
                print(f"  번호: {case2['번호']}")
                print(f"  제목: {case2['제목']}")
                print(f"\n  신청 내용 (처음 200자):")
                print(f"    {case2['신청 내용'][:200]}")
                print(f"\n  처리 과정 (처음 200자):")
                print(f"    {case2['처리 과정'][:200]}")
                print(f"\n  처리 결과 (마지막 150자):")
                print(f"    ...{case2['처리 결과'][-150:]}")

        except Exception as e:
            print(f"\n[ERROR] {pdf_filename} 처리 중 오류 발생:")
            print(f"  {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
