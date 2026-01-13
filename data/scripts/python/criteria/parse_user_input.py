"""
사용자 입력 파싱 및 분석

구매 일자, 구매처, 구매 품목, 구매 금액, 분쟁 상세 내용을 분석하여
품목 매칭, 분쟁 유형 추출, 구매처 분석 등을 수행합니다.
"""
import re
from datetime import datetime
from typing import Dict, List, Any, Optional
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()


def conninfo_from_env() -> str:
    import os
    return (
        f"host={os.environ.get('PGHOST', 'localhost')} "
        f"port={os.environ.get('PGPORT', '5432')} "
        f"dbname={os.environ.get('PGDATABASE', 'ddoksori_db')} "
        f"user={os.environ.get('PGUSER', 'postgres')} "
        f"password={os.environ.get('PGPASSWORD', '')}"
    )


# 인터넷 쇼핑몰 키워드
ONLINE_MARKETPLACE_KEYWORDS = [
    "네이버", "naver", "쿠팡", "coupang", "11번가", "11st",
    "지마켓", "gmarket", "옥션", "auction", "티몬", "tmon",
    "위메프", "wemakeprice", "인터파크", "interpark", "롯데온", "lotteon",
    "신세계몰", "ssg", "이마트몰", "emart", "홈플러스", "homeplus",
    "인터넷", "온라인", "쇼핑몰", "쇼핑", "온라인쇼핑"
]


def detect_online_marketplace(seller_info: str) -> bool:
    """구매처 정보에서 인터넷 쇼핑몰 여부 판단"""
    if not seller_info:
        return False
    
    seller_lower = seller_info.lower()
    for keyword in ONLINE_MARKETPLACE_KEYWORDS:
        if keyword.lower() in seller_lower:
            return True
    
    return False


# 분쟁 유형 키워드 매핑
DISPUTE_TYPE_KEYWORDS = {
    "환불": ["환불", "환불 불가", "환불 거부", "환불 요구", "환불 거절"],
    "교환": ["교환", "교환 불가", "교환 거부", "교환 요구", "교환 거절"],
    "청약철회": ["청약철회", "계약 해제", "계약 취소", "철회", "취소"],
    "위약금": ["위약금", "과도한 위약금", "위약금 요구", "위약금 부담"],
    "부패 변질": ["부패", "변질", "상한", "썩음", "부패된", "변질된"],
    "하자": ["하자", "결함", "불량", "문제", "고장", "손상"],
    "함량 부족": ["함량", "용량", "중량", "개수", "부족", "미달"],
    "이물혼입": ["이물", "혼입", "이물질", "이물 발견"],
    "유통기간": ["유통기한", "유통기간", "소비기한", "기한 경과"],
    "표시 상이": ["표시", "표기", "내용 상이", "다름", "틀림"]
}


def extract_dispute_types(dispute_detail: str) -> List[str]:
    """
    분쟁 상세 내용에서 분쟁 유형 추출
    
    키워드 매칭 기반으로 분쟁 유형을 추출합니다.
    """
    if not dispute_detail:
        return []
    
    dispute_lower = dispute_detail.lower()
    matched_types = []
    
    for dispute_type, keywords in DISPUTE_TYPE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in dispute_lower:
                if dispute_type not in matched_types:
                    matched_types.append(dispute_type)
                break
    
    return matched_types


def match_item_from_table1(item_name: str) -> Optional[Dict[str, Any]]:
    """
    별표1에서 품목 매칭
    
    품목명으로 별표1을 검색하여 category, industry, item_group을 찾습니다.
    """
    conninfo = conninfo_from_env()
    
    try:
        with psycopg.connect(conninfo, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        unit_id, unit_text, doc,
                        category, industry, item_group
                    FROM criteria_units
                    WHERE source_id = 'table1'
                      AND search_stage = 'stage1'
                      AND (
                        unit_text LIKE %s
                        OR doc->'payload'->>'item_group' LIKE %s
                        OR doc->'payload'->'items'::text LIKE %s
                      )
                    ORDER BY 
                        CASE 
                            WHEN doc->'payload'->'items'::text LIKE %s THEN 1
                            WHEN doc->'payload'->>'item_group' LIKE %s THEN 2
                            ELSE 3
                        END
                    LIMIT 1
                """, (
                    f"%{item_name}%",
                    f"%{item_name}%",
                    f"%{item_name}%",
                    f"%{item_name}%",
                    f"%{item_name}%"
                ))
                
                row = cur.fetchone()
                if row:
                    payload = row.get("doc", {}).get("payload", {})
                    return {
                        "unit_id": row["unit_id"],
                        "category": row.get("category") or payload.get("category"),
                        "industry": row.get("industry") or payload.get("industry"),
                        "item_group": row.get("item_group") or payload.get("item_group"),
                        "items": payload.get("items", []),
                        "unit_text": row["unit_text"]
                    }
    except Exception as e:
        print(f"[WARN] 품목 매칭 실패: {e}")
    
    return None


def parse_user_input(
    purchase_date: str,
    seller_info: str,
    item: str,
    purchase_amount: float,
    dispute_detail: str
) -> Dict[str, Any]:
    """
    사용자 입력 파싱 및 분석
    
    Args:
        purchase_date: "2024-01-15" 형식
        seller_info: "네이버 쇼핑" 또는 "오프라인 매장명"
        item: "계란"
        purchase_amount: 10000.0
        dispute_detail: "환불 불가, 부패된 상품"
    
    Returns:
        {
            "item": "계란",
            "item_matched": {
                "category": "상품(재화)",
                "industry": "농ㆍ수ㆍ축산물",
                "item_group": "란류"
            },
            "dispute_types": ["환불", "부패 변질"],
            "is_online": True/False,
            "purchase_date": datetime,
            "purchase_amount": 10000.0,
            "dispute_keywords": ["환불 불가", "부패"]
        }
    """
    # 구매 일자 파싱
    try:
        purchase_dt = datetime.strptime(purchase_date, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"구매 일자 형식이 올바르지 않습니다: {purchase_date} (예: 2024-01-15)")
    
    # 인터넷 쇼핑몰 여부 판단
    is_online = detect_online_marketplace(seller_info)
    
    # 분쟁 유형 추출
    dispute_types = extract_dispute_types(dispute_detail)
    
    # 품목 매칭 (별표1)
    item_matched = match_item_from_table1(item)
    
    # 분쟁 키워드 추출 (간단한 키워드 추출)
    dispute_keywords = []
    for dispute_type, keywords in DISPUTE_TYPE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in dispute_detail:
                dispute_keywords.append(keyword)
                break
    
    return {
        "item": item,
        "item_matched": item_matched,
        "dispute_types": dispute_types,
        "is_online": is_online,
        "purchase_date": purchase_dt,
        "purchase_amount": purchase_amount,
        "dispute_keywords": dispute_keywords,
        "seller_info": seller_info,
        "dispute_detail": dispute_detail
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 6:
        print("Usage: python parse_user_input.py <purchase_date> <seller_info> <item> <purchase_amount> <dispute_detail>")
        print("Example: python parse_user_input.py 2024-01-15 '네이버 쇼핑' '계란' 10000 '환불 불가, 부패된 상품'")
        sys.exit(1)
    
    purchase_date = sys.argv[1]
    seller_info = sys.argv[2]
    item = sys.argv[3]
    purchase_amount = float(sys.argv[4])
    dispute_detail = sys.argv[5]
    
    result = parse_user_input(
        purchase_date,
        seller_info,
        item,
        purchase_amount,
        dispute_detail
    )
    
    print("=== 사용자 입력 분석 결과 ===")
    print(f"품목: {result['item']}")
    print(f"품목 매칭: {result['item_matched']}")
    print(f"분쟁 유형: {result['dispute_types']}")
    print(f"인터넷 쇼핑몰: {result['is_online']}")
    print(f"구매 일자: {result['purchase_date']}")
    print(f"구매 금액: {result['purchase_amount']}")
    print(f"분쟁 키워드: {result['dispute_keywords']}")
