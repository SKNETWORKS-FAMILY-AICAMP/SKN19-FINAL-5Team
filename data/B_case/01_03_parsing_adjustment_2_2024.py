"""
2024년 전자거래 조정사례 Gemini API 파싱 (조정 66개)

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
3. python 01_03_parsing_adjustment_2_2024.py 실행
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
    """케이스 경계 자동 탐색 - 2024년 패턴: "1. 제목..." 형식"""
    doc = fitz.open(pdf_path)
    boundaries = []

    # 2024년 패턴: "1. 제품 하자에 따른...", "2. 제품 하자..."
    # 숫자. 한글로 시작하는 제목
    case_pattern = re.compile(r'^\d+\.\s+[가-힣]+')

    total_pages = len(doc)
    print(f"PDF 페이지 수: {total_pages}")
    print("케이스 경계 탐색 중...")

    # 실제 사례는 페이지 1(인덱스)부터 시작 (표지 제외)
    for page_num in range(1, total_pages):
        text = doc[page_num].get_text()
        lines = text.split('\n')

        for line in lines:
            line_stripped = line.strip()
            # 케이스 번호가 1부터 시작하고, 제목이 한글로 시작
            if case_pattern.match(line_stripped):
                # "1) 사건 개요"나 "2) 양 당사자" 같은 하위 항목 제외
                if "사건" not in line_stripped and "당사자" not in line_stripped and "조정부" not in line_stripped:
                    # 제목이 충분히 긴 경우만 (10자 이상)
                    if len(line_stripped) >= 10:
                        boundaries.append(page_num)
                        print(f"  Page {page_num}: {line_stripped[:60]}...")
                        break

    doc.close()

    # 페이지 범위로 변환
    case_ranges = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else total_pages
        case_ranges.append((start, end))

    print(f"발견된 케이스: {len(case_ranges)}개")
    return case_ranges


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


def parse_case_with_gemini(images, case_type="조정"):
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
        prompt = """이 이미지들은 2024년 전자거래 분쟁조정 사례집의 조정 사례입니다.
다음 JSON 형식으로 **원문 그대로** 추출하세요:

{
  "case_number": "사건번호 (없으면 빈 문자열 또는 케이스 번호)",
  "method": "조정방법 (없으면 null)",
  "title": "사건명칭 (예: 제품 하자에 따른 환불 요청(모니터))",
  "case_type": "조정",
  "printed_page_number": "인쇄된 페이지 번호",
  "overview": "1) 사건 개요 섹션의 원문 전체 (제목 제외, 내용만)",
  "claims": {
    "applicant": ["2) 양 당사자 주장의 가. 신청인의 주장 원문 전체"],
    "respondent": ["2) 양 당사자 주장의 나. 피신청인의 주장 원문 전체"]
  },
  "judgement": "3) 조정부 판단 섹션 전체 원문 (가. 관련 법률 및 조정부 의견, 나. 조정결정 모두 포함)",
  "result": "조정 결과 (합의 종결, 합의 결렬 등)"
}

**중요 지침**:
1. 모든 내용을 원문 그대로 추출 (요약 금지)
2. 줄바꿈과 문단 구조 유지
3. 섹션 제목(1), 2), 3), 가., 나. 등)은 내용에 포함
4. 빠진 내용 없이 완전하게 추출
5. case_number가 명시되지 않으면 빈 문자열로
6. method가 없으면 null로 설정
7. judgement는 하나의 문자열로 "3) 조정부 판단" 전체를 포함
8. JSON 형식을 정확히 지켜주세요
9. 특수문자나 따옴표는 적절히 이스케이프 처리"""

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
    Gemini가 judgment 또는 judgement로 반환할 수 있으므로 통일
    """
    # judgment -> judgement로 변환 (철자 통일)
    if 'judgment' in case_data:
        case_data['judgement'] = case_data['judgment']
        del case_data['judgment']

    # judgement가 dict 형태로 왔다면 문자열로 변환
    if 'judgement' in case_data and isinstance(case_data['judgement'], dict):
        judgement_dict = case_data['judgement']
        parts = []

        # order와 reason이 있다면 결합
        if 'order' in judgement_dict and judgement_dict['order']:
            parts.append(judgement_dict['order'])
        if 'reason' in judgement_dict and judgement_dict['reason']:
            parts.append(judgement_dict['reason'])

        case_data['judgement'] = '\n\n'.join(parts) if parts else ""

    # judgement가 None이면 빈 문자열로
    if 'judgement' in case_data and case_data['judgement'] is None:
        case_data['judgement'] = ""

    return case_data


def reorder_case_fields(case_data):
    """
    필드 순서 재정렬: 2017년 JSON과 동일한 순서
    """
    field_order = [
        "case_number",
        "method",
        "title",
        "case_type",
        "printed_page_number",
        "overview",
        "claims",
        "judgement",
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
    pdf_path = Path("01_B_parsed/02_02_AdjustmentCase/02_kisa/2024년 전자거래 분쟁조정 사례집.pdf")
    output_path = Path("01_B_parsed/02_02_AdjustmentCase/02_kisa/2024년 전자거래 조정사례.json")

    if not pdf_path.exists():
        print(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")
        return

    print("="*80)
    print("2024년 전자거래 조정사례 Gemini API 파싱")
    print("="*80)

    # 자동 케이스 경계 탐색
    case_ranges = find_case_boundaries(str(pdf_path))

    print(f"\n조정 사례: {len(case_ranges)}개")
    print("="*80)

    all_cases = []

    # 조정 사례 파싱 (2024년은 조정만 있음)
    print("\n[조정 사례 파싱]")
    print("-"*80)

    for i, (start_page, end_page) in enumerate(case_ranges, 1):
        print(f"\n조정 사례 {i}/{len(case_ranges)} (Pages {start_page}-{end_page-1})")

        images = pdf_pages_to_images(str(pdf_path), start_page, end_page, dpi=150)
        print(f"  이미지 변환: {len(images)}개 페이지")

        case_data = parse_case_with_gemini(images, case_type="조정")

        if case_data:
            # number 필드 추가 (정수로 저장)
            case_data["number"] = i
            case_data["page_start"] = start_page
            case_data["page_end"] = end_page - 1

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
    print(f"조정 사례 완료: {len(all_cases)}/{len(case_ranges)}")

    # 결과 생성
    result = {
        "year": "2024",
        "total_cases": len(all_cases),
        "parsing_statistics": {
            "text_parsed": 0,
            "vision_parsed": 0,
            "gemini_parsed": len(all_cases),
            "complete_cases": len(all_cases),
            "recommendation_cases": 0,  # 2024년은 권고 없음
            "adjustment_cases": len(all_cases)
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
    print(f"  - 권고 사례: {result['parsing_statistics']['recommendation_cases']}개")
    print(f"  - 조정 사례: {result['parsing_statistics']['adjustment_cases']}개 (number: 1-{len(all_cases)})")
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
        if not case.get('judgement'):
            issues.append('조정부 판단')
        if not case.get('result'):
            issues.append('결과')

        if issues:
            case_type = case.get('case_type')
            number = case.get('number')
            title = case.get('title', 'N/A')[:30]
            print(f"  [{case_type} {number}] {title} - 누락: {', '.join(issues)}")
            incomplete_count += 1

    if incomplete_count == 0:
        print("  ✓ 모든 사례 완벽하게 파싱됨!")
    else:
        print(f"\n  불완전한 사례: {incomplete_count}개")

    # 각 사례의 내용 길이 확인
    print("\n[파싱된 내용 길이 확인]")
    for case in all_cases:
        number = case.get('number')
        title = case.get('title', 'N/A')[:40]
        overview_len = len(case.get('overview', ''))
        judgement_len = len(case.get('judgement', ''))
        print(f"  [{number}] {title}")
        print(f"      개요: {overview_len}자, 판단: {judgement_len}자")

    print("\n파싱 완료!")


if __name__ == "__main__":
    main()
