"""
2018년 전자거래 조정사례 Gemini API 파싱 (조정 66개)

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
3. python 01_03_parsing_adjustment_2_2018.py 실행
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
    """케이스 경계 자동 탐색 - 2018년 패턴: "사례 1", "사례 2" 형식, 조정/권고 구분"""
    doc = fitz.open(pdf_path)
    boundaries = []
    total_pages = len(doc)

    # 2018년 패턴: "사례 1", "사례 2"
    case_pattern = re.compile(r'^사례\s+\d+')
    # 섹션 구분 패턴 - 합의권고 섹션 헤더 찾기
    recommendation_section_pattern = re.compile(r'[IⅡ]{1,2}\s*합의권고사례')

    print(f"PDF 페이지 수: {total_pages}")
    print("케이스 경계 탐색 중...")

    # 먼저 합의권고 섹션이 시작하는 페이지 찾기
    recommendation_start_page = None
    for page_num in range(total_pages):
        text = doc[page_num].get_text()
        if recommendation_section_pattern.search(text):
            recommendation_start_page = page_num
            print(f"  [합의권고 섹션 헤더 발견] Page {page_num}")
            break

    print(f"  조정 섹션: 0-{recommendation_start_page-1 if recommendation_start_page else total_pages-1}")
    print(f"  권고 섹션: {recommendation_start_page if recommendation_start_page else 'N/A'}-{total_pages-1}")

    # 케이스 경계 탐색
    for page_num in range(total_pages):
        text = doc[page_num].get_text()
        lines = text.split('\n')

        for line in lines:
            line_stripped = line.strip()
            if case_pattern.match(line_stripped):
                # 페이지 번호로 섹션 구분
                if recommendation_start_page and page_num >= recommendation_start_page:
                    case_type = "권고"
                else:
                    case_type = "조정"

                boundaries.append((page_num, case_type))
                print(f"  Page {page_num} ({case_type}): {line_stripped}")
                break

    doc.close()

    # 페이지 범위로 변환 (case_type 포함)
    case_ranges = []
    for i, (start, case_type) in enumerate(boundaries):
        if i + 1 < len(boundaries):
            end = boundaries[i + 1][0]
        else:
            end = total_pages
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

    if case_type == "권고":
        prompt = """이 이미지들은 2018년 전자거래 분쟁조정 사례집의 합의권고 사례입니다.
다음 JSON 형식으로 **원문 그대로** 추출하세요:

{
  "case_number": "사건번호 (없으면 null)",
  "method": "조정방법 (없으면 null)",
  "title": "사건명칭",
  "case_type": "권고",
  "printed_page_number": "인쇄된 페이지 번호",
  "overview": "1. 사건개요 원문 전체",
  "claims": {
    "applicant": ["가. 신청인 주장 원문 전체 (2. 양 당사자 주장의 가. 신청인 주장)"],
    "respondent": ["나. 피신청인 주장 원문 전체 (2. 양 당사자 주장의 나. 피신청인 주장)"]
  },
  "judgement": "3. 합의권고 섹션 전체 원문 (가. 판단, 나. 결론 등 모두 포함)",
  "result": "4. 처리 결과 원문 (예: 합의 종결, 조정 불응 등)"
}

**중요 지침**:
1. 모든 내용을 원문 그대로 추출 (요약 금지)
2. 줄바꿈과 문단 구조 유지
3. 섹션 제목(1., 2., 3., 가., 나. 등)은 내용에 포함
4. 빠진 내용 없이 완전하게 추출
5. case_number, method가 없으면 null로 설정
6. judgement는 하나의 문자열로 "3. 합의권고" 전체를 포함
7. JSON 형식을 정확히 지켜주세요
8. 특수문자나 따옴표는 적절히 이스케이프 처리"""
    else:  # 조정
        prompt = """이 이미지들은 2018년 전자거래 분쟁조정 사례집의 조정 사례입니다.
다음 JSON 형식으로 **원문 그대로** 추출하세요:

{
  "case_number": "사건번호 (없으면 null)",
  "method": "조정방법 (예: 대면조정, 서면조정)",
  "title": "사건명칭",
  "case_type": "조정",
  "printed_page_number": "인쇄된 페이지 번호",
  "overview": "1. 사건개요 원문 전체",
  "claims": {
    "applicant": ["가. 신청인 주장 원문 전체 (2. 양 당사자 주장의 가. 신청인 주장)"],
    "respondent": ["나. 피신청인 주장 원문 전체 (2. 양 당사자 주장의 나. 피신청인 주장)"]
  },
  "judgement": {
    "reason": "3. 조정부 판단 섹션 전체 원문 (가. 적용법규, 나. 판단 등 포함, 단 '다. 결론' 또는 '라. 결론' 제외)",
    "order": "다. 결론 또는 라. 결론 등의 원문 전체 (주문 포함)"
  },
  "result": "4. 조정결과 원문 (예: 조정안 수락)"
}

**중요 지침**:
1. 모든 내용을 원문 그대로 추출 (요약 금지)
2. 줄바꿈과 문단 구조 유지
3. 섹션 제목(1., 2., 3., 가., 나., 다., 라. 등)은 내용에 포함
4. 빠진 내용 없이 완전하게 추출
5. "3. 조정부 판단"에서 "다. 결론" 또는 "라. 결론" 등을 찾아 order로 분리
6. 결론이 "다"가 아니라 "라", "마" 등일 수도 있음에 유의
7. reason에는 가., 나. 등만, order에는 결론 부분만
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
    - 조정: judgement가 dict면 reason과 order로 분리 유지
    - 권고: judgement가 문자열이면 그대로 유지
    """
    # judgment -> judgement로 변환 (철자 통일)
    if 'judgment' in case_data:
        case_data['judgement'] = case_data['judgment']
        del case_data['judgment']

    # case_type에 따라 다르게 처리
    case_type = case_data.get('case_type', '조정')

    if case_type == "조정":
        # 조정 케이스: judgement가 dict면 reason과 order로 분리
        if 'judgement' in case_data and isinstance(case_data['judgement'], dict):
            judgement_dict = case_data['judgement']

            # reason과 order 추출
            if 'reason' in judgement_dict:
                case_data['reason'] = judgement_dict['reason']
            if 'order' in judgement_dict:
                case_data['order'] = judgement_dict['order']

            # dict 형태의 judgement 삭제
            del case_data['judgement']
    else:
        # 권고 케이스: judgement가 문자열로 유지
        if 'judgement' in case_data:
            if isinstance(case_data['judgement'], dict):
                # dict로 왔다면 하나의 문자열로 통합
                judgement_dict = case_data['judgement']
                parts = []
                for key in ['order', 'reason']:
                    if key in judgement_dict and judgement_dict[key]:
                        parts.append(judgement_dict[key])
                case_data['judgement'] = '\n\n'.join(parts) if parts else ""
            elif case_data['judgement'] is None:
                case_data['judgement'] = ""

    return case_data


def reorder_case_fields(case_data):
    """
    필드 순서 재정렬:
    - 조정: claims -> reason -> order -> result
    - 권고: claims -> judgement -> result
    """
    case_type = case_data.get('case_type', '조정')

    if case_type == "조정":
        field_order = [
            "case_number",
            "method",
            "title",
            "case_type",
            "printed_page_number",
            "overview",
            "claims",
            "reason",     # 조정부 판단
            "order",      # 결론
            "result",
            "parsing_method",
            "number",
            "page_start",
            "page_end"
        ]
    else:  # 권고
        field_order = [
            "case_number",
            "method",
            "title",
            "case_type",
            "printed_page_number",
            "overview",
            "claims",
            "judgement",  # 합의권고
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
    pdf_path = Path("01_B_parsed/02_02_AdjustmentCase/02_kisa/2018년 전자거래 분쟁조정 사례집.pdf")
    output_path = Path("01_B_parsed/02_02_AdjustmentCase/02_kisa/2018년 전자거래 조정사례.json")

    if not pdf_path.exists():
        print(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")
        return

    print("="*80)
    print("2018년 전자거래 조정사례 Gemini API 파싱")
    print("="*80)

    # 자동 케이스 경계 탐색
    case_ranges = find_case_boundaries(str(pdf_path))

    print(f"\n조정 사례: {len(case_ranges)}개")
    print("="*80)

    all_cases = []
    adjustment_count = 0
    recommendation_count = 0

    # 모든 사례 파싱
    print("\n[사례 파싱]")
    print("-"*80)

    for i, (start_page, end_page, case_type) in enumerate(case_ranges, 1):
        print(f"\n사례 {i}/{len(case_ranges)} ({case_type}) (Pages {start_page}-{end_page-1})")

        images = pdf_pages_to_images(str(pdf_path), start_page, end_page, dpi=150)
        print(f"  이미지 변환: {len(images)}개 페이지")

        case_data = parse_case_with_gemini(images, case_type=case_type)

        if case_data:
            # number 필드 추가 (정수로 저장)
            case_data["number"] = i
            case_data["page_start"] = start_page
            case_data["page_end"] = end_page - 1

            # case_type 확인 및 설정
            if 'case_type' not in case_data or not case_data['case_type']:
                case_data['case_type'] = case_type

            # judgement 필드 처리
            case_data = process_judgement_field(case_data)

            # 필드 순서 재정렬
            case_data = reorder_case_fields(case_data)

            title = case_data.get('title', 'N/A')
            case_num = case_data.get('case_number', 'N/A')
            print(f"  [OK] {case_num}: {title[:40]}")
            print(f"  개요: {len(case_data.get('overview') or '')} 자")

            # 카운트 증가
            if case_data.get('case_type') == "조정":
                adjustment_count += 1
            else:
                recommendation_count += 1

            all_cases.append(case_data)
        else:
            print(f"  [FAIL]")

        # Rate limit 회피
        if i < len(case_ranges):
            time.sleep(2)

    print("\n" + "-"*80)
    print(f"사례 완료: {len(all_cases)}/{len(case_ranges)}")
    print(f"  - 조정: {adjustment_count}개")
    print(f"  - 권고: {recommendation_count}개")

    # 결과 생성
    result = {
        "year": "2018",
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
    print(f"  - 권고 사례: {result['parsing_statistics']['recommendation_cases']}개")
    print(f"  - 조정 사례: {result['parsing_statistics']['adjustment_cases']}개 (number: 1-{len(all_cases)})")
    print("="*80)

    # 완성도 체크
    print("\n[완성도 체크]")
    incomplete_count = 0

    for case in all_cases:
        issues = []
        case_type = case.get('case_type', '조정')

        if not case.get('title'):
            issues.append('제목')
        if not case.get('overview'):
            issues.append('사건개요')
        if not case.get('claims', {}).get('applicant'):
            issues.append('신청인 주장')
        if not case.get('claims', {}).get('respondent'):
            issues.append('피신청인 주장')

        # case_type에 따라 다르게 체크
        if case_type == "조정":
            # 조정: reason과 order 확인
            if not case.get('reason'):
                issues.append('조정부 판단(reason)')
            if not case.get('order'):
                issues.append('결론(order)')
        else:
            # 권고: judgement 확인
            if not case.get('judgement'):
                issues.append('합의권고(judgement)')

        if not case.get('result'):
            issues.append('결과')

        if issues:
            number = case.get('number')
            title = case.get('title', 'N/A')[:30]
            print(f"  [{case_type} {number}] {title} - 누락: {', '.join(issues)}")
            incomplete_count += 1

    if incomplete_count == 0:
        print("  [OK] 모든 사례 완벽하게 파싱됨!")
    else:
        print(f"\n  불완전한 사례: {incomplete_count}개")

    # judgement 처리 결과 확인
    print("\n[judgement 처리 결과]")
    for case in all_cases:
        case_type = case.get('case_type', '조정')
        number = case.get('number')

        if case_type == "조정":
            has_order = 'order' in case
            has_reason = 'reason' in case
            if has_order and has_reason:
                print(f"  [{case_type} {number}] reason/order로 분리 (조정부 판단/결론)")
            else:
                print(f"  [{case_type} {number}] 불완전 (reason: {has_reason}, order: {has_order})")
        else:
            has_judgement = 'judgement' in case
            if has_judgement:
                print(f"  [{case_type} {number}] judgement로 통합 (합의권고)")
            else:
                print(f"  [{case_type} {number}] 불완전 (judgement 없음)")

    # 각 사례의 내용 길이 확인
    print("\n[파싱된 내용 길이 확인]")
    for case in all_cases:
        number = case.get('number')
        case_type = case.get('case_type', '조정')
        title = case.get('title', 'N/A')[:40]
        overview_len = len(case.get('overview', ''))

        if case_type == "조정":
            reason_len = len(case.get('reason', ''))
            order_len = len(case.get('order', ''))
            print(f"  [{case_type} {number}] {title}")
            print(f"      개요: {overview_len}자, 판단: {reason_len}자, 결론: {order_len}자")
        else:
            judgement_len = len(case.get('judgement', ''))
            print(f"  [{case_type} {number}] {title}")
            print(f"      개요: {overview_len}자, 합의권고: {judgement_len}자")

    print("\n파싱 완료!")


if __name__ == "__main__":
    main()
