"""
사용자 상황과 분쟁조정기준 해결방안 매칭

사용자 입력과 분쟁조정기준 해결기준을 비교하여
적용 가능 여부와 매칭 점수를 계산합니다.
"""
from typing import Dict, List, Any, Optional
from datetime import datetime
import sys
from pathlib import Path

# 상대 import를 위한 경로 추가
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from parse_user_input import parse_user_input
from check_periods import check_warranty_period, check_cooling_off_period, check_distribution_period
from search_criteria_hierarchical import search_criteria_hierarchical


def calculate_match_score(
    user_input: Dict[str, Any],
    criteria_resolution: Dict[str, Any]
) -> float:
    """
    매칭 점수 계산 (0.0-1.0)
    
    - 품목 매칭: 0.3
    - 분쟁 유형 매칭: 0.4
    - 기간 조건 충족: 0.2
    - 구매처 조건 충족: 0.1
    """
    score = 0.0
    
    # 1. 품목 매칭 (0.3)
    item_matched = user_input.get("item_matched")
    if item_matched:
        criteria_category = criteria_resolution.get("category")
        criteria_item_group = criteria_resolution.get("item_group")
        
        if criteria_category and item_matched.get("category") == criteria_category:
            score += 0.15
        if criteria_item_group and item_matched.get("item_group") == criteria_item_group:
            score += 0.15
    
    # 2. 분쟁 유형 매칭 (0.4)
    user_dispute_types = user_input.get("dispute_types", [])
    criteria_dispute_type = criteria_resolution.get("dispute_type", "")
    
    if criteria_dispute_type:
        for user_type in user_dispute_types:
            if user_type in criteria_dispute_type or criteria_dispute_type in user_type:
                score += 0.4
                break
        else:
            # 부분 매칭
            for user_type in user_dispute_types:
                if any(keyword in criteria_dispute_type for keyword in user_type.split()):
                    score += 0.2
                    break
    
    # 3. 기간 조건 충족 (0.2)
    # 품질보증기간 확인
    item = user_input.get("item")
    purchase_date = user_input.get("purchase_date")
    if item and purchase_date:
        warranty_result = check_warranty_period(item, purchase_date)
        if warranty_result.get("is_passed") is False:  # 기간 내
            score += 0.1
        elif warranty_result.get("is_passed") is True:  # 기간 경과
            score -= 0.1  # 감점
    
    # 청약철회 기간 확인 (인터넷 쇼핑몰인 경우)
    is_online = user_input.get("is_online", False)
    if is_online and purchase_date:
        cooling_result = check_cooling_off_period(purchase_date, is_online=True)
        if cooling_result.get("is_within_period"):
            score += 0.1
    
    # 4. 구매처 조건 충족 (0.1)
    # 인터넷 쇼핑몰인 경우 청약철회 관련 분쟁 유형에 가점
    if is_online:
        if "청약철회" in user_input.get("dispute_types", []):
            score += 0.1
    
    return min(max(score, 0.0), 1.0)  # 0.0-1.0 범위로 제한


def check_conditions(
    user_input: Dict[str, Any],
    criteria_resolution: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    조건 검토
    
    품목 매칭, 분쟁 유형 매칭, 기간 조건 등을 확인합니다.
    """
    conditions = []
    
    # 1. 품목 매칭 확인
    item_matched = user_input.get("item_matched")
    if item_matched:
        criteria_category = criteria_resolution.get("category")
        criteria_item_group = criteria_resolution.get("item_group")
        
        if criteria_category == item_matched.get("category"):
            conditions.append({
                "type": "item_category",
                "status": "matched",
                "message": f"카테고리 일치: {criteria_category}"
            })
        else:
            conditions.append({
                "type": "item_category",
                "status": "mismatched",
                "message": f"카테고리 불일치: {item_matched.get('category')} vs {criteria_category}"
            })
        
        if criteria_item_group == item_matched.get("item_group"):
            conditions.append({
                "type": "item_group",
                "status": "matched",
                "message": f"품목 그룹 일치: {criteria_item_group}"
            })
        else:
            conditions.append({
                "type": "item_group",
                "status": "mismatched",
                "message": f"품목 그룹 불일치: {item_matched.get('item_group')} vs {criteria_item_group}"
            })
    else:
        conditions.append({
            "type": "item_match",
            "status": "unknown",
            "message": "품목 매칭 정보 없음"
        })
    
    # 2. 분쟁 유형 매칭 확인
    user_dispute_types = user_input.get("dispute_types", [])
    criteria_dispute_type = criteria_resolution.get("dispute_type", "")
    
    if user_dispute_types and criteria_dispute_type:
        matched = False
        for user_type in user_dispute_types:
            if user_type in criteria_dispute_type or criteria_dispute_type in user_type:
                matched = True
                break
        
        if matched:
            conditions.append({
                "type": "dispute_type",
                "status": "matched",
                "message": f"분쟁 유형 일치: {criteria_dispute_type}"
            })
        else:
            conditions.append({
                "type": "dispute_type",
                "status": "mismatched",
                "message": f"분쟁 유형 불일치: {user_dispute_types} vs {criteria_dispute_type}"
            })
    else:
        conditions.append({
            "type": "dispute_type",
            "status": "unknown",
            "message": "분쟁 유형 정보 없음"
        })
    
    # 3. 기간 조건 확인
    item = user_input.get("item")
    purchase_date = user_input.get("purchase_date")
    
    if item and purchase_date:
        warranty_result = check_warranty_period(item, purchase_date)
        if warranty_result.get("is_passed") is False:
            conditions.append({
                "type": "warranty_period",
                "status": "passed",
                "message": warranty_result.get("message", "품질보증기간 내")
            })
        elif warranty_result.get("is_passed") is True:
            conditions.append({
                "type": "warranty_period",
                "status": "failed",
                "message": warranty_result.get("message", "품질보증기간 경과")
            })
        else:
            conditions.append({
                "type": "warranty_period",
                "status": "unknown",
                "message": warranty_result.get("message", "품질보증기간 정보 없음")
            })
    
    # 4. 청약철회 기간 확인 (인터넷 쇼핑몰인 경우)
    is_online = user_input.get("is_online", False)
    if is_online and purchase_date:
        cooling_result = check_cooling_off_period(purchase_date, is_online=True)
        if cooling_result.get("is_within_period"):
            conditions.append({
                "type": "cooling_off_period",
                "status": "passed",
                "message": cooling_result.get("message", "청약철회 기간 내")
            })
        else:
            conditions.append({
                "type": "cooling_off_period",
                "status": "failed",
                "message": cooling_result.get("message", "청약철회 기간 경과")
            })
    
    return conditions


def match_user_situation(
    user_input: Dict[str, Any],
    criteria_resolution: Dict[str, Any]
) -> Dict[str, Any]:
    """
    사용자 상황과 분쟁조정기준 해결방안 매칭
    
    Args:
        user_input: parse_user_input() 결과
        criteria_resolution: 별표2 해결기준 레코드
    
    Returns:
        {
            "is_applicable": True/False,
            "match_score": 0.0-1.0,
            "conditions": [...],
            "resolution": "...",
            "warnings": [...],
            "estimated_refund": float
        }
    """
    # 조건 검토
    conditions = check_conditions(user_input, criteria_resolution)
    
    # 매칭 점수 계산
    match_score = calculate_match_score(user_input, criteria_resolution)
    
    # 적용 가능 여부 판단 (임계값: 0.5)
    is_applicable = match_score >= 0.5
    
    # 경고 메시지 생성
    warnings = []
    for condition in conditions:
        if condition.get("status") == "failed":
            warnings.append(condition.get("message"))
        elif condition.get("status") == "mismatched":
            warnings.append(condition.get("message"))
    
    # 배상액 추정 (구매 금액 기반)
    purchase_amount = user_input.get("purchase_amount", 0.0)
    estimated_refund = purchase_amount if is_applicable else 0.0
    
    return {
        "is_applicable": is_applicable,
        "match_score": match_score,
        "conditions": conditions,
        "resolution": criteria_resolution.get("resolution", ""),
        "warnings": warnings,
        "estimated_refund": estimated_refund
    }


def search_and_match_user_situation(
    purchase_date: str,
    seller_info: str,
    item: str,
    purchase_amount: float,
    dispute_detail: str,
    limit: int = 5
) -> Dict[str, Any]:
    """
    사용자 상황을 분석하고 적합한 분쟁조정기준을 검색하여 매칭
    
    전체 파이프라인: 입력 파싱 → 계층 검색 → 상황 매칭
    """
    # 1. 사용자 입력 파싱
    user_input = parse_user_input(
        purchase_date,
        seller_info,
        item,
        purchase_amount,
        dispute_detail
    )
    
    # 2. 계층 검색
    dispute_types = user_input.get("dispute_types", [])
    dispute_type_query = dispute_types[0] if dispute_types else None
    
    search_results = search_criteria_hierarchical(
        user_query=dispute_detail,
        item_name=item,
        dispute_type=dispute_type_query,
        limit=limit
    )
    
    # 3. 각 해결기준에 대해 매칭
    matched_results = []
    for resolution in search_results.get("stage2", {}).get("results", []):
        match_result = match_user_situation(user_input, resolution)
        matched_results.append({
            "criteria": resolution,
            "match": match_result
        })
    
    # 매칭 점수 순으로 정렬
    matched_results.sort(key=lambda x: x["match"]["match_score"], reverse=True)
    
    return {
        "user_input": user_input,
        "search_results": search_results,
        "matched_results": matched_results
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 6:
        print("Usage: python match_user_situation.py <purchase_date> <seller_info> <item> <purchase_amount> <dispute_detail>")
        print("Example: python match_user_situation.py 2024-01-15 '네이버 쇼핑' '계란' 10000 '환불 불가, 부패된 상품'")
        sys.exit(1)
    
    purchase_date = sys.argv[1]
    seller_info = sys.argv[2]
    item = sys.argv[3]
    purchase_amount = float(sys.argv[4])
    dispute_detail = sys.argv[5]
    
    result = search_and_match_user_situation(
        purchase_date,
        seller_info,
        item,
        purchase_amount,
        dispute_detail
    )
    
    print("=== 사용자 상황 매칭 결과 ===")
    print(f"품목: {result['user_input']['item']}")
    print(f"분쟁 유형: {result['user_input']['dispute_types']}")
    print(f"인터넷 쇼핑몰: {result['user_input']['is_online']}")
    print()
    
    print(f"매칭된 해결기준: {len(result['matched_results'])}개")
    for i, matched in enumerate(result['matched_results'], 1):
        match_info = matched["match"]
        criteria = matched["criteria"]
        print(f"\n[{i}] 매칭 점수: {match_info['match_score']:.2f}")
        print(f"    적용 가능: {match_info['is_applicable']}")
        print(f"    분쟁 유형: {criteria.get('dispute_type', 'N/A')}")
        print(f"    해결기준: {criteria.get('resolution', 'N/A')[:50]}...")
        if match_info.get('warnings'):
            print(f"    경고: {', '.join(match_info['warnings'])}")
