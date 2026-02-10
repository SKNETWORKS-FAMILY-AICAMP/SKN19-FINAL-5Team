"""
Gemini Vision API를 사용한 분쟁조정 사례 PDF 파싱 스크립트 (통합본)
"조정내용"과 "위원회 판단" 섹션을 정확히 구분하여 추출

사용법:
  python 01_03_parsing_adjustment_1_100선.py              # 전체 파싱 (재개 기능)
  python 01_03_parsing_adjustment_1_100선.py --reparse 27    # 사례 27만 다시 파싱
  python 01_03_parsing_adjustment_1_100선.py --reparse 27,28,29  # 여러 사례 다시 파싱
"""

import argparse
import json
import os
import re
import time
from typing import List, Optional, Dict, Set

import google.generativeai as genai
import pdfplumber
from pdf2image import convert_from_path
from PIL import Image


def load_env_if_needed():
    """환경변수 로드"""
    if os.getenv('GEMINI_API_KEY'):
        return
    base_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.normpath(os.path.join(base_dir, '..', '.env'))
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, val = line.split('=', 1)
                os.environ.setdefault(key, val)
    except Exception:
        return


# Gemini 모델 설정
# 우선 순위대로 시도할 모델 목록 (2.0 시리즈만 사용)
GEMINI_MODELS = [
    'gemini-2.0-flash',          # 2.0 Flash (출력: 8K 토큰)
    'gemini-2.0-flash-lite',     # 2.0 Flash Lite (경량 버전)
    'gemini-2.5-flash',          # 2.5 Flash (출력: 65K 토큰!)
]

# 사례 시작 헤더 정규식
# 패턴 1: [카테고리] 소비자분쟁조정위원회 (대부분의 사례)
# 패턴 2: [카테고리] 카테고리명/연도일가번호 (Book 3의 사례 75 등 일부)
CASE_HEADER_RE = re.compile(r'^\s*\[.+?\]\s+(소비자분쟁조정위원회|.+/\d{4}일[가나다]?\d+)')


def gemini_extract_case_structure(images: List, case_number: int, is_first_case: bool = False) -> Optional[Dict]:
    """
    Gemini Vision API를 사용하여 사례의 구조화된 데이터 추출

    Args:
        images: PIL Image 객체 리스트 (한 사례의 모든 페이지)
        case_number: 사례 번호
        is_first_case: 첫 번째 사례 여부 (모델 정보 출력용)

    Returns:
        구조화된 사례 데이터 딕셔너리
    """
    load_env_if_needed()
    api_key = os.getenv('GEMINI_API_KEY', '').strip()
    if not api_key:
        print("경고: GEMINI_API_KEY가 설정되지 않았습니다.")
        return None

    # Gemini API 초기화
    genai.configure(api_key=api_key)

    # 모델 생성 (여러 모델 시도)
    model = None
    used_model = None

    for model_name in GEMINI_MODELS:
        try:
            model = genai.GenerativeModel(model_name)
            used_model = model_name
            # 첫 사례에서만 모델 정보 출력
            if is_first_case:
                print(f"  [OK] 사용 모델: {model_name}")
            break
        except Exception as e:
            if is_first_case:
                print(f"  [오류] {model_name} 사용 불가: {str(e)[:50]}...")
            continue

    if not model:
        print(f"  [오류] 사용 가능한 모델이 없습니다.")
        return None

    # Gemini에게 제공할 상세한 프롬프트
    prompt = f"""이 이미지들은 한국 소비자원의 분쟁조정 사례 문서입니다.

다음 정보를 정확히 추출하여 JSON 형식으로 반환해주세요:

1. **사례 번호** (case_number): 숫자만 (예: 1, 2, 3)
2. **연도** (year): 결정 연도 (예: 2019)
3. **제목** (title): 사례 제목 전체
4. **사례 유형** (case_type): "조정" 또는 "판정"
5. **페이지 번호** (printed_page_number): **사례 제목이 나오는 첫 번째 페이지의 하단**에 인쇄된 페이지 번호
6. **사건 개요** (overview): "사업자", "소비자" 등으로 시작하는 사건 개요 전체
7. **조정내용** (order): "조정내용" 섹션의 내용 전체. 보통 "사업자는...", "...조정하지 아니함" 등의 결정문
8. **위원회 판단** (reason): "위원회 판단" 섹션의 내용 전체. 판단 이유와 근거
9. **해설** (commentary): "조정례 [번호]"로 시작하는 해설 부분

**중요:**
- **페이지 번호는 반드시 사례 제목이 있는 첫 페이지의 하단 번호를 사용하세요!**
- "조정내용"과 "위원회 판단"은 이미지로 되어있을 수 있으니 주의깊게 확인하세요.
- "조정내용"은 결정문으로, 짧고 명확합니다.
- "위원회 판단"은 결정 이유로, 길고 상세합니다.
- 각 섹션의 내용을 빠짐없이 모두 포함하세요.

JSON 형식:
{{
  "case_number": 숫자,
  "year": "연도",
  "title": "제목",
  "case_type": "조정",
  "printed_page_number": "페이지번호",
  "overview": "사건개요 전체 텍스트...",
  "order": "조정내용 전체 텍스트...",
  "reason": "위원회 판단 전체 텍스트...",
  "commentary": "해설 전체 텍스트..."
}}

JSON만 반환하고, 다른 설명은 포함하지 마세요."""

    # 재시도 로직 (최대 3회)
    max_retries = 3
    retry_delays = [60, 120, 180]  # 1분, 2분, 3분 대기

    for retry in range(max_retries):
        try:
            if retry > 0:
                print(f"  - 재시도 {retry}/{max_retries-1}...")

            print(f"  - Gemini Vision API 호출 중 (사례 {case_number})...")

            # 프롬프트와 이미지 함께 전달
            content = [prompt] + images

            # Gemini API 호출
            response = model.generate_content(
                content,
                generation_config=genai.GenerationConfig(
                    temperature=0.1,
                    top_p=0.95,
                    top_k=40,
                    max_output_tokens=8192,
                )
            )

            # 응답에서 텍스트 추출
            text = response.text.strip()

            # JSON 파싱 (마크다운 코드 블록 제거)
            if text.startswith('```json'):
                text = text[7:]
            if text.startswith('```'):
                text = text[3:]
            if text.endswith('```'):
                text = text[:-3]
            text = text.strip()

            # JSON 파싱
            case_data = json.loads(text)

            # 리스트로 반환된 경우 첫 번째 요소 추출
            if isinstance(case_data, list):
                if len(case_data) > 0:
                    case_data = case_data[0]
                else:
                    print(f"  - 오류: 빈 리스트 반환됨")
                    return None

            # 딕셔너리인지 확인
            if not isinstance(case_data, dict):
                print(f"  - 오류: JSON이 딕셔너리가 아님 (타입: {type(case_data)})")
                return None

            # 기본값 설정
            case_data.setdefault('case_number', case_number)
            case_data.setdefault('year', '')
            case_data.setdefault('title', '')
            case_data.setdefault('case_type', '조정')
            case_data.setdefault('printed_page_number', '')
            case_data.setdefault('overview', '')
            case_data.setdefault('order', '')
            case_data.setdefault('reason', '')
            case_data.setdefault('commentary', '')

            return case_data

        except json.JSONDecodeError as e:
            print(f"  - JSON 파싱 오류: {e}")
            print(f"  - 응답 텍스트: {text[:500]}...")
            return None

        except Exception as e:
            error_msg = str(e)

            # 429 오류 (요청 제한 초과)
            if '429' in error_msg or 'Resource exhausted' in error_msg:
                if retry < max_retries - 1:
                    wait_time = retry_delays[retry]
                    print(f"  [경고] API 요청 제한 초과. {wait_time}초 대기 후 재시도...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"  [오류] 최대 재시도 횟수 초과. 사례 {case_number} 파싱 실패")
                    return None
            else:
                # 다른 오류는 바로 실패 처리
                print(f"  - Gemini API 오류: {e}")
                import traceback
                traceback.print_exc()
                return None

    return None


def split_pdf_into_cases(pdf_path: str) -> List[tuple]:
    """
    PDF를 사례별로 분할

    Returns:
        [(case_start_page_idx, case_end_page_idx, case_number), ...]
    """
    case_boundaries = []

    with pdfplumber.open(pdf_path) as pdf:
        current_case_start = None
        case_number = 1  # 사례 1번부터 시작

        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue

            lines = text.split('\n')

            # 새 사례 시작 확인
            for line in lines:
                if CASE_HEADER_RE.search(line):
                    # 이전 사례 종료
                    if current_case_start is not None:
                        case_boundaries.append((current_case_start, page_idx - 1, case_number))
                        case_number += 1  # 다음 사례 번호로 증가

                    # 새 사례 시작
                    current_case_start = page_idx
                    break

        # 마지막 사례 추가
        if current_case_start is not None:
            case_boundaries.append((current_case_start, len(pdf.pages) - 1, case_number))

    return case_boundaries


def load_existing_cases(output_path: str) -> Dict[int, Dict]:
    """
    기존에 파싱된 사례들을 로드

    Args:
        output_path: JSON 파일 경로

    Returns:
        {case_number: case_data} 딕셔너리
    """
    if not os.path.exists(output_path):
        return {}

    try:
        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            existing_cases = {}
            for case in data.get('cases', []):
                case_num = case.get('case_number')
                if case_num:
                    existing_cases[case_num] = case
            return existing_cases
    except Exception as e:
        print(f"경고: 기존 JSON 파일 로드 실패: {e}")
        return {}


def save_intermediate_result(cases: List[Dict], output_path: str):
    """
    중간 결과 저장 (파싱 중 중단되어도 재개 가능)

    Args:
        cases: 파싱된 사례 리스트
        output_path: 출력 JSON 경로
    """
    result = {
        'year': '2020',
        'total_cases': len(cases),
        'cases': sorted(cases, key=lambda x: x.get('case_number', 0))
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def parse_pdf_with_gemini_vision(pdf_path: str, output_path: str, reparse_cases: Optional[Set[int]] = None):
    """
    Gemini Vision API를 사용하여 PDF 파싱 (재개 기능 포함)

    Args:
        pdf_path: 입력 PDF 경로
        output_path: 출력 JSON 경로
        reparse_cases: 다시 파싱할 사례 번호 집합 (None이면 일반 모드)
    """
    if not os.path.exists(pdf_path):
        print(f"오류: PDF 파일을 찾을 수 없습니다: {pdf_path}")
        return

    print(f"파싱 시작: {pdf_path}")

    # 기존에 파싱된 사례 로드
    existing_cases = load_existing_cases(output_path)

    # 다시 파싱 모드
    if reparse_cases:
        print(f"[다시 파싱 모드] 사례 {sorted(reparse_cases)}")
        # reparse_cases에 포함된 사례는 기존 케이스에서 제거
        for case_num in reparse_cases:
            if case_num in existing_cases:
                del existing_cases[case_num]
                print(f"  - 사례 {case_num}: 기존 데이터 삭제")
    elif existing_cases:
        print(f"[OK] 기존에 파싱된 사례 {len(existing_cases)}개 발견 (건너뛰기)")
        print(f"  사례 번호: {sorted(existing_cases.keys())}")

    print("\n1단계: PDF를 사례별로 분할 중...")

    # PDF를 사례별로 분할
    case_boundaries = split_pdf_into_cases(pdf_path)
    print(f"  - 총 {len(case_boundaries)}개의 사례 발견")

    # 파싱이 필요한 사례만 필터링
    if reparse_cases:
        # 다시 파싱 모드: reparse_cases에 포함된 사례만
        pending_boundaries = [(s, e, n) for s, e, n in case_boundaries if n in reparse_cases]
        if pending_boundaries:
            print(f"  - 다시 파싱: {len(pending_boundaries)}개")
        else:
            print(f"\n[오류] 요청한 사례를 찾을 수 없습니다: {sorted(reparse_cases)}")
            return
    else:
        # 일반 모드: 아직 파싱되지 않은 사례만
        pending_boundaries = [(s, e, n) for s, e, n in case_boundaries if n not in existing_cases]
        if pending_boundaries:
            print(f"  - 파싱 필요: {len(pending_boundaries)}개")
        else:
            print(f"\n[OK] 모든 사례가 이미 파싱되었습니다!")
            return

    print("\n2단계: PDF를 이미지로 변환 중...")
    # PDF 전체를 이미지로 변환 (한 번만)
    try:
        all_images = convert_from_path(pdf_path, dpi=200)
        print(f"  - 총 {len(all_images)}개 페이지 변환 완료")
    except Exception as e:
        print(f"오류: PDF 이미지 변환 실패: {e}")
        return

    print(f"\n3단계: Gemini Vision으로 사례 파싱 중 ({len(pending_boundaries)}개)...\n")

    # 기존 사례를 딕셔너리에서 리스트로 변환
    cases_dict = existing_cases.copy()

    for idx, (start_page, end_page, case_num) in enumerate(pending_boundaries):
        is_first = (idx == 0 and not existing_cases)  # 전체에서 첫 번째인지 확인
        print(f"사례 {case_num} 파싱 중 (페이지 {start_page+1}-{end_page+1})... [{idx+1}/{len(pending_boundaries)}]")

        # 해당 사례의 이미지만 추출
        case_images = all_images[start_page:end_page+1]

        # Gemini Vision으로 파싱
        case_data = gemini_extract_case_structure(case_images, case_num, is_first)

        if case_data:
            cases_dict[case_num] = case_data
            print(f"  [OK] 사례 {case_num} 완료")
            print(f"    - order 길이: {len(case_data['order'])} 자")
            print(f"    - reason 길이: {len(case_data['reason'])} 자")

            # 중간 저장 (5개마다)
            if (idx + 1) % 5 == 0:
                cases_list = list(cases_dict.values())
                save_intermediate_result(cases_list, output_path)
                print(f"  [중간 저장] 완료 ({len(cases_dict)}개 사례)\n")
            else:
                print()
        else:
            print(f"  [오류] 사례 {case_num} 파싱 실패\n")

        # API 요청 제한 방지 (분당 15회 제한 대응)
        time.sleep(5)

    # 최종 저장
    cases_list = list(cases_dict.values())
    save_intermediate_result(cases_list, output_path)

    print(f"\n[OK] 완료! 총 {len(cases_list)}개의 사례가 파싱되었습니다.")
    print(f"저장 위치: {output_path}")


def main():
    """메인 함수"""
    # 명령줄 인자 파싱
    parser = argparse.ArgumentParser(description='분쟁조정 사례 PDF 파싱 (통합본)')
    parser.add_argument(
        '--reparse',
        type=str,
        help='다시 파싱할 사례 번호 (예: 27 또는 27,28,29)'
    )
    args = parser.parse_args()

    # reparse 인자 처리
    reparse_cases = None
    if args.reparse:
        try:
            reparse_cases = set(int(x.strip()) for x in args.reparse.split(','))
        except ValueError:
            print("오류: --reparse 인자는 쉼표로 구분된 숫자여야 합니다 (예: 27 또는 27,28,29)")
            return

    current_dir = os.path.dirname(os.path.abspath(__file__))

    # 원본 PDF 파일 사용 (통합본)
    pdf_path = os.path.join(
        current_dir,
        '01_B_parsed',
        '02_02_AdjustmentCase',
        '01_kca',
        '2020년 분쟁조정 사례 100선.pdf'
    )

    # 통합 JSON 파일로 저장
    output_path = os.path.join(
        current_dir,
        '01_B_parsed',
        '02_02_AdjustmentCase',
        '01_kca',
        '2020년 분쟁조정 사례 100선.json'
    )

    parse_pdf_with_gemini_vision(pdf_path, output_path, reparse_cases)


if __name__ == '__main__':
    main()
