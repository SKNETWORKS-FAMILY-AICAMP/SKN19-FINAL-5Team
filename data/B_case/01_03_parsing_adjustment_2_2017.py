"""
2017년 전자거래 조정사례 Gemini API 파싱 (권고 13개 + 조정 3개)

주요 기능:
- Gemini API를 사용한 PDF 파싱
- 자동 케이스 경계 탐색 (사건번호 기반)
- number 필드: 숫자(정수)로 저장 (예: 1, 2, 3...)
- judgement 처리 규칙:
  * "주문"이라는 단어가 있으면: order와 reason으로 분리
  * "주문"이 없으면: judgement에 통합
- 필드 순서: claims -> judgement(or order/reason) -> result

사용 방법:
1. .env 파일에 GEMINI_API_KEY 설정
2. PDF 경로 확인
3. python 01_03_parsing_adjustment_2_2017.py 실행
"""
import fitz
import json
import os
import re
from pathlib import Path
from PIL import Image
import io
import google.generativeai as genai
from dotenv import load_dotenv
import time

load_dotenv(dotenv_path="../.env")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))


def find_case_boundaries(pdf_path):
    """사건번호를 기반으로 케이스 경계 자동 탐색"""
    doc = fitz.open(pdf_path)
    boundaries = []

    # 권고 사례는 사건번호가 없을 수 있으므로 "사건명칭:" 패턴도 사용
    case_number_pattern = re.compile(r'사건번호:\s*(CA\d{2}-\d{5})')
    case_title_pattern = re.compile(r'사건명칭:\s*([^\n]+)')

    print(f"PDF 페이지 수: {len(doc)}")
    print("케이스 경계 탐색 중...")

    for page_num in range(len(doc)):
        text = doc[page_num].get_text()
        # 사건번호 또는 사건명칭이 있는 페이지를 케이스 시작으로 간주
        if case_number_pattern.search(text) or (case_title_pattern.search(text) and "1. 사건" in text):
            boundaries.append(page_num)

    doc.close()

    # 페이지 범위로 변환
    case_ranges = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(doc)
        case_ranges.append((start, end))

    print(f"발견된 케이스: {len(case_ranges)}개")
    return case_ranges


def detect_case_type(text):
    """텍스트에서 권고/조정 자동 판별"""
    # result 관련 키워드로 판별
    if re.search(r'4\.\s*조정안\s*권고\s*결과', text):
        return "권고"
    elif re.search(r'4\.\s*합의\s*결과', text):
        return "권고"
    elif re.search(r'4\.\s*조정\s*결과', text):
        return "조정"
    elif re.search(r'3\.\s*조정\s*결과', text):
        return "조정"
    else:
        # 사건번호가 있으면 조정, 없으면 권고
        if re.search(r'사건번호:\s*CA\d{2}-\d{5}', text):
            return "조정"
        else:
            return "권고"


def pdf_pages_to_images(pdf_path, start_page, end_page, dpi=150):
    """PDF 페이지들을 이미지로 변환"""
    doc = fitz.open(pdf_path)
    images = []

    for page_num in range(start_page, min(end_page, len(doc))):
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))
        images.append(img)

    doc.close()
    return images


def parse_case_with_gemini(images, case_type="권고"):
    """Gemini API로 케이스 파싱"""

    if case_type == "권고":
        prompt = """이 이미지들은 전자거래 분쟁조정 사례집의 권고 사례입니다.
다음 JSON 형식으로 **원문 그대로** 추출하세요:

{
  "case_number": "사건번호 (없으면 null)",
  "method": "조정방법 (없으면 null)",
  "title": "사건명칭",
  "case_type": "권고",
  "printed_page_number": "인쇄된 페이지 번호",
  "overview": "1. 사건개요 원문 전체",
  "claims": {
    "applicant": ["가. 신청인 주장 원문 전체"],
    "respondent": ["나. 피신청인 주장 원문 전체"]
  },
  "judgment": {
    "order": "가. 합의 권고안 또는 주문 원문 전체",
    "reason": "나. 이유 원문 전체"
  },
  "result": "4. 합의 결과 또는 권고 결과 원문"
}

**중요**:
- 모든 내용을 원문 그대로 추출 (요약 금지)
- 줄바꿈과 문단 구조 유지
- 빠진 내용 없이 완전하게 추출
- 없는 필드는 null로 설정
- JSON 형식을 정확히 지켜주세요"""
    else:  # 조정
        prompt = """이 이미지들은 전자거래 분쟁조정 사례집의 조정 사례입니다.
다음 JSON 형식으로 **원문 그대로** 추출하세요:

{
  "case_number": "사건번호 (예: CA15-00001)",
  "method": "조정방법 (예: 서면조정)",
  "title": "사건명칭",
  "case_type": "조정",
  "printed_page_number": "인쇄된 페이지 번호",
  "overview": "1. 사건개요 원문 전체",
  "claims": {
    "applicant": ["가. 신청인 주장 원문 전체"],
    "respondent": ["나. 피신청인 주장 원문 전체"]
  },
  "judgment": {
    "order": "가. 주문 원문 전체",
    "reason": "나. 이유 원문 전체"
  },
  "result": "4. 조정 결과 원문"
}

**중요**:
- 모든 내용을 원문 그대로 추출 (요약 금지)
- 줄바꿈과 문단 구조 유지
- 빠진 내용 없이 완전하게 추출
- JSON 형식을 정확히 지켜주세요"""

    try:
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        response = model.generate_content([prompt] + images)
        text = response.text.strip()

        # JSON 추출
        if '```json' in text:
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
            if json_match:
                text = json_match.group(1)

        data = json.loads(text)
        data["parsing_method"] = "gemini"

        return data

    except Exception as e:
        print(f"    오류: {str(e)}")
        return None


def process_judgement_field(case_data):
    """
    judgement 필드 처리:
    - "주문"이라는 단어가 order에 있으면 order와 reason으로 분리
    - "주문"이 없으면 judgement로 통합
    """
    if 'judgment' in case_data:
        judgment = case_data['judgment']

        if isinstance(judgment, dict):
            order = judgment.get('order', '')
            reason = judgment.get('reason', '')

            # order에 "주문"이라는 단어가 있는지 확인
            if order and "주문" in order:
                # "주문"이 있으면 order와 reason으로 분리
                case_data['order'] = order
                case_data['reason'] = reason
            else:
                # "주문"이 없으면 통합
                if order and reason:
                    case_data['judgement'] = f"{order}\n\n{reason}"
                elif order:
                    case_data['judgement'] = order
                elif reason:
                    case_data['judgement'] = reason
                else:
                    case_data['judgement'] = ""
        else:
            case_data['judgement'] = str(judgment) if judgment else ""

        # 원본 judgment 필드 삭제
        del case_data['judgment']

    return case_data


def reorder_case_fields(case_data):
    """
    필드 순서 재정렬: claims -> judgement (or order/reason) -> result
    """
    field_order = [
        "case_number",
        "method",
        "title",
        "case_type",
        "printed_page_number",
        "overview",
        "claims",
        "judgement",  # judgement 먼저
        "order",      # 또는 order
        "reason",     # 그리고 reason
        "result",
        "parsing_method",
        "number",
        "page_start",
        "page_end"
    ]

    ordered_case = {}
    for field in field_order:
        if field in case_data:
            ordered_case[field] = case_data[field]

    # 혹시 누락된 필드가 있다면 추가
    for key, value in case_data.items():
        if key not in ordered_case:
            ordered_case[key] = value

    return ordered_case


def main():
    pdf_path = Path("01_B_parsed/02_02_AdjustmentCase/02_kisa/2017년 전자거래 분쟁조정 사례집.pdf")
    output_path = Path("01_B_parsed/02_02_AdjustmentCase/02_kisa/2017년 전자거래 조정사례.json")

    if not pdf_path.exists():
        print(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")
        return

    print("="*80)
    print("2017년 전자거래 조정사례 Gemini API 파싱")
    print("="*80)

    # 자동 케이스 경계 탐색
    case_ranges = find_case_boundaries(str(pdf_path))

    print(f"\n총 케이스: {len(case_ranges)}개")
    print("="*80)

    all_cases = []

    # 케이스 타입별 카운터
    recommendation_count = 0
    adjustment_count = 0

    # 모든 케이스 파싱
    print("\n[케이스 파싱]")
    print("-"*80)

    for i, (start_page, end_page) in enumerate(case_ranges, 1):
        print(f"\n케이스 {i}/{len(case_ranges)} (Pages {start_page}-{end_page-1})")

        # 첫 페이지에서 케이스 타입 자동 판별
        doc = fitz.open(str(pdf_path))
        first_page_text = doc[start_page].get_text()
        doc.close()

        case_type = detect_case_type(first_page_text)
        print(f"  감지된 타입: {case_type}")

        images = pdf_pages_to_images(str(pdf_path), start_page, end_page, dpi=150)
        print(f"  이미지 변환: {len(images)}개 페이지")

        case_data = parse_case_with_gemini(images, case_type=case_type)

        if case_data:
            # 케이스 타입별 number 부여
            if case_type == "권고":
                recommendation_count += 1
                case_data["number"] = recommendation_count
            else:
                adjustment_count += 1
                case_data["number"] = adjustment_count

            case_data["page_start"] = start_page
            case_data["page_end"] = end_page - 1

            # case_number 처리 (권고는 숫자, 조정은 CA 번호)
            if case_type == "권고":
                case_data["case_number"] = str(case_data["number"])
            # 조정은 파싱된 case_number 그대로 사용

            # judgement 필드 처리
            case_data = process_judgement_field(case_data)

            # 필드 순서 재정렬
            case_data = reorder_case_fields(case_data)

            title = case_data.get('title', 'N/A')
            case_num = case_data.get('case_number', 'N/A')
            print(f"  [OK] {case_num}: {title[:40]}")
            print(f"  개요: {len(case_data.get('overview') or '')} 자")

            all_cases.append(case_data)
        else:
            print(f"  [FAIL]")

        # Rate limit 회피
        if i < len(case_ranges):
            time.sleep(2)

    print("\n" + "-"*80)
    print(f"파싱 완료: {len(all_cases)}/{len(case_ranges)}")
    print(f"  - 권고: {recommendation_count}개")
    print(f"  - 조정: {adjustment_count}개")

    # 결과 생성
    result = {
        "year": "2017",
        "total_cases": len(all_cases),
        "parsing_statistics": {
            "text_parsed": 0,
            "vision_parsed": 0,
            "gemini_parsed": len(all_cases),
            "complete_cases": len(all_cases),
            "recommendation_cases": recommendation_count,
            "adjustment_cases": adjustment_count
        },
        "cases": all_cases
    }

    # 저장
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n" + "="*80)
    print("최종 결과")
    print("="*80)
    print(f"저장: {output_path}")
    print(f"총 사례: {result['total_cases']}개")
    print(f"  - 권고 사례: {result['parsing_statistics']['recommendation_cases']}개 (number: 1-{recommendation_count})")
    print(f"  - 조정 사례: {result['parsing_statistics']['adjustment_cases']}개 (number: 1-{adjustment_count})")
    print("="*80)

    # 완성도 체크
    print("\n[완성도 체크]")
    incomplete_count = 0

    for case in all_cases:
        issues = []
        if not case.get('title'):
            issues.append('제목')
        if not case.get('overview'):
            issues.append('사건개요')
        if not case.get('claims', {}).get('applicant'):
            issues.append('신청인 주장')
        if not case.get('claims', {}).get('respondent'):
            issues.append('피신청인 주장')

        # judgement 또는 order/reason 확인
        has_judgement = case.get('judgement') or (case.get('order') and case.get('reason'))
        if not has_judgement:
            issues.append('판단/주문')

        if not case.get('result'):
            issues.append('결과')

        if issues:
            case_type = case.get('case_type')
            number = case.get('number')
            print(f"  [{case_type} {number}] 누락: {', '.join(issues)}")
            incomplete_count += 1

    if incomplete_count == 0:
        print("  모든 사례 완벽하게 파싱됨!")
    else:
        print(f"\n  불완전한 사례: {incomplete_count}개")

    # judgement 처리 결과 확인
    print("\n[judgement 처리 결과]")
    for case in all_cases:
        case_type = case.get('case_type')
        number = case.get('number')
        has_order = 'order' in case
        has_judgement = 'judgement' in case

        if has_order:
            print(f"  [{case_type} {number}] order/reason으로 분리 (\"주문\" 키워드 발견)")
        elif has_judgement:
            print(f"  [{case_type} {number}] judgement로 통합 (\"주문\" 키워드 없음)")

    print("\n파싱 완료!")


if __name__ == "__main__":
    main()
