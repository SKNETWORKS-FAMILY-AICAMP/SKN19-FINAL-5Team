"""
후처리 스크립트: Gemini로 파싱한 JSON 파일의 오류 자동 수정
- bullet point 누락 복원
- 섹션 구분 오류 수정
- 표 외부 텍스트 제거
"""
import re
import json
from pathlib import Path
from typing import Dict, List


BASE_DIR = Path(__file__).resolve().parent
KCA_DIR = BASE_DIR / "01_B_parsed" / "02_01_SolutionCase" / "01_kca"

JSON_FILES = [
    "2022년_우수해결사례.json",
    "2023년_우수해결사례.json",
    "2024년_우수해결사례.json",
]


def detect_and_fix_section_errors(case: Dict) -> Dict:
    """섹션 구분 오류 감지 및 수정"""

    # 1. "신청 내용"에 "처리 과정" 내용이 섞여있는지 확인
    # - "● 관련 법률", "● 피해예방", "ㅇ A사업자에게" 같은 키워드가 있으면 "처리 과정"으로 이동
    신청내용 = case.get("신청 내용", "")
    처리과정 = case.get("처리 과정", "")

    # 신청 내용에서 "처리 과정"으로 이동할 패턴
    처리과정_패턴 = [
        r"● 관련 법률.*?검토",
        r"● 피해예방 정보",
        r"● 사실관계 확인",
        r"● 합의권고",
        r"ㅇ A사업자에게",
    ]

    # 신청 내용을 줄 단위로 분석
    신청_lines = 신청내용.split('\n')
    올바른_신청 = []
    이동할_내용 = []

    이동_시작 = False
    for line in 신청_lines:
        if not 이동_시작:
            # 처리 과정 패턴을 찾으면 이동 시작
            for pattern in 처리과정_패턴:
                if re.search(pattern, line):
                    이동_시작 = True
                    이동할_내용.append(line)
                    break
            if not 이동_시작:
                올바른_신청.append(line)
        else:
            # 이미 이동 시작했으면 나머지도 모두 이동
            이동할_내용.append(line)

    # 이동할 내용이 있으면 수정
    if 이동할_내용:
        case["신청 내용"] = '\n'.join(올바른_신청).strip()
        # 처리 과정 앞에 추가
        이동할_텍스트 = '\n'.join(이동할_내용).strip()
        if 처리과정:
            case["처리 과정"] = 이동할_텍스트 + '\n' + 처리과정
        else:
            case["처리 과정"] = 이동할_텍스트

    return case


def remove_table_external_content(case: Dict) -> Dict:
    """표 외부 텍스트 제거 (페이지 하단의 별도 텍스트)"""

    처리과정 = case.get("처리 과정", "")

    # "①청약철회 기간 제한, ②청약철회..." 같은 패턴이 있으면
    # 이것은 표 외부 텍스트일 가능성이 높음 → [대괄호]로 감싸거나 제거

    # 패턴: ①로 시작하고 ②③④⑤⑥⑦⑧⑨가 여러 개 나오는 경우
    외부_텍스트_패턴 = r'①[^●ㅇ]{0,50}②[^●ㅇ]{0,50}③[^●ㅇ]{0,50}④'

    if re.search(외부_텍스트_패턴, 처리과정):
        # ① 시작 위치 찾기
        match = re.search(r'①', 처리과정)
        if match:
            start_pos = match.start()

            # ① 이전까지가 진짜 "처리 과정"
            before = 처리과정[:start_pos].strip()

            # ① 이후에서 다음 ●, ㅇ, ○ 까지가 외부 텍스트
            after = 처리과정[start_pos:]

            # 외부 텍스트 끝 찾기 (다음 bullet point 또는 끝)
            next_bullet = re.search(r'\n[●ㅇ○]', after)
            if next_bullet:
                외부_텍스트 = after[:next_bullet.start()].strip()
                나머지 = after[next_bullet.start():].strip()

                # 외부 텍스트를 대괄호로 감싸서 표시
                case["처리 과정"] = before + '\n[' + 외부_텍스트 + ']\n' + 나머지
            else:
                # 외부 텍스트가 끝까지 계속되면 대괄호로 감싸기
                외부_텍스트 = after.strip()
                case["처리 과정"] = before + '\n[' + 외부_텍스트 + ']'

    return case


def add_missing_bullet_points(case: Dict) -> Dict:
    """누락된 bullet point 복원"""

    for field in ["신청 내용", "처리 과정", "처리 결과"]:
        content = case.get(field, "")
        if not content:
            continue

        lines = content.split('\n')
        fixed_lines = []

        for i, line in enumerate(lines):
            stripped = line.strip()

            # 빈 줄은 그대로 유지
            if not stripped:
                fixed_lines.append(line)
                continue

            # 이미 bullet point가 있으면 그대로
            if stripped.startswith(('●', 'ㅇ', '○', '-', '①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '[')):
                fixed_lines.append(line)
                continue

            # bullet point가 없는데 문장이 시작되면 (대문자, 한글 시작)
            # 이전 줄과의 연속성 확인
            if i > 0 and fixed_lines:
                prev_line = fixed_lines[-1].strip()
                # 이전 줄이 bullet point로 시작하고 문장이 완결되지 않았으면 (줄바꿈 연속)
                # bullet point를 추가하지 않음
                if prev_line and not prev_line.endswith(('.', '함', '음', '됨', '요', '임', '등)')):
                    fixed_lines.append(line)
                    continue

            # 새 문장 시작인 것 같으면 ● 추가
            if re.match(r'^[가-힣A-Z]', stripped):
                # 들여쓰기 유지하고 ● 추가
                indent = len(line) - len(line.lstrip())
                fixed_lines.append(' ' * indent + '● ' + stripped)
            else:
                fixed_lines.append(line)

        case[field] = '\n'.join(fixed_lines)

    return case


def fix_specific_cases(case: Dict, year: str) -> Dict:
    """특정 케이스 수동 수정"""

    # 2022년 케이스 6번: 신청 내용 누락 수정
    if year == "2022" and case.get("번호") == 6:
        if "주식리딩서비스" in case.get("제목", ""):
            case["신청 내용"] = """● 유사투자자문업체인 C투자클럽은 2022. 4. 경부터 회원을 모집하면서 N쇼핑(온라인)의 입점 업체로 위장하여 간편결제(N페이)를 통해 신용카드로 회비를 결제함.
● 상세 결제 방법으로는 ① C투자클럽이 계약 체결을 위해 N쇼핑 결제를 유도하면, ② N쇼핑(온라인) 측의 유사투자자문 서비스 계약 체결 금지 규정을 피하기 위해, ③ N쇼핑 입점 업체가 실제로 소비자가 구매하지 않은 물품 판매 또는 전자제품 렌탈 계약을 체결하고, ④ 소비자는 C투자클럽 담당자의 안내에 따라 결제 직후 '구매확정'을 클릭하는 방식으로 이루어짐.
● 이후 소비자가 계약해지 및 환불을 요구하면 '카드 결제 금액 전액을 취소해 줄 테니 C투자클럽 법인계좌로 위약금을 입금하라'고 안내한 후, 입금이 완료되어도 '결제대행사(PG)에서 처리를 지연하고 있다'고 주장하며 환급을 지연함."""

            case["처리 과정"] = """● 법률 검토
- 「여신전문금융업법」 제19조 제7항에 따라 결제대행사가 거래취소, 환불에 대한 1차적 책임이 있으므로, 소비자의 환불 요구가 타당한 경우 결제대행사는 이에 응해야 함을 확인
● 결제대행사에 대한 환급 권고
- 입점 업체에서 결제대행사에 대금을 입금하지 않았다는 이유로 환급을 거부하는 것은 부당하므로 조속히 환급처리 할 것을 결제대행사에 권고"""

            case["처리 결과"] = """● 합의권고 수용
- 총 1억 9천 5백만 원 환급"""

    return case


def post_process_case(case: Dict, year: str = None) -> Dict:
    """케이스 후처리"""

    # 0. 특정 케이스 수동 수정 (최우선)
    if year:
        case = fix_specific_cases(case, year)

    # 1. 섹션 구분 오류 수정
    case = detect_and_fix_section_errors(case)

    # 2. 표 외부 텍스트 처리
    case = remove_table_external_content(case)

    # 3. 누락된 bullet point 복원 (선택적 - 너무 공격적일 수 있음)
    # case = add_missing_bullet_points(case)

    return case


def process_json_file(json_path: Path) -> None:
    """JSON 파일 후처리"""

    print(f"\n{'='*80}")
    print(f"Processing: {json_path.name}")
    print(f"{'='*80}\n")

    # JSON 로드
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    cases = data.get("사례", [])
    year = data.get("연도", "")
    print(f"Total cases: {len(cases)}")

    # 각 케이스 후처리
    modified_count = 0
    for i, case in enumerate(cases):
        original = json.dumps(case, ensure_ascii=False)
        processed = post_process_case(case, year)
        modified = json.dumps(processed, ensure_ascii=False)

        if original != modified:
            modified_count += 1
            print(f"  Case #{case['번호']}: Modified")

    print(f"\nModified cases: {modified_count}/{len(cases)}")

    # 백업 저장
    backup_path = json_path.with_suffix('.json.backup')
    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Backup saved: {backup_path.name}")

    # 수정된 JSON 저장
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Updated: {json_path.name}")


def main():
    """메인 함수"""

    print("\n" + "="*80)
    print("후처리 스크립트: Gemini 파싱 결과 자동 수정")
    print("="*80)

    for json_file in JSON_FILES:
        json_path = KCA_DIR / json_file

        if not json_path.exists():
            print(f"\n[SKIP] 파일 없음: {json_file}")
            continue

        process_json_file(json_path)

    print("\n" + "="*80)
    print("후처리 완료")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
