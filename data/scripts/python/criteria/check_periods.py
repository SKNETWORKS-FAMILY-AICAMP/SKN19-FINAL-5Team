"""
기간 검토 함수

품질보증기간, 유통기간/소비기한, 청약철회 기간 등을 확인합니다.
"""
import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

load_dotenv()

import psycopg
from psycopg.rows import dict_row


def conninfo_from_env() -> str:
    return (
        f"host={os.environ.get('PGHOST', 'localhost')} "
        f"port={os.environ.get('PGPORT', '5432')} "
        f"dbname={os.environ.get('PGDATABASE', 'ddoksori_db')} "
        f"user={os.environ.get('PGUSER', 'postgres')} "
        f"password={os.environ.get('PGPASSWORD', '')}"
    )


def parse_warranty_period(warranty_text: str) -> Optional[Dict[str, Any]]:
    """
    품질보증기간 텍스트에서 기간 정보 추출
    
    예: "2년 이내" -> {"years": 2, "unit": "year"}
    예: "1년 이내. 다만, 주행거리가 1만㎞를 초과한 경우에는 기간이 만료된 것으로 함"
    """
    if not warranty_text:
        return None
    
    # 년 단위 추출
    year_match = re.search(r'(\d+)년', warranty_text)
    if year_match:
        years = int(year_match.group(1))
        return {
            "years": years,
            "unit": "year",
            "text": warranty_text,
            "has_condition": "다만" in warranty_text or "단," in warranty_text
        }
    
    # 월 단위 추출
    month_match = re.search(r'(\d+)개월', warranty_text)
    if month_match:
        months = int(month_match.group(1))
        return {
            "months": months,
            "unit": "month",
            "text": warranty_text,
            "has_condition": "다만" in warranty_text or "단," in warranty_text
        }
    
    # 일 단위 추출
    day_match = re.search(r'(\d+)일', warranty_text)
    if day_match:
        days = int(day_match.group(1))
        return {
            "days": days,
            "unit": "day",
            "text": warranty_text,
            "has_condition": "다만" in warranty_text or "단," in warranty_text
        }
    
    return None


def get_warranty_period(item: str) -> Optional[Dict[str, Any]]:
    """
    별표3에서 품목의 품질보증기간 조회
    """
    conninfo = conninfo_from_env()
    
    try:
        with psycopg.connect(conninfo, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                # 품목명으로 검색
                cur.execute("""
                    SELECT 
                        unit_id, unit_text, doc
                    FROM criteria_units
                    WHERE source_id = 'table3'
                      AND (
                        unit_text LIKE %s
                        OR doc->'payload'->>'item' LIKE %s
                      )
                    LIMIT 1
                """, (
                    f"%{item}%",
                    f"%{item}%"
                ))
                
                row = cur.fetchone()
                if row:
                    payload = row.get("doc", {}).get("payload", {})
                    warranty_period_text = payload.get("warranty_period")
                    if warranty_period_text:
                        parsed = parse_warranty_period(warranty_period_text)
                        if parsed:
                            parsed["item"] = payload.get("item")
                            parsed["unit_text"] = row["unit_text"]
                            return parsed
    except Exception as e:
        print(f"[WARN] 품질보증기간 조회 실패: {e}")
    
    return None


def check_warranty_period(
    item: str,
    purchase_date: datetime,
    current_date: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    품질보증기간 경과 여부 확인
    
    Args:
        item: 품목명
        purchase_date: 구매 일자
        current_date: 현재 일자 (None이면 오늘)
    
    Returns:
        {
            "is_passed": True/False,
            "warranty_info": {...},
            "days_remaining": int (경과 시 음수),
            "message": str
        }
    """
    if current_date is None:
        current_date = datetime.now()
    
    warranty_info = get_warranty_period(item)
    
    if not warranty_info:
        return {
            "is_passed": None,
            "warranty_info": None,
            "days_remaining": None,
            "message": "품질보증기간 정보를 찾을 수 없습니다."
        }
    
    # 기간 계산
    warranty_end = purchase_date
    if "years" in warranty_info:
        warranty_end = purchase_date + timedelta(days=warranty_info["years"] * 365)
    elif "months" in warranty_info:
        warranty_end = purchase_date + timedelta(days=warranty_info["months"] * 30)
    elif "days" in warranty_info:
        warranty_end = purchase_date + timedelta(days=warranty_info["days"])
    
    is_passed = current_date > warranty_end
    days_remaining = (warranty_end - current_date).days
    
    if is_passed:
        message = f"품질보증기간이 경과했습니다. (만료일: {warranty_end.strftime('%Y-%m-%d')})"
    else:
        message = f"품질보증기간 내입니다. (만료일: {warranty_end.strftime('%Y-%m-%d')}, 남은 일수: {days_remaining}일)"
    
    return {
        "is_passed": is_passed,
        "warranty_info": warranty_info,
        "warranty_end": warranty_end,
        "days_remaining": days_remaining,
        "message": message
    }


def check_distribution_period(
    item: str,
    purchase_date: datetime,
    current_date: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    유통기간/소비기한 경과 여부 확인
    
    별표2의 dispute_type_id: 3 ("유통기간 경과", "소비기한 경과")와 관련
    실제 유통기한 정보는 별도로 관리되어야 하므로, 기본적인 확인만 수행
    """
    if current_date is None:
        current_date = datetime.now()
    
    # 일반적으로 식품의 경우 구매 후 7일 이내 확인 권장
    # 실제로는 상품의 유통기한 정보가 필요함
    days_since_purchase = (current_date - purchase_date).days
    
    return {
        "is_passed": None,  # 유통기한 정보가 없어 판단 불가
        "days_since_purchase": days_since_purchase,
        "message": f"구매 후 {days_since_purchase}일 경과. 유통기한 정보 확인 필요."
    }


def check_cooling_off_period(
    purchase_date: datetime,
    current_date: Optional[datetime] = None,
    is_online: bool = True
) -> Dict[str, Any]:
    """
    청약철회 기간 확인 (전자상거래 지침)
    
    인터넷 쇼핑몰 구매 시 7일 이내 여부 확인
    
    Args:
        purchase_date: 구매 일자
        current_date: 현재 일자 (None이면 오늘)
        is_online: 인터넷 쇼핑몰 구매 여부
    
    Returns:
        {
            "is_within_period": True/False,
            "days_remaining": int,
            "message": str
        }
    """
    if not is_online:
        return {
            "is_within_period": None,
            "days_remaining": None,
            "message": "오프라인 구매는 청약철회 기간이 적용되지 않습니다."
        }
    
    if current_date is None:
        current_date = datetime.now()
    
    # 청약철회 기간: 7일
    cooling_off_end = purchase_date + timedelta(days=7)
    is_within_period = current_date <= cooling_off_end
    days_remaining = (cooling_off_end - current_date).days
    
    if is_within_period:
        message = f"청약철회 가능 기간 내입니다. (만료일: {cooling_off_end.strftime('%Y-%m-%d')}, 남은 일수: {days_remaining}일)"
    else:
        message = f"청약철회 기간이 경과했습니다. (만료일: {cooling_off_end.strftime('%Y-%m-%d')})"
    
    return {
        "is_within_period": is_within_period,
        "cooling_off_end": cooling_off_end,
        "days_remaining": days_remaining,
        "message": message
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python check_periods.py <item> <purchase_date> [current_date]")
        print("Example: python check_periods.py '계란' '2024-01-15'")
        sys.exit(1)
    
    item = sys.argv[1]
    purchase_date = datetime.strptime(sys.argv[2], "%Y-%m-%d")
    current_date = datetime.strptime(sys.argv[3], "%Y-%m-%d") if len(sys.argv) > 3 else None
    
    print(f"=== 기간 검토: {item} ===")
    print(f"구매 일자: {purchase_date.strftime('%Y-%m-%d')}")
    print()
    
    # 품질보증기간 확인
    warranty_result = check_warranty_period(item, purchase_date, current_date)
    print("품질보증기간:")
    print(f"  {warranty_result['message']}")
    if warranty_result.get('warranty_info'):
        print(f"  정보: {warranty_result['warranty_info']['text']}")
    print()
    
    # 유통기간 확인
    dist_result = check_distribution_period(item, purchase_date, current_date)
    print("유통기간:")
    print(f"  {dist_result['message']}")
    print()
    
    # 청약철회 기간 확인 (인터넷 쇼핑몰 가정)
    cooling_result = check_cooling_off_period(purchase_date, current_date, is_online=True)
    print("청약철회 기간 (인터넷 쇼핑몰):")
    print(f"  {cooling_result['message']}")
