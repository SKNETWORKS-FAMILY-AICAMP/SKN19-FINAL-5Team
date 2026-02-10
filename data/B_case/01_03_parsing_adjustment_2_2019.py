"""
2019년 전자거래 분쟁조정 사례집 - Gemini 2.0 Flash 파싱

주요 개선사항:
1. Gemini 2.0 Flash로 간단하고 빠른 파싱
2. 명확한 프롬프트 - 불필요한 지침 제거
3. 기존 JSON의 case_ranges 활용
4. reason/order 정확 추출

필수 설치:
    pip install google-generativeai pillow pymupdf python-dotenv

사용 방법:
    python 01_03_parsing_adjustment_2_2019.py
"""
import fitz
import json
import os
import re
import base64
from pathlib import Path
from PIL import Image
import io
import google.generativeai as genai
from dotenv import load_dotenv
import time
from collections import OrderedDict

load_dotenv(dotenv_path="../.env")
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("[ERROR] GEMINI_API_KEY를 찾을 수 없습니다")
    exit(1)

genai.configure(api_key=api_key)

CACHE_FILE = Path("01_B_parsed/02_02_AdjustmentCase/02_kisa/.2019_parsing_cache_gemini.json")


def load_cache():
    """캐시 파일에서 이전 작업 불러오기"""
    if CACHE_FILE.exists():
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        print(f"[OK] 캐시 발견 - {len(cache.get('completed_cases', []))}개 사례 완료됨")
        return cache
    return {
        "completed_cases": [],
        "case_ranges": [],
        "last_completed_index": -1
    }


def save_cache(cache):
    """캐시 파일에 중간 결과 저장"""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def delete_cache():
    """캐시 파일 삭제"""
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()
        print("[OK] 파싱이 완료되어 캐시가 삭제되었습니다.")


def extract_case_ranges_from_json(json_path):
    """기존 JSON 파일에서 페이지 범위 추출"""
    json_path = Path(json_path)

    if not json_path.exists():
        print(f"[ERROR] 파일을 찾을 수 없습니다: {json_path}")
        return None

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"[ERROR] JSON 읽기 오류: {e}")
        return None

    cases = data.get('cases', [])
    if not cases:
        print(f"[ERROR] cases를 찾을 수 없습니다")
        return None

    print(f"[OK] {len(cases)}개 사례 발견\n")

    # 페이지 범위 추출
    case_ranges = []
    print("[페이지 범위]")
    print("-" * 60)

    for case in cases:
        case_num = case.get('number')
        page_start = case.get('page_start')
        page_end = case.get('page_end')

        if page_start is None or page_end is None:
            continue

        range_end = page_end + 1
        case_ranges.append((page_start, range_end))

        title = case.get('title', '제목 없음')[:35]
        pages = range_end - page_start
        print(f"사례 {case_num:2d}: 페이지 {page_start:2d}-{range_end-1:2d}  [{pages}페이지]  {title}...")

    print("-" * 60)
    print(f"\n[OK] {len(case_ranges)}개 범위 추출 완료\n")
    return case_ranges


def image_to_base64(image):
    """PIL Image를 base64 문자열로 변환"""
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')


def pdf_pages_to_images(pdf_path, start_page, end_page, dpi=200):
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


def parse_case_gemini(images, retry=0):
    """
    Gemini 2.0 Flash로 전체 케이스 + reason/order 한번에 추출
    429 에러 시 재시도 포함
    """
    prompt = """이 이미지들은 2019년 전자거래 분쟁조정 사례집의 조정 사례입니다.

다음 정보를 원문 그대로 추출하여 JSON으로 응답하세요:

{
  "case_number": "사건번호",
  "method": "조정방법",
  "title": "사건명칭",
  "case_type": "조정",
  "printed_page_number": "인쇄된 페이지 번호",
  "overview": "1. 분쟁개요 섹션",
  "claims": {
    "applicant": ["가. 신청인 주장"],
    "respondent": ["나. 피신청인 주장"]
  },
  "judgement": {
    "reason": "3. 조정결정 섹션 (가., 나., 다. 등 모든 부분)",
    "order": "4. 결론 섹션"
  },
  "result": "조정결과"
}

주의: 없는 내용은 null, 배열은 원문을 문자열로 한 항목에 넣기, 요약 금지."""

    try:
        model = genai.GenerativeModel("gemini-2.0-flash")

        # 이미지를 Gemini 형식으로 변환
        image_parts = []
        for img in images:
            img_base64 = image_to_base64(img)
            image_parts.append({
                "mime_type": "image/png",
                "data": img_base64
            })

        # Gemini API 호출
        response = model.generate_content([prompt] + image_parts)
        text = response.text.strip()

        # JSON 추출
        if '```json' in text:
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
            if json_match:
                text = json_match.group(1)
        elif '```' in text:
            json_match = re.search(r'```\s*(\{.*?\})\s*```', text, re.DOTALL)
            if json_match:
                text = json_match.group(1)

        text = text.strip()
        if '{' in text and '}' in text:
            start_idx = text.find('{')
            end_idx = text.rfind('}') + 1
            text = text[start_idx:end_idx]

        data = json.loads(text)
        return data

    except Exception as e:
        error_msg = str(e)

        # 429 Rate Limit 에러 처리
        if "429" in error_msg or "Resource exhausted" in error_msg:
            if retry < 3:
                wait_time = 30 * (retry + 1)  # 30초, 60초, 90초
                print(f"    [WARN]  Rate limit 도달 - {wait_time}초 대기 후 재시도 {retry+1}/3...")
                time.sleep(wait_time)
                return parse_case_gemini(images, retry + 1)
            else:
                print(f"    [ERROR] 3회 재시도 후에도 Rate limit 실패")
                return None
        else:
            print(f"    [ERROR] 파싱 오류: {error_msg[:80]}")
            return None


def extract_reason_order_only(images, retry=0):
    """
    reason과 order 섹션만 집중적으로 추출 (검증 실패 시 재시도용)
    """
    prompt = """이 이미지들은 2019년 전자거래 분쟁조정 사례집입니다.

"3. 조정결정" 섹션과 "4. 결론" 섹션을 완전히 추출하세요.

반드시 다음을 포함하세요:
1. "3. 조정결정" 또는 "3.조정결정"으로 시작하는 섹션의 전체 내용 (가., 나., 다. 등 모든 소항목 포함)
2. "4. 결론" 또는 "4.결론"으로 시작하는 섹션의 전체 내용

JSON으로 응답하세요:
{
  "reason": "3. 조정결정 섹션의 모든 내용",
  "order": "4. 결론 섹션의 모든 내용"
}

주의: 절대 요약하지 마세요. 원문 전체를 포함하세요."""

    try:
        model = genai.GenerativeModel("gemini-2.0-flash")

        # 이미지를 Gemini 형식으로 변환
        image_parts = []
        for img in images:
            img_base64 = image_to_base64(img)
            image_parts.append({
                "mime_type": "image/png",
                "data": img_base64
            })

        # Gemini API 호출
        response = model.generate_content([prompt] + image_parts)
        text = response.text.strip()

        # JSON 추출
        if '```json' in text:
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
            if json_match:
                text = json_match.group(1)
        elif '```' in text:
            json_match = re.search(r'```\s*(\{.*?\})\s*```', text, re.DOTALL)
            if json_match:
                text = json_match.group(1)

        text = text.strip()
        if '{' in text and '}' in text:
            start_idx = text.find('{')
            end_idx = text.rfind('}') + 1
            text = text[start_idx:end_idx]

        data = json.loads(text)
        return data

    except Exception as e:
        error_msg = str(e)

        # 429 Rate Limit 에러 처리
        if "429" in error_msg or "Resource exhausted" in error_msg:
            if retry < 3:
                wait_time = 30 * (retry + 1)
                print(f"    [RETRY] Rate limit - {wait_time}초 대기...")
                time.sleep(wait_time)
                return extract_reason_order_only(images, retry + 1)
            else:
                print(f"    [ERROR] reason/order 추출 실패 (Rate limit)")
                return None
        else:
            print(f"    [ERROR] reason/order 추출 오류: {error_msg[:80]}")
            return None


def validate_judgement(judgement, case_num):
    """reason과 order 검증"""
    MIN_REASON = 500
    MIN_ORDER = 150

    reason = judgement.get('reason', '')
    order = judgement.get('order', '')

    issues = []
    is_valid = True

    if not reason or (isinstance(reason, str) and len(reason) < MIN_REASON):
        issues.append(f"reason 불완전 ({len(reason) if reason else 0}자 < {MIN_REASON}자)")
        is_valid = False

    if not order or (isinstance(order, str) and len(order) < MIN_ORDER):
        issues.append(f"order 불완전 ({len(order) if order else 0}자 < {MIN_ORDER}자)")
        is_valid = False

    if issues:
        print(f"    [WARN]  [검증] 사례 {case_num}:")
        for issue in issues:
            print(f"       - {issue}")

    return is_valid, issues


def reorder_case_fields(case_data):
    """필드 순서 정렬"""
    field_order = [
        "case_number", "method", "title", "case_type", "printed_page_number",
        "overview", "claims", "judgement", "result", "parsing_method",
        "number", "page_start", "page_end"
    ]

    ordered_case = OrderedDict()
    for field in field_order:
        if field in case_data:
            ordered_case[field] = case_data[field]

    for key, value in case_data.items():
        if key not in ordered_case:
            ordered_case[key] = value

    return dict(ordered_case)


def main():
    print("=" * 80)
    print("2019년 전자거래 분쟁조정 사례집 - Gemini 2.0 Flash 파싱")
    print("=" * 80)

    # 기존 JSON에서 범위 추출
    existing_json = Path("01_B_parsed/02_02_AdjustmentCase/02_kisa/2019년 전자거래 조정사례.json")

    if not existing_json.exists():
        print(f"[ERROR] 기존 JSON 파일을 찾을 수 없습니다: {existing_json}")
        return

    case_ranges = extract_case_ranges_from_json(existing_json)

    if not case_ranges:
        print("[ERROR] 범위 추출 실패")
        return

    # PDF 경로
    pdf_path = Path("01_B_parsed/02_02_AdjustmentCase/02_kisa/2019년 전자거래 분쟁조정 사례집.pdf")
    output_path = Path("01_B_parsed/02_02_AdjustmentCase/02_kisa/2019년 전자거래 조정사례.json")

    if not pdf_path.exists():
        print(f"[ERROR] PDF 파일을 찾을 수 없습니다: {pdf_path}")
        return

    # 캐시 로드
    cache = load_cache()
    cache["case_ranges"] = case_ranges
    save_cache(cache)

    print(f"발견된 케이스: {len(case_ranges)}개")
    print("=" * 80)

    cases = cache.get("completed_cases", [])
    last_completed = cache.get("last_completed_index", -1)

    print("\n[사례 파싱 - Gemini 2.0 Flash]")
    print("-" * 80)

    if last_completed >= 0:
        print(f"[재개] 사례 {last_completed + 1}부터 시작합니다...\n")

    # 각 케이스 파싱
    for idx, (start_page, end_page) in enumerate(case_ranges, 1):
        # 이미 완료된 사례는 스킵
        if idx <= last_completed + 1:
            print(f"사례 {idx:2d}/14 - 이미 완료됨 (스킵)")
            continue

        print(f"\n사례 {idx:2d}/14 (PDF 페이지 {start_page}-{end_page-1})")

        # 이미지 변환
        num_pages = end_page - start_page
        print(f"  [IMG] 이미지 변환: {num_pages}개 페이지")
        images = pdf_pages_to_images(pdf_path, start_page, end_page, dpi=200)

        if not images:
            print(f"  [ERROR] 이미지 변환 실패")
            continue

        # 파싱
        print(f"  [AI] Gemini 2.0 Flash 파싱 중...")
        case_data = parse_case_gemini(images)

        if not case_data:
            print(f"  [ERROR] 파싱 실패")
            return

        print(f"  [OK] 파싱 완료")

        # 검증
        is_valid, issues = validate_judgement(case_data.get('judgement', {}), idx)

        if is_valid:
            print(f"  [OK] [검증] 통과")
        else:
            print(f"  [RETRY] 검증 실패 - reason/order 재추출 중...")
            print(f"    이슈: {', '.join(issues)}")

            # 검증 실패 시 reason/order만 다시 추출
            reason_order_data = extract_reason_order_only(images)

            if reason_order_data:
                # 새로운 reason/order 데이터로 업데이트
                if 'judgement' not in case_data:
                    case_data['judgement'] = {}

                if 'reason' in reason_order_data and reason_order_data['reason']:
                    case_data['judgement']['reason'] = reason_order_data['reason']
                    print(f"    [OK] reason 업데이트: {len(reason_order_data['reason'])}자")

                if 'order' in reason_order_data and reason_order_data['order']:
                    case_data['judgement']['order'] = reason_order_data['order']
                    print(f"    [OK] order 업데이트: {len(reason_order_data['order'])}자")

                # 재검증
                is_valid_retry, issues_retry = validate_judgement(case_data.get('judgement', {}), idx)
                if is_valid_retry:
                    print(f"  [OK] 재검증 통과!")
                else:
                    print(f"  [WARN] 재검증 후에도 경고 존재: {', '.join(issues_retry)}")
            else:
                print(f"  [WARN] reason/order 재추출 실패 - 기존 데이터 유지")

        # 메타데이터 추가
        case_data["parsing_method"] = "gemini_2.0_flash"
        case_data["number"] = idx
        case_data["page_start"] = start_page
        case_data["page_end"] = end_page - 1

        # 필드 순서 정렬
        case_data = reorder_case_fields(case_data)

        cases.append(case_data)

        # 통계
        title = case_data.get("title", "제목 없음")[:40]
        judgement = case_data.get("judgement", {})
        reason_len = len(judgement.get("reason", "") if isinstance(judgement.get("reason"), str) else "")
        order_len = len(judgement.get("order", "") if isinstance(judgement.get("order"), str) else "")

        print(f"  [INFO] 제목: {title}...")
        print(f"  [INFO] reason: {reason_len}자, order: {order_len}자")

        # 중간 저장
        cache["completed_cases"] = cases
        cache["last_completed_index"] = idx - 1
        save_cache(cache)

        print(f"  [SAVE] 캐시 저장됨 ({len(cases)}/14)")

        # API 레이트 제한
        time.sleep(5)

    print("\n" + "-" * 80)
    print(f"[OK] 파싱 완료: {len(cases)}/14")
    print("=" * 80)

    # JSON 저장
    output_data = {
        "year": "2019",
        "total_cases": len(cases),
        "parsing_statistics": {
            "text_parsed": 0,
            "vision_parsed": 0,
            "openai_vision_parsed": 0,
            "gemini_vision_parsed": len(cases),
            "complete_cases": len(cases),
            "adjustment_cases": len(cases),
            "recommendation_cases": 0
        },
        "cases": cases
    }

    print("\n[파일 저장]")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"[FILE] 저장됨: {output_path}")
    print(f"[INFO] 총 사례: {len(cases)}개")
    print("=" * 80)

    # 완성도 검증
    print("\n[완성도 최종 검증]")

    all_valid = True
    for case in cases:
        if not validate_judgement(case.get('judgement', {}), case.get('number')):
            all_valid = False

    if all_valid:
        print(f"[OK] 모든 사례가 완벽합니다!")
        for i, case in enumerate(cases[:3], 1):
            judgement = case.get('judgement', {})
            reason_len = len(judgement.get("reason", "") if isinstance(judgement.get("reason"), str) else "")
            order_len = len(judgement.get("order", "") if isinstance(judgement.get("order"), str) else "")
            print(f"   사례 {i}: reason {reason_len}자, order {order_len}자")
    else:
        print(f"[WARN]  일부 사례에 경고가 있습니다.")

    # 캐시 삭제 (완료 시)
    if len(cases) == 14:
        delete_cache()
        print("\n[OK] 파싱 완료! 캐시가 삭제되었습니다.")

    return len(cases) == 14


if __name__ == "__main__":
    success = main()
    if not success:
        print("\n[WARN]  파싱이 완료되지 않았습니다.")
        print("다시 실행하면 마지막 지점부터 계속됩니다.")
