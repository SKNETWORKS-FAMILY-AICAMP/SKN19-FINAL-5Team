"""
2021년 전자거래 조정사례 OpenAI GPT-4o API 파싱

주요 기능:
- GPT-4o Vision API를 사용한 PDF 파싱
- 자동 케이스 경계 탐색
- Gemini보다 더 긴 응답 지원
- judgement 구조:
  * reason: "다. 조정부 판단"
  * order: "라. 조정 결과"
- result 필드: null
"""
import fitz
import json
import os
import re
from pathlib import Path
from PIL import Image
import io
import base64
from openai import OpenAI
from dotenv import load_dotenv
import time

load_dotenv(dotenv_path="../.env")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def pdf_pages_to_images(pdf_path, start_page, end_page, dpi=100):
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


def image_to_base64(image):
    """PIL Image를 base64 문자열로 변환"""
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')


def parse_case_with_openai(images, case_type="조정"):
    """OpenAI GPT-4o로 케이스 파싱"""

    # 이미지를 base64로 변환
    image_contents = []
    for img in images:
        base64_image = image_to_base64(img)
        image_contents.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{base64_image}",
                "detail": "high"
            }
        })

    prompt = """이 이미지들은 2021년 전자거래 분쟁조정 사례집의 조정 사례입니다.
다음 JSON 형식으로 **원문 그대로** 추출하세요:

{
  "title": "사건명칭 (예: 제품 불량에 따른 수선비 지급요구 거부)",
  "printed_page_number": "인쇄된 페이지 번호 (페이지 하단에 표시된 숫자)",
  "overview": "가. 사건 개요\n\n[사건 개요의 전체 내용을 한 글자도 빠짐없이 그대로 복사]",
  "claims": {
    "applicant": ["나. 양 당사자 주장\n\n1) 신청인 주장\n\n[1) 신청인 주장의 전체 내용을 한 글자도 빠짐없이 그대로 복사]"],
    "respondent": ["2) 피신청인 주장\n\n[2) 피신청인 주장의 전체 내용을 한 글자도 빠짐없이 그대로 복사]"]
  },
  "judgement": {
    "reason": "다. 조정부 판단\n\n[다. 조정부 판단 섹션의 전체 내용을 처음부터 끝까지 한 글자도 빠짐없이 그대로 복사. 내용이 아무리 길어도 절대 중간에 자르지 말고 끝까지 복사]",
    "order": "라. 조정 결과\n\n[라. 조정 결과 섹션의 전체 내용을 한 글자도 빠짐없이 그대로 복사]"
  },
  "result": null
}

**매우 중요한 지침**:
1. **절대로 내용을 요약하거나 줄이지 마세요** - 원문을 처음부터 끝까지 한 글자도 빠짐없이 복사
2. 특히 judgement.reason은 내용이 아무리 길어도 **반드시 전체를 다 복사**해야 합니다
3. judgement.order도 "라. 조정 결과" 헤더와 함께 **모든 내용을 복사**
4. claims에서:
   - applicant는 "1) 신청인 주장" 부분의 **전체 내용**
   - respondent는 "2) 피신청인 주장" 부분의 **전체 내용**
5. 섹션 헤더(가., 나., 다., 라., 1), 2))를 반드시 포함
6. 줄바꿈과 문단 구조 유지
7. JSON 형식을 정확히 지키고 특수문자는 이스케이프 처리
8. 응답은 반드시 유효한 JSON만 포함하고, ```json 같은 마크다운은 사용하지 마세요"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        *image_contents
                    ]
                }
            ],
            max_tokens=4096,  # 긴 응답 지원
            temperature=0.1
        )

        text = response.choices[0].message.content.strip()

        # JSON 추출
        if '```json' in text:
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
            if json_match:
                text = json_match.group(1)
        elif '```' in text:
            json_match = re.search(r'```\s*(\{.*?\})\s*```', text, re.DOTALL)
            if json_match:
                text = json_match.group(1)

        data = json.loads(text)
        return data

    except Exception as e:
        print(f"    에러: {e}", flush=True)
        return None


def parse_long_case_with_openai(images1, images2, case_type="조정"):
    """긴 케이스를 2개 부분으로 나눠서 파싱 후 병합"""

    # 첫 부분 파싱
    prompt1 = """이 이미지들은 2021년 전자거래 분쟁조정 사례집의 일부입니다.
다음 JSON 형식으로 원문 그대로 추출하세요:

{
  "title": "사건명칭",
  "printed_page_number": "인쇄된 페이지 번호",
  "overview": "가. 사건 개요 섹션 전체 원문",
  "claims_applicant": "나. 양 당사자 주장의 1) 신청인 주장 전체 원문",
  "claims_respondent": "나. 양 당사자 주장의 2) 피신청인 주장 전체 원문 (또는 첫 부분)"
}

원문을 한 글자도 빠짐없이 그대로 복사하세요. JSON만 출력하세요."""

    image_contents1 = []
    for img in images1:
        base64_image = image_to_base64(img)
        image_contents1.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{base64_image}", "detail": "high"}
        })

    try:
        response1 = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt1},
                        *image_contents1
                    ]
                }
            ],
            max_tokens=4096,
            temperature=0.1
        )

        text1 = response1.choices[0].message.content.strip()
        if '```json' in text1:
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', text1, re.DOTALL)
            if json_match:
                text1 = json_match.group(1)

        data1 = json.loads(text1)
        time.sleep(1)

    except Exception as e:
        print(f"    Part 1 에러: {e}", flush=True)
        return None

    # 두 번째 부분 파싱
    prompt2 = """이 이미지들은 앞 페이지에서 이어지는 내용입니다.
다음 JSON 형식으로 원문 그대로 추출하세요:

{
  "claims_respondent_cont": "2) 피신청인 주장의 나머지 부분 (있다면)",
  "judgement_reason": "다. 조정부 판단 섹션 전체 원문 (아무리 길어도 전체를 복사)",
  "judgement_order": "라. 조정 결과 섹션 전체 원문"
}

원문을 한 글자도 빠짐없이 그대로 복사하세요. JSON만 출력하세요."""

    image_contents2 = []
    for img in images2:
        base64_image = image_to_base64(img)
        image_contents2.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{base64_image}", "detail": "high"}
        })

    try:
        response2 = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt2},
                        *image_contents2
                    ]
                }
            ],
            max_tokens=4096,
            temperature=0.1
        )

        text2 = response2.choices[0].message.content.strip()
        if '```json' in text2:
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', text2, re.DOTALL)
            if json_match:
                text2 = json_match.group(1)

        data2 = json.loads(text2)

    except Exception as e:
        print(f"    Part 2 에러: {e}", flush=True)
        return None

    # 병합
    respondent_full = data1.get("claims_respondent", "") + "\n\n" + data2.get("claims_respondent_cont", "")

    merged = {
        "title": data1.get("title"),
        "printed_page_number": data1.get("printed_page_number"),
        "overview": data1.get("overview"),
        "claims": {
            "applicant": [data1.get("claims_applicant", "")],
            "respondent": [respondent_full.strip()]
        },
        "judgement": {
            "reason": data2.get("judgement_reason"),
            "order": data2.get("judgement_order")
        },
        "result": None
    }

    return merged


def find_case_boundaries(pdf_path):
    """케이스 경계 자동 탐색"""
    doc = fitz.open(pdf_path)
    boundaries = []

    case_pattern1 = re.compile(r'^\d+\.\s+[\uac00-\ud7a3]')
    case_pattern2 = re.compile(r'^\d+\.\s*$')

    total_pages = len(doc)

    for page_num in range(1, total_pages):
        page = doc[page_num]
        text = page.get_text()
        lines = [line.strip() for line in text.split('\n') if line.strip()]

        for line in lines[:15]:
            if case_pattern1.match(line) or case_pattern2.match(line):
                boundaries.append(page_num)
                break

    doc.close()

    # (start, end) 튜플 생성
    case_ranges = []
    for i in range(len(boundaries)):
        start = boundaries[i]
        end = boundaries[i + 1] if i + 1 < len(boundaries) else total_pages
        case_ranges.append((start, end))

    return case_ranges


def main():
    pdf_path = Path("01_B_parsed/02_02_AdjustmentCase/02_kisa/2021년 전자거래 분쟁조정 사례집.pdf")

    if not pdf_path.exists():
        print(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")
        return

    print("=" * 80, flush=True)
    print("2021년 전자거래 조정사례 OpenAI GPT-4o API 파싱", flush=True)
    print("=" * 80, flush=True)

    # 케이스 경계 탐색
    print("\n케이스 경계 탐색 중...", flush=True)
    case_ranges = find_case_boundaries(str(pdf_path))
    print(f"발견된 케이스: {len(case_ranges)}개", flush=True)

    for i, (start, end) in enumerate(case_ranges[:5], 1):
        print(f"  Case {i}: 페이지 {start+1}-{end}", flush=True)

    # 각 케이스 파싱
    all_cases = []

    for i, (start_page, end_page) in enumerate(case_ranges, 1):
        page_count = end_page - start_page

        print(f"\n{'='*80}", flush=True)
        print(f"Case {i}/{len(case_ranges)} 파싱 중 (페이지 {start_page+1}-{end_page}, {page_count}페이지)", flush=True)
        print(f"{'='*80}", flush=True)

        # 페이지가 3개 이상이면 분할 파싱
        if page_count >= 3:
            print(f"  긴 케이스 감지 ({page_count}페이지) - 분할 파싱", flush=True)
            mid = start_page + (page_count // 2)
            images1 = pdf_pages_to_images(str(pdf_path), start_page, mid, dpi=100)
            images2 = pdf_pages_to_images(str(pdf_path), mid, end_page, dpi=100)
            case_data = parse_long_case_with_openai(images1, images2, case_type="조정")
        else:
            images = pdf_pages_to_images(str(pdf_path), start_page, end_page, dpi=100)
            case_data = parse_case_with_openai(images, case_type="조정")

        if case_data:
            # 최종 케이스 데이터 구성
            final_case = {
                "case_number": str(i),
                "method": None,
                "title": case_data.get("title"),
                "case_type": "조정",
                "printed_page_number": case_data.get("printed_page_number"),
                "overview": case_data.get("overview", ""),
                "claims": case_data.get("claims", {"applicant": [], "respondent": []}),
                "judgement": case_data.get("judgement", {"reason": "", "order": ""}),
                "result": None,
                "parsing_method": "openai_gpt4o",
                "number": i,
                "page_start": start_page,
                "page_end": end_page - 1
            }

            all_cases.append(final_case)

            print(f"  [OK] {final_case['title'][:50] if final_case['title'] else 'N/A'}", flush=True)
            print(f"  길이: ov={len(final_case['overview'])}, reason={len(final_case['judgement']['reason'])}, order={len(final_case['judgement']['order'])}", flush=True)
        else:
            print(f"  [FAIL] 파싱 실패", flush=True)

        # Rate limit 방지
        time.sleep(2)

    # JSON 파일 생성
    output_data = {
        "year": "2021",
        "total_cases": len(all_cases),
        "parsing_statistics": {
            "text_parsed": 0,
            "vision_parsed": 0,
            "gemini_parsed": 0,
            "openai_parsed": len(all_cases),
            "complete_cases": len(all_cases),
            "recommendation_cases": 0,
            "adjustment_cases": len(all_cases)
        },
        "cases": all_cases
    }

    output_path = Path("01_B_parsed/02_02_AdjustmentCase/02_kisa/2021년 전자거래 조정사례.json")

    print(f"\n{'='*80}", flush=True)
    print("JSON 파일 저장 중...", flush=True)
    print(f"{'='*80}", flush=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"저장 완료: {output_path}", flush=True)
    print(f"총 {len(all_cases)}개 케이스 파싱 완료", flush=True)


if __name__ == "__main__":
    main()
