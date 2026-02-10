"""
2022년 전자거래 조정사례 Gemini API 파싱 (2021년 사례 포함)

주요 기능:
- Gemini API를 사용한 PDF 파싱
- 자동 케이스 경계 탐색 (사건번호 기반)
- 두 가지 케이스 타입 처리: 조정 사례, 사무국 합의권고 사례
- number 필드: 숫자(정수)로 저장 (예: 1, 2, 3...)
- judgement 처리 규칙:
  * dict 형태로 오면 문자열로 변환
- 필드 순서: claims -> judgement(or order/reason) -> result

사용 방법:
1. .env 파일에 GEMINI_API_KEY 설정
2. PDF 경로 확인
3. python 01_03_parsing_adjustment_2_2022.py 실행
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
    """케이스 경계 자동 탐색 - 2022년 패턴: "사례 1", "사례 2" 형식 + 섹션 구분"""
    doc = fitz.open(pdf_path)
    boundaries = []
    section_markers = {}  # page_num -> section_type (조정 or 합의권고)

    # 2022년 패턴: "사례 1", "사례 2" 형식
    case_pattern = re.compile(r'^사례\s+\d+')
    section1_pattern = re.compile(r'Ⅰ\.\s*조정\s*사례')
    section2_pattern = re.compile(r'Ⅱ\.\s*사무국\s*합의권고\s*사례')

    total_pages = len(doc)
    print(f"PDF 페이지 수: {total_pages}")
    print("케이스 경계 탐색 중...")

    current_section = None
    section1_start = None
    section2_start = None

    # 섹션 헤더 찾기
    for page_num in range(1, total_pages):
        text = doc[page_num].get_text()
        if section1_pattern.search(text):
            section1_start = page_num
            print(f"  조정 사례 섹션 시작: Page {page_num}")
        if section2_pattern.search(text):
            section2_start = page_num
            print(f"  합의권고 사례 섹션 시작: Page {page_num}")

    # 케이스 경계 찾기
    for page_num in range(1, total_pages):
        text = doc[page_num].get_text()
        lines = text.split('\n')

        # 현재 섹션 판단
        if section2_start and page_num >= section2_start:
            current_section = "합의권고"
        elif section1_start and page_num >= section1_start:
            current_section = "조정"

        for line in lines:
            line_stripped = line.strip()
            # "사례 1", "사례 2" 패턴 매칭
            if case_pattern.match(line_stripped):
                boundaries.append(page_num)
                section_markers[page_num] = current_section
                print(f"  Page {page_num} [{current_section}]: {line_stripped[:60]}...")
                break

    doc.close()

    # 페이지 범위로 변환
    case_ranges = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else total_pages
        case_type = section_markers.get(start, "조정")
        case_ranges.append((start, end, case_type))

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

    if case_type == "합의권고":
        prompt = """이 이미지들은 2022년 전자거래 분쟁조정 사례집의 사무국 합의권고 사례입니다.
다음 JSON 형식으로 **원문 그대로** 추출하세요:

{
  "case_number": "사건번호 (없으면 빈 문자열)",
  "method": "조정방법 (없으면 null)",
  "title": "사건명칭",
  "case_type": "합의권고",
  "printed_page_number": "인쇄된 페이지 번호",
  "overview": "1. 사건 개요 섹션의 원문 전체 (제목 제외, 내용만)",
  "claims": {
    "applicant": ["2. 양 당사자 주장의 가. 신청인의 주장 원문 전체"],
    "respondent": ["2. 양 당사자 주장의 나. 피신청인의 주장 원문 전체"]
  },
  "judgement": "3. 합의권고 섹션 전체 원문 (모든 내용 포함)",
  "result": "4. 처리결과 섹션 원문 (예: '합의종결', '조정이첩' 등)"
}

**중요 지침**:
1. 모든 내용을 원문 그대로 추출 (요약, 의역, 표준화 절대 금지)
2. 줄바꿈과 문단 구조 유지
3. 섹션 제목(1., 2., 3., 4., 가., 나. 등)은 내용에 포함
4. 빠진 내용 없이 완전하게 추출
5. case_number가 명시되지 않으면 빈 문자열로
6. method가 없으면 null로 설정
7. judgement는 "3. 합의권고" 섹션 전체를 포함
8. result는 원문 그대로 추출
9. JSON 형식을 정확히 지켜주세요
10. 특수문자나 따옴표는 적절히 이스케이프 처리"""
    else:  # 조정
        prompt = """이 이미지들은 2022년 전자거래 분쟁조정 사례집의 조정 사례입니다.
다음 JSON 형식으로 **원문 그대로** 추출하세요:

{
  "case_number": "사건번호 (없으면 빈 문자열)",
  "method": "조정방법 (없으면 null)",
  "title": "사건명칭",
  "case_type": "조정",
  "printed_page_number": "인쇄된 페이지 번호",
  "overview": "1. 사건 개요 섹션의 원문 전체 (제목 제외, 내용만)",
  "claims": {
    "applicant": ["2. 양 당사자 주장의 가. 신청인의 주장 원문 전체"],
    "respondent": ["2. 양 당사자 주장의 나. 피신청인의 주장 원문 전체"]
  },
  "judgement": {
    "reason": "3. 조정부 판단 섹션 원문 전체 (가. 관련 법률, 나. 판단 등 모든 내용 포함)",
    "order": "4. 조정결정 섹션 원문 전체"
  },
  "result": "5. 조정결과 섹션 원문 (예: '조정안 수락', '조정안 불수락', '조정불응' 등 원문 그대로)"
}

**중요 지침**:
1. 모든 내용을 원문 그대로 추출 (요약, 의역, 표준화 절대 금지)
2. 줄바꿈과 문단 구조 유지
3. 섹션 제목(1., 2., 3., 4., 5., 가., 나. 등)은 내용에 포함
4. 빠진 내용 없이 완전하게 추출
5. case_number가 명시되지 않으면 빈 문자열로
6. method가 없으면 null로 설정
7. judgement는 dict 형태로 reason(3. 조정부 판단)과 order(4. 조정결정)를 분리
8. result는 "5. 조정결과" 섹션을 원문 그대로 추출
9. JSON 형식을 정확히 지켜주세요
10. 특수문자나 따옴표는 적절히 이스케이프 처리"""

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
    - 조정 사례: dict 형태 유지 (reason, order)
    - 합의권고 사례: 문자열 형태 유지
    - Gemini가 judgment 또는 judgement로 반환할 수 있으므로 통일
    """
    # judgment -> judgement로 변환 (철자 통일)
    if 'judgment' in case_data:
        case_data['judgement'] = case_data['judgment']
        del case_data['judgment']

    case_type = case_data.get('case_type', '')

    # 조정 사례: judgement를 dict 형태로 유지
    if case_type == '조정':
        if 'judgement' in case_data and isinstance(case_data['judgement'], dict):
            # 이미 dict 형태이면 그대로 유지
            pass
        elif 'judgement' in case_data and case_data['judgement'] is None:
            case_data['judgement'] = {"reason": "", "order": ""}

    # 합의권고 사례: judgement를 문자열로 유지
    else:
        if 'judgement' in case_data and isinstance(case_data['judgement'], dict):
            # dict 형태로 왔다면 문자열로 변환
            judgement_dict = case_data['judgement']
            parts = []

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
    pdf_path = Path("01_B_parsed/02_02_AdjustmentCase/02_kisa/2022년 전자거래 분쟁조정 사례집.pdf")
    output_path = Path("01_B_parsed/02_02_AdjustmentCase/02_kisa/2022년 전자거래 조정사례.json")

    if not pdf_path.exists():
        print(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")
        return

    print("="*80)
    print("2022년 전자거래 조정사례 Gemini API 파싱")
    print("="*80)

    # 자동 케이스 경계 탐색
    case_ranges = find_case_boundaries(str(pdf_path))

    adjustment_count = sum(1 for _, _, ct in case_ranges if ct == "조정")
    recommendation_count = sum(1 for _, _, ct in case_ranges if ct == "합의권고")

    print(f"\n총 사례: {len(case_ranges)}개")
    print(f"  - 조정 사례: {adjustment_count}개")
    print(f"  - 합의권고 사례: {recommendation_count}개")
    print("="*80)

    all_cases = []

    # 전체 사례 파싱
    print("\n[사례 파싱]")
    print("-"*80)

    for i, (start_page, end_page, case_type) in enumerate(case_ranges, 1):
        print(f"\n사례 {i}/{len(case_ranges)} [{case_type}] (Pages {start_page}-{end_page-1})")

        images = pdf_pages_to_images(str(pdf_path), start_page, end_page, dpi=150)
        print(f"  이미지 변환: {len(images)}개 페이지")

        case_data = parse_case_with_gemini(images, case_type=case_type)

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
    print(f"파싱 완료: {len(all_cases)}/{len(case_ranges)}")

    # 후처리: case_number 정규화
    print("\n[후처리: case_number 정규화]")
    for i, case in enumerate(all_cases, 1):
        old_case_number = case.get('case_number', '')
        case['case_number'] = str(i)
        if old_case_number != str(i):
            print(f"  Case {i}: '{old_case_number}' -> '{case['case_number']}'")

    # 통계 계산
    final_adjustment_count = sum(1 for c in all_cases if c.get('case_type') == "조정")
    final_recommendation_count = sum(1 for c in all_cases if c.get('case_type') == "합의권고")

    # 결과 생성
    result = {
        "year": "2022",
        "total_cases": len(all_cases),
        "parsing_statistics": {
            "text_parsed": 0,
            "vision_parsed": 0,
            "gemini_parsed": len(all_cases),
            "complete_cases": len(all_cases),
            "recommendation_cases": final_recommendation_count,
            "adjustment_cases": final_adjustment_count
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
    print(f"  - 조정 사례: {result['parsing_statistics']['adjustment_cases']}개")
    print(f"  - 합의권고 사례: {result['parsing_statistics']['recommendation_cases']}개")
    print(f"  - number 범위: 1-{len(all_cases)}")
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

        # judgement 체크 (dict 또는 문자열)
        judgement = case.get('judgement')
        if not judgement:
            issues.append('조정부 판단')
        elif isinstance(judgement, dict):
            if not judgement.get('reason') and not judgement.get('order'):
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
        print("  모든 사례 완벽하게 파싱됨!")
    else:
        print(f"\n  불완전한 사례: {incomplete_count}개")

    # 각 사례의 내용 길이 확인
    print("\n[파싱된 내용 길이 확인]")
    for case in all_cases:
        number = case.get('number')
        title = case.get('title', 'N/A')[:40]
        overview_len = len(case.get('overview', ''))

        # judgement 길이 계산 (dict 또는 문자열)
        judgement = case.get('judgement', '')
        if isinstance(judgement, dict):
            reason_len = len(judgement.get('reason', ''))
            order_len = len(judgement.get('order', ''))
            judgement_len = reason_len + order_len
        else:
            judgement_len = len(judgement)

        print(f"  [{number}] {title}")
        print(f"      개요: {overview_len}자, 판단: {judgement_len}자")

    print("\n파싱 완료!")


if __name__ == "__main__":
    main()
