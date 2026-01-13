"""
법령 데이터 질의 라우팅 유틸리티

입력 쿼리를 분석하여 RDB 정확조회 또는 Vector 유사도 검색으로 라우팅합니다.
"""
import os
import re
import json
from typing import List, Dict, Any, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

import psycopg
from pgvector.psycopg import register_vector
from pgvector import Vector


def conninfo_from_env() -> str:
    return (
        f"host={os.environ.get('PGHOST','localhost')} "
        f"port={os.environ.get('PGPORT','5433')} "
        f"dbname={os.environ.get('PGDATABASE','postgres')} "
        f"user={os.environ.get('PGUSER','postgres')} "
        f"password={os.environ.get('PGPASSWORD','postgres')}"
    )


# 조문 번호 패턴
ARTICLE_PATTERN = re.compile(r"제\s*(\d+)\s*조")
ARTICLE_WITH_BRANCH = re.compile(r"제\s*(\d+)\s*조\s*의\s*(\d+)")
PARAGRAPH_PATTERN = re.compile(r"제\s*(\d+)\s*항")
ITEM_PATTERN = re.compile(r"제\s*(\d+)\s*호")
SUBITEM_PATTERN = re.compile(r"([가나다라마바사아자차카타파하])\s*목")


def detect_query_type(query: str) -> str:
    """
    쿼리 타입 감지
    
    Returns:
        "exact": 조문 번호가 포함된 정확조회
        "semantic": 의미 기반 검색
        "hybrid": 둘 다 포함
    """
    has_article = bool(ARTICLE_PATTERN.search(query) or ARTICLE_WITH_BRANCH.search(query))
    has_paragraph = bool(PARAGRAPH_PATTERN.search(query))
    has_item = bool(ITEM_PATTERN.search(query))
    has_subitem = bool(SUBITEM_PATTERN.search(query))
    
    has_exact_pattern = has_article or has_paragraph or has_item or has_subitem
    
    if has_exact_pattern and len(query.strip()) < 50:
        # 조문 번호만 있거나 짧은 쿼리면 정확조회
        return "exact"
    elif has_exact_pattern:
        # 조문 번호 + 의미 검색
        return "hybrid"
    else:
        # 의미 기반 검색
        return "semantic"


def search_exact(
    query: str,
    law_id: Optional[str] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    RDB 정확조회
    
    Args:
        query: 검색 쿼리 (조문 번호 포함)
        law_id: 특정 법령만 검색 (None이면 전체)
        limit: 결과 개수 제한
    
    Returns:
        검색 결과 노드 리스트
    """
    conninfo = conninfo_from_env()
    
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            conditions = []
            params = []
            
            # 조문 번호 추출
            article_match = ARTICLE_PATTERN.search(query)
            if article_match:
                article_no = article_match.group(1)
                conditions.append("article_no LIKE %s")
                params.append(f"제{article_no}조%")
            
            article_branch_match = ARTICLE_WITH_BRANCH.search(query)
            if article_branch_match:
                article_no = article_branch_match.group(1)
                branch_no = article_branch_match.group(2)
                conditions.append("article_no LIKE %s")
                params.append(f"제{article_no}조의{branch_no}%")
            
            # 항 번호 추출
            para_match = PARAGRAPH_PATTERN.search(query)
            if para_match:
                para_no = para_match.group(1)
                conditions.append("paragraph_no = %s")
                params.append(para_no)
            
            # 호 번호 추출
            item_match = ITEM_PATTERN.search(query)
            if item_match:
                item_no = item_match.group(1)
                conditions.append("item_no = %s")
                params.append(item_no)
            
            # 목 번호 추출
            subitem_match = SUBITEM_PATTERN.search(query)
            if subitem_match:
                subitem_no = subitem_match.group(1)
                conditions.append("subitem_no = %s")
                params.append(subitem_no)
            
            # 법령 필터
            if law_id:
                conditions.append("law_id = %s")
                params.append(law_id)
            
            # 쿼리 실행
            if conditions:
                where_clause = " AND ".join(conditions)
                sql = f"""
                    SELECT doc_id, law_id, level, article_no, article_title,
                           paragraph_no, item_no, subitem_no,
                           path, text
                    FROM law_units
                    WHERE {where_clause}
                    ORDER BY article_no, paragraph_no, item_no, subitem_no
                    LIMIT %s
                """
                params.append(limit)
                cur.execute(sql, params)
            else:
                # 패턴이 없으면 텍스트 검색
                sql = """
                    SELECT doc_id, law_id, level, article_no, article_title,
                           paragraph_no, item_no, subitem_no,
                           path, text
                    FROM law_units
                    WHERE text LIKE %s
                    ORDER BY article_no, paragraph_no, item_no, subitem_no
                    LIMIT %s
                """
                cur.execute(sql, [f"%{query}%", limit])
            
            columns = [desc[0] for desc in cur.description]
            results = []
            for row in cur:
                result = dict(zip(columns, row))
                results.append(result)
            
            return results


def search_semantic(
    query: str,
    law_id: Optional[str] = None,
    limit: int = 10,
    embedding_model: str = "text-embedding-3-large",
    threshold: float = 0.7
) -> List[Dict[str, Any]]:
    """
    Vector 유사도 검색
    
    Args:
        query: 검색 쿼리
        law_id: 특정 법령만 검색 (None이면 전체)
        limit: 결과 개수 제한
        embedding_model: 임베딩 모델명
        threshold: 유사도 임계값 (0.0 ~ 1.0)
    
    Returns:
        검색 결과 노드 리스트 (유사도 점수 포함)
    """
    # TODO: 실제 임베딩 API 호출 필요
    # query_embedding = embed_text(query, model=embedding_model)
    
    raise NotImplementedError(
        "search_semantic()에 실제 임베딩 API를 연결하세요.\n"
        "예: OpenAI API, HuggingFace 등"
    )
    
    # 아래는 구현 예시 (실제 임베딩이 있을 때 사용)
    """
    conninfo = conninfo_from_env()
    
    with psycopg.connect(conninfo) as conn:
        register_vector(conn)
        
        with conn.cursor() as cur:
            # Vector 유사도 검색
            if law_id:
                sql = """
                    SELECT 
                        lu.doc_id, lu.law_id, lu.level, lu.article_no, lu.article_title,
                        lu.paragraph_no, lu.item_no, lu.subitem_no,
                        lu.path, lu.text,
                        1 - (scv.embedding <=> %s::vector) AS similarity
                    FROM statute_chunk_vectors scv
                    JOIN law_units lu ON scv.unit_id = lu.doc_id
                    WHERE scv.law_id = %s 
                      AND scv.embedding_model = %s
                      AND 1 - (scv.embedding <=> %s::vector) >= %s
                    ORDER BY scv.embedding <=> %s::vector
                    LIMIT %s
                """
                cur.execute(sql, [
                    Vector(query_embedding), law_id, embedding_model,
                    Vector(query_embedding), threshold,
                    Vector(query_embedding), limit
                ])
            else:
                sql = """
                    SELECT 
                        lu.doc_id, lu.law_id, lu.level, lu.article_no, lu.article_title,
                        lu.paragraph_no, lu.item_no, lu.subitem_no,
                        lu.path, lu.text,
                        1 - (scv.embedding <=> %s::vector) AS similarity
                    FROM statute_chunk_vectors scv
                    JOIN law_units lu ON scv.unit_id = lu.doc_id
                    WHERE scv.embedding_model = %s
                      AND 1 - (scv.embedding <=> %s::vector) >= %s
                    ORDER BY scv.embedding <=> %s::vector
                    LIMIT %s
                """
                cur.execute(sql, [
                    Vector(query_embedding), embedding_model,
                    Vector(query_embedding), threshold,
                    Vector(query_embedding), limit
                ])
            
            columns = [desc[0] for desc in cur.description]
            results = []
            for row in cur:
                result = dict(zip(columns, row))
                results.append(result)
            
            return results
    """


def search_hybrid(
    query: str,
    law_id: Optional[str] = None,
    limit: int = 10,
    embedding_model: str = "text-embedding-3-large"
) -> List[Dict[str, Any]]:
    """
    하이브리드 검색: 정확조회 + 의미 검색 결과 통합
    
    Args:
        query: 검색 쿼리
        law_id: 특정 법령만 검색
        limit: 결과 개수 제한
        embedding_model: 임베딩 모델명
    
    Returns:
        검색 결과 노드 리스트
    """
    # 정확조회
    exact_results = search_exact(query, law_id=law_id, limit=limit)
    
    # 의미 검색 (구현 필요)
    try:
        semantic_results = search_semantic(query, law_id=law_id, limit=limit, embedding_model=embedding_model)
    except NotImplementedError:
        semantic_results = []
    
    # 결과 통합 (중복 제거)
    seen_ids = set()
    combined_results = []
    
    # 정확조회 결과 우선
    for result in exact_results:
        doc_id = result["doc_id"]
        if doc_id not in seen_ids:
            seen_ids.add(doc_id)
            combined_results.append(result)
    
    # 의미 검색 결과 추가
    for result in semantic_results:
        doc_id = result["doc_id"]
        if doc_id not in seen_ids:
            seen_ids.add(doc_id)
            combined_results.append(result)
    
    return combined_results[:limit]


def search(
    query: str,
    law_id: Optional[str] = None,
    limit: int = 10,
    embedding_model: str = "text-embedding-3-large"
) -> List[Dict[str, Any]]:
    """
    통합 검색 함수: 쿼리 타입에 따라 자동 라우팅
    
    Args:
        query: 검색 쿼리
        law_id: 특정 법령만 검색
        limit: 결과 개수 제한
        embedding_model: 임베딩 모델명
    
    Returns:
        검색 결과 노드 리스트
    """
    query_type = detect_query_type(query)
    
    if query_type == "exact":
        return search_exact(query, law_id=law_id, limit=limit)
    elif query_type == "semantic":
        try:
            return search_semantic(query, law_id=law_id, limit=limit, embedding_model=embedding_model)
        except NotImplementedError:
            # 임베딩이 없으면 텍스트 검색으로 폴백
            return search_exact(query, law_id=law_id, limit=limit)
    else:  # hybrid
        return search_hybrid(query, law_id=law_id, limit=limit, embedding_model=embedding_model)


def search_hierarchical(
    query: str,
    law_id: Optional[str] = None,
    limit: int = 10,
    embedding_model: str = "text-embedding-3-large",
    threshold: float = 0.7
) -> Dict[str, Any]:
    """
    계층적 검색: Stage 1 (장/절/조 키워드 검색) → Stage 2 (항/호/목 Vector 검색)
    
    Args:
        query: 검색 쿼리
        law_id: 특정 법령만 검색
        limit: 최종 결과 개수 제한
        embedding_model: 임베딩 모델명
        threshold: Vector 검색 유사도 임계값
    
    Returns:
        검색 결과 딕셔너리 (stage1_results, stage2_results 포함)
    """
    conninfo = conninfo_from_env()
    
    # Stage 1: 장/절/조 키워드 검색
    stage1_results = []
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            conditions = ["level = 'article'"]
            params = []
            
            # 키워드 검색 조건
            keyword_conditions = [
                "article_title LIKE %s",
                "text LIKE %s",
                "section_path::text LIKE %s"
            ]
            keyword_pattern = f"%{query}%"
            params.extend([keyword_pattern] * 3)
            
            conditions.append(f"({' OR '.join(keyword_conditions)})")
            
            # 법령 필터
            if law_id:
                conditions.append("law_id = %s")
                params.append(law_id)
            
            where_clause = " AND ".join(conditions)
            sql = f"""
                SELECT doc_id, law_id, article_no, article_title, section_path,
                       chapter_no, chapter_name, section_no, section_name, path
                FROM law_units
                WHERE {where_clause}
                ORDER BY article_no
                LIMIT %s
            """
            params.append(limit * 2)  # Stage 2를 위해 더 많이 가져옴
            
            cur.execute(sql, params)
            columns = [desc[0] for desc in cur.description]
            for row in cur:
                result = dict(zip(columns, row))
                # JSONB 필드 처리
                if result.get("section_path"):
                    if isinstance(result["section_path"], str):
                        result["section_path"] = json.loads(result["section_path"])
                else:
                    result["section_path"] = []
                stage1_results.append(result)
    
    if not stage1_results:
        return {
            "stage": "hierarchical",
            "stage1": {"count": 0, "results": []},
            "stage2": {"count": 0, "results": []},
            "message": "Stage 1 검색 결과가 없습니다."
        }
    
    # Stage 2: 항/호/목 Vector 검색 (Stage 1 결과의 하위 노드만)
    stage2_results = []
    article_ids = [r["doc_id"] for r in stage1_results]
    
    # TODO: 실제 임베딩 API 호출 필요
    # query_embedding = embed_text(query, model=embedding_model)
    
    # 임시: 텍스트 검색으로 폴백
    with psycopg.connect(conninfo) as conn:
        register_vector(conn)
        
        with conn.cursor() as cur:
            placeholders = ','.join(['%s'] * len(article_ids))
            
            sql = f"""
                SELECT 
                    lu.doc_id, lu.law_id, lu.level, lu.article_no, lu.article_title,
                    lu.paragraph_no, lu.item_no, lu.subitem_no,
                    lu.path, lu.text
                FROM law_units lu
                WHERE lu.level IN ('paragraph', 'item', 'subitem')
                  AND lu.parent_id IN ({placeholders})
                  AND lu.search_stage = 'stage2'
                  AND lu.text LIKE %s
                ORDER BY lu.article_no, lu.paragraph_no, lu.item_no, lu.subitem_no
                LIMIT %s
            """
            
            params = article_ids + [f"%{query}%", limit]
            cur.execute(sql, params)
            
            columns = [desc[0] for desc in cur.description]
            for row in cur:
                result = dict(zip(columns, row))
                stage2_results.append(result)
    
    return {
        "stage": "hierarchical",
        "stage1": {
            "count": len(stage1_results),
            "results": stage1_results[:5]  # 상위 5개만 표시
        },
        "stage2": {
            "count": len(stage2_results),
            "results": stage2_results
        }
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python query_router.py <query> [law_id] [--hierarchical]")
        sys.exit(1)
    
    query = sys.argv[1]
    law_id = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None
    use_hierarchical = "--hierarchical" in sys.argv or "-h" in sys.argv
    
    print(f"검색 쿼리: {query}")
    
    if use_hierarchical:
        print("검색 방식: 계층적 검색")
        results = search_hierarchical(query, law_id=law_id, limit=5)
        print(f"\nStage 1 결과: {results['stage1']['count']}개")
        for i, result in enumerate(results['stage1']['results'], 1):
            print(f"  [{i}] {result.get('path', 'N/A')}")
        print(f"\nStage 2 결과: {results['stage2']['count']}개")
        for i, result in enumerate(results['stage2']['results'], 1):
            print(f"  [{i}] {result.get('path', 'N/A')}")
            print(f"      text: {result.get('text', '')[:100]}...")
    else:
        print(f"쿼리 타입: {detect_query_type(query)}")
        print()
        
        results = search(query, law_id=law_id, limit=5)
        
        print(f"검색 결과: {len(results)}개")
        for i, result in enumerate(results, 1):
            print(f"\n[{i}] {result.get('path', 'N/A')}")
            print(f"    level: {result.get('level')}")
            print(f"    text: {result.get('text', '')[:100]}...")
