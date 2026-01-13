"""
분쟁조정기준 계층 검색 함수

Stage 1: category/industry/item_group 키워드 검색 (RDB)
Stage 2: items/dispute_type/resolution Vector 검색 (Vector DB)
"""
import os
from typing import Dict, List, Any, Optional
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

import psycopg
from psycopg.rows import dict_row
from pgvector.psycopg import register_vector
from pgvector import Vector


def conninfo_from_env() -> str:
    return (
        f"host={os.environ.get('PGHOST', 'localhost')} "
        f"port={os.environ.get('PGPORT', '5432')} "
        f"dbname={os.environ.get('PGDATABASE', 'ddoksori_db')} "
        f"user={os.environ.get('PGUSER', 'postgres')} "
        f"password={os.environ.get('PGPASSWORD', '')}"
    )


def match_items_stage1(
    item_name: str,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Stage 1: 품목 매칭 (별표1)
    
    category/industry/item_group 레벨에서 키워드 검색
    """
    conninfo = conninfo_from_env()
    
    with psycopg.connect(conninfo, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # 별표1에서 품목명으로 검색
            cur.execute("""
                SELECT 
                    unit_id, unit_text, doc,
                    category, industry, item_group, item
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
                LIMIT %s
            """, (
                f"%{item_name}%",
                f"%{item_name}%",
                f"%{item_name}%",
                f"%{item_name}%",
                f"%{item_name}%",
                limit
            ))
            
            results = []
            for row in cur:
                payload = row.get("doc", {}).get("payload", {})
                results.append({
                    "unit_id": row["unit_id"],
                    "unit_text": row["unit_text"],
                    "category": row.get("category") or payload.get("category"),
                    "industry": row.get("industry") or payload.get("industry"),
                    "item_group": row.get("item_group") or payload.get("item_group"),
                    "items": payload.get("items", []),
                    "doc": row.get("doc", {})
                })
            
            return results


def search_resolutions_stage2(
    matched_items: List[Dict[str, Any]],
    dispute_type: Optional[str] = None,
    query_text: Optional[str] = None,
    limit: int = 10,
    embedding_model: str = "text-embedding-3-small"
) -> List[Dict[str, Any]]:
    """
    Stage 2: 해결기준 검색 (별표2)
    
    Stage 1 결과의 category/industry/item_group로 필터링 후
    dispute_type + resolution Vector 검색
    """
    if not matched_items:
        return []
    
    conninfo = conninfo_from_env()
    
    # Stage 1 결과에서 추출한 필터 조건
    categories = list(set([item.get("category") for item in matched_items if item.get("category")]))
    industries = list(set([item.get("industry") for item in matched_items if item.get("industry")]))
    item_groups = list(set([item.get("item_group") for item in matched_items if item.get("item_group")]))
    
    with psycopg.connect(conninfo, row_factory=dict_row) as conn:
        register_vector(conn)
        
        with conn.cursor() as cur:
            # 필터 조건 구성
            conditions = ["source_id = 'table2'", "search_stage = 'stage2'"]
            params = []
            
            if categories:
                placeholders = ','.join(['%s'] * len(categories))
                conditions.append(f"category IN ({placeholders})")
                params.extend(categories)
            
            if item_groups:
                placeholders = ','.join(['%s'] * len(item_groups))
                conditions.append(f"item_group IN ({placeholders})")
                params.extend(item_groups)
            
            # dispute_type 필터
            if dispute_type:
                conditions.append("dispute_type LIKE %s")
                params.append(f"%{dispute_type}%")
            
            # TODO: Vector 검색 구현 (임베딩 API 연결 필요)
            # 현재는 텍스트 검색으로 폴백
            if query_text:
                conditions.append("(unit_text LIKE %s OR dispute_type LIKE %s)")
                params.extend([f"%{query_text}%", f"%{query_text}%"])
            
            where_clause = " AND ".join(conditions)
            
            sql = f"""
                SELECT 
                    unit_id, unit_text, doc,
                    category, item_group, item, dispute_type
                FROM criteria_units
                WHERE {where_clause}
                ORDER BY 
                    CASE 
                        WHEN dispute_type LIKE %s THEN 1
                        ELSE 2
                    END
                LIMIT %s
            """
            
            dispute_pattern = f"%{dispute_type}%" if dispute_type else "%"
            params.extend([dispute_pattern, limit])
            
            cur.execute(sql, params)
            
            results = []
            for row in cur:
                payload = row.get("doc", {}).get("payload", {})
                results.append({
                    "unit_id": row["unit_id"],
                    "unit_text": row["unit_text"],
                    "category": row.get("category") or payload.get("category"),
                    "item_group": row.get("item_group") or payload.get("item_group"),
                    "item": row.get("item") or payload.get("item"),
                    "dispute_type": row.get("dispute_type") or payload.get("dispute_type"),
                    "resolution": payload.get("resolution"),
                    "doc": row.get("doc", {})
                })
            
            return results


def search_criteria_hierarchical(
    user_query: str,
    item_name: Optional[str] = None,
    dispute_type: Optional[str] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    계층적 분쟁조정기준 검색
    
    Stage 1: category/industry/item_group 키워드 검색
    Stage 2: items/dispute_type/resolution Vector 검색
    
    Args:
        user_query: 사용자 검색 쿼리
        item_name: 품목명 (선택)
        dispute_type: 분쟁 유형 (선택)
        limit: 최종 결과 개수 제한
    
    Returns:
        {
            "stage1": {
                "count": int,
                "results": List[Dict]
            },
            "stage2": {
                "count": int,
                "results": List[Dict]
            }
        }
    """
    # Stage 1: 품목 매칭 (별표1)
    search_term = item_name or user_query
    matched_items = match_items_stage1(search_term, limit=limit * 2)
    
    if not matched_items:
        return {
            "stage1": {"count": 0, "results": []},
            "stage2": {"count": 0, "results": []},
            "message": "Stage 1 검색 결과가 없습니다."
        }
    
    # Stage 2: 해결기준 검색 (별표2)
    resolutions = search_resolutions_stage2(
        matched_items,
        dispute_type=dispute_type,
        query_text=user_query,
        limit=limit
    )
    
    return {
        "stage1": {
            "count": len(matched_items),
            "results": matched_items[:5]  # 상위 5개만 표시
        },
        "stage2": {
            "count": len(resolutions),
            "results": resolutions
        }
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python search_criteria_hierarchical.py <query> [item_name] [dispute_type]")
        sys.exit(1)
    
    query = sys.argv[1]
    item_name = sys.argv[2] if len(sys.argv) > 2 else None
    dispute_type = sys.argv[3] if len(sys.argv) > 3 else None
    
    print(f"검색 쿼리: {query}")
    if item_name:
        print(f"품목명: {item_name}")
    if dispute_type:
        print(f"분쟁 유형: {dispute_type}")
    print()
    
    results = search_criteria_hierarchical(
        query,
        item_name=item_name,
        dispute_type=dispute_type,
        limit=5
    )
    
    print(f"Stage 1 결과: {results['stage1']['count']}개")
    for i, item in enumerate(results['stage1']['results'], 1):
        print(f"  [{i}] {item.get('item_group', 'N/A')} - {item.get('unit_text', '')[:50]}...")
    
    print(f"\nStage 2 결과: {results['stage2']['count']}개")
    for i, res in enumerate(results['stage2']['results'], 1):
        print(f"  [{i}] {res.get('dispute_type', 'N/A')}")
        print(f"      해결기준: {res.get('resolution', 'N/A')[:50]}...")
