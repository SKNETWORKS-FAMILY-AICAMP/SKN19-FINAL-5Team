"""
Gemini 파싱 결과 검증 스크립트

파싱된 JSON 데이터의 품질을 검증합니다:
1. 기본 통계 계산
2. 구조 검증 (필수 필드)
3. 비고 매핑 검증
4. 대분류/중분류 forward fill 검증
5. 샘플 데이터 출력
6. 오류 리포트 생성
"""

import json
import os
from pathlib import Path
from collections import defaultdict

# 파싱 결과 파일 경로
JSON_PATH = r"C:\Users\Playdata\Desktop\project\05_5th_project\data_n_db\raw\02_Guide\소비자분쟁해결기준_별표\[별표 2] 품목별 해결기준 1.json"


def load_json(file_path: str) -> dict:
    """JSON 파일 로드"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def calculate_statistics(data: dict) -> dict:
    """기본 통계 계산"""
    stats = {
        'total_tables': len(data['data']),
        'total_items': 0,
        'total_conditions': 0,
        'total_sub_conditions': 0,
        'total_notes': 0,
        'tables_with_errors': 0,
        'pages_covered': set(),
        'categories': defaultdict(int),
        'mid_categories': defaultdict(int)
    }

    for table in data['data']:
        # 페이지 수집
        if 'source_page' in table:
            stats['pages_covered'].add(table['source_page'])

        # 에러 확인
        if 'error' in table:
            stats['tables_with_errors'] += 1
            continue

        # 대분류/중분류 카운트
        if table.get('대분류'):
            stats['categories'][table['대분류']] += 1
        if table.get('중분류'):
            stats['mid_categories'][table['중분류']] += 1

        # 항목 수 계산
        items = table.get('items', [])
        stats['total_items'] += len(items)

        # 조건 및 하위 조건 수 계산
        for item in items:
            conditions = item.get('conditions', [])
            stats['total_conditions'] += len(conditions)

            for cond in conditions:
                # 하위 조건
                sub_conds = cond.get('sub_conditions', [])
                stats['total_sub_conditions'] += len(sub_conds)

                # 조건 레벨 비고
                stats['total_notes'] += len(cond.get('notes', []))

                # 하위 조건 레벨 비고
                for sub in sub_conds:
                    stats['total_notes'] += len(sub.get('notes', []))

            # 항목 레벨 비고
            stats['total_notes'] += len(item.get('notes', []))

        # 표 레벨 비고
        stats['total_notes'] += len(table.get('notes', []))

    return stats


def validate_structure(table: dict, table_idx: int) -> list:
    """표 구조 검증"""
    errors = []

    # 필수 필드 확인
    required_fields = ['소분류', 'items', 'notes', 'reference', 'source_page']
    for field in required_fields:
        if field not in table:
            errors.append(f"Table {table_idx}: Missing required field '{field}'")

    # items 구조 검증
    if 'items' in table:
        for item_idx, item in enumerate(table['items'], 1):
            required_item_fields = ['id', 'dispute_type', 'resolution', 'conditions', 'notes']
            for field in required_item_fields:
                if field not in item:
                    errors.append(f"Table {table_idx}, Item {item_idx}: Missing field '{field}'")

            # conditions 구조 검증
            if 'conditions' in item:
                for cond_idx, cond in enumerate(item['conditions'], 1):
                    required_cond_fields = ['condition', 'resolution', 'sub_conditions', 'notes']
                    for field in required_cond_fields:
                        if field not in cond:
                            errors.append(f"Table {table_idx}, Item {item_idx}, Condition {cond_idx}: Missing field '{field}'")

    # reference 구조 검증
    if 'reference' in table:
        ref = table['reference']
        if not isinstance(ref, dict):
            errors.append(f"Table {table_idx}: 'reference' should be a dict")
        elif '근거법령' not in ref or '기타법령' not in ref:
            errors.append(f"Table {table_idx}: 'reference' missing required fields")

    return errors


def validate_notes_mapping(table: dict, table_idx: int) -> list:
    """비고 매핑 검증"""
    warnings = []

    for item_idx, item in enumerate(table.get('items', []), 1):
        # 항목 레벨 비고 검증
        for note_idx, note in enumerate(item.get('notes', []), 1):
            if not isinstance(note, dict):
                warnings.append(f"Table {table_idx}, Item {item_idx}, Note {note_idx}: Note should be a dict")
                continue

            # keyword와 matched_by 일관성 확인
            keyword = note.get('keyword', '')
            matched_by = note.get('matched_by', '')

            if keyword and matched_by != 'keyword':
                warnings.append(f"Table {table_idx}, Item {item_idx}, Note {note_idx}: Has keyword '{keyword}' but matched_by is '{matched_by}'")

            if not keyword and matched_by == 'keyword':
                warnings.append(f"Table {table_idx}, Item {item_idx}, Note {note_idx}: matched_by is 'keyword' but keyword is empty")

        # 조건 레벨 비고 검증
        for cond_idx, cond in enumerate(item.get('conditions', []), 1):
            for note_idx, note in enumerate(cond.get('notes', []), 1):
                if not isinstance(note, dict):
                    continue

                keyword = note.get('keyword', '')
                matched_by = note.get('matched_by', '')

                if keyword and matched_by != 'keyword':
                    warnings.append(f"Table {table_idx}, Item {item_idx}, Cond {cond_idx}, Note {note_idx}: Keyword/matched_by mismatch")

    return warnings


def validate_forward_fill(data: dict) -> list:
    """대분류/중분류 forward fill 검증"""
    errors = []

    last_대분류 = ""
    last_중분류 = ""

    for idx, table in enumerate(data['data'], 1):
        if 'error' in table:
            continue

        current_대분류 = table.get('대분류', '')
        current_중분류 = table.get('중분류', '')

        # 대분류가 비어있는데 이전에도 없었으면 문제
        if not current_대분류 and not last_대분류:
            errors.append(f"Table {idx}: 대분류 is empty and no previous 대분류 to inherit")

        # 대분류 업데이트
        if current_대분류:
            last_대분류 = current_대분류

        # 중분류 업데이트
        if current_중분류:
            last_중분류 = current_중분류

    return errors


def print_sample_data(data: dict, num_samples: int = 3):
    """샘플 데이터 출력"""
    print(f"\n{'='*80}")
    print(f"샘플 데이터 출력 (처음 {num_samples}개 표)")
    print(f"{'='*80}\n")

    for idx, table in enumerate(data['data'][:num_samples], 1):
        print(f"[표 {idx}] 페이지 {table.get('source_page', '?')}")
        print(f"  대분류: {table.get('대분류', '(없음)')}")
        print(f"  중분류: {table.get('중분류', '(없음)')}")
        print(f"  소분류: {table.get('소분류', '(없음)')}")
        print(f"  항목 수: {len(table.get('items', []))}")

        # 첫 번째 항목 상세 출력
        if table.get('items'):
            item = table['items'][0]
            print(f"\n  [첫 번째 항목]")
            print(f"    ID: {item.get('id', '?')}")
            print(f"    분쟁유형: {item.get('dispute_type', '')[:50]}...")
            print(f"    조건 수: {len(item.get('conditions', []))}")
            print(f"    비고 수: {len(item.get('notes', []))}")

        print()


def generate_report(stats: dict, structure_errors: list, notes_warnings: list, ff_errors: list):
    """검증 리포트 생성"""
    print(f"\n{'='*80}")
    print("Gemini 파싱 결과 검증 리포트")
    print(f"{'='*80}\n")

    # 기본 통계
    print("[기본 통계]")
    print(f"  총 테이블 수: {stats['total_tables']}개")
    print(f"  총 분쟁항목 수: {stats['total_items']}개")
    print(f"  총 조건 수: {stats['total_conditions']}개")
    print(f"  총 하위조건 수: {stats['total_sub_conditions']}개")
    print(f"  총 비고 수: {stats['total_notes']}개")
    print(f"  커버된 페이지: {sorted(stats['pages_covered'])}")
    print(f"  페이지 범위: {min(stats['pages_covered'])} ~ {max(stats['pages_covered'])}")

    # 대분류/중분류 통계
    print(f"\n[대분류 분포]")
    for cat, count in sorted(stats['categories'].items()):
        print(f"  {cat}: {count}개 표")

    print(f"\n[중분류 분포] (상위 5개)")
    sorted_mid = sorted(stats['mid_categories'].items(), key=lambda x: x[1], reverse=True)
    for cat, count in sorted_mid[:5]:
        print(f"  {cat}: {count}개 표")

    # 에러 리포트
    print(f"\n[구조 검증 결과]")
    if structure_errors:
        print(f"  [ERROR] {len(structure_errors)}개 오류 발견:")
        for error in structure_errors[:10]:  # 처음 10개만
            print(f"    - {error}")
        if len(structure_errors) > 10:
            print(f"    ... 외 {len(structure_errors) - 10}개")
    else:
        print(f"  [OK] 구조 검증 통과!")

    # 비고 매핑 경고
    print(f"\n[비고 매핑 검증 결과]")
    if notes_warnings:
        print(f"  [WARNING] {len(notes_warnings)}개 경고:")
        for warning in notes_warnings[:10]:  # 처음 10개만
            print(f"    - {warning}")
        if len(notes_warnings) > 10:
            print(f"    ... 외 {len(notes_warnings) - 10}개")
    else:
        print(f"  [OK] 비고 매핑 검증 통과!")

    # Forward fill 검증
    print(f"\n[Forward Fill 검증 결과]")
    if ff_errors:
        print(f"  [ERROR] {len(ff_errors)}개 오류 발견:")
        for error in ff_errors:
            print(f"    - {error}")
    else:
        print(f"  [OK] Forward fill 검증 통과!")

    # 에러 있는 표
    if stats['tables_with_errors'] > 0:
        print(f"\n[파싱 에러]")
        print(f"  [ERROR] {stats['tables_with_errors']}개 표에서 파싱 에러 발생")

    # 종합 평가
    print(f"\n{'='*80}")
    print("[종합 평가]")

    total_issues = len(structure_errors) + len(ff_errors) + stats['tables_with_errors']

    if total_issues == 0:
        print("  [EXCELLENT] 모든 검증 통과! 파싱 결과가 우수합니다.")
        print(f"  등급: 5/5 (★★★★★)")
    elif total_issues < 5:
        print(f"  [GOOD] {total_issues}개의 사소한 문제 발견. 대체로 양호합니다.")
        print(f"  등급: 4/5 (★★★★)")
    elif total_issues < 20:
        print(f"  [WARNING] {total_issues}개의 문제 발견. 일부 수정이 필요합니다.")
        print(f"  등급: 3/5 (★★★)")
    else:
        print(f"  [ERROR] {total_issues}개의 문제 발견. 재파싱을 검토하세요.")
        print(f"  등급: 2/5 (★★)")

    print(f"{'='*80}\n")


def main():
    """메인 함수"""
    print("Gemini 파싱 결과 검증 시작...\n")

    # JSON 파일 로드
    if not os.path.exists(JSON_PATH):
        print(f"❌ 파일을 찾을 수 없습니다: {JSON_PATH}")
        return

    data = load_json(JSON_PATH)

    # 1. 기본 통계 계산
    print("[1/5] 통계 계산 중...")
    stats = calculate_statistics(data)

    # 2. 구조 검증
    print("[2/5] 구조 검증 중...")
    structure_errors = []
    for idx, table in enumerate(data['data'], 1):
        if 'error' not in table:
            errors = validate_structure(table, idx)
            structure_errors.extend(errors)

    # 3. 비고 매핑 검증
    print("[3/5] 비고 매핑 검증 중...")
    notes_warnings = []
    for idx, table in enumerate(data['data'], 1):
        if 'error' not in table:
            warnings = validate_notes_mapping(table, idx)
            notes_warnings.extend(warnings)

    # 4. Forward fill 검증
    print("[4/5] Forward fill 검증 중...")
    ff_errors = validate_forward_fill(data)

    # 5. 샘플 데이터 출력
    print_sample_data(data, num_samples=3)

    # 6. 리포트 생성
    generate_report(stats, structure_errors, notes_warnings, ff_errors)


if __name__ == "__main__":
    main()
