"""
통합 벡터 검색 API (FastAPI)

기능:
- 하이브리드 검색 (BM25 + 벡터 + RRF)
- 순수 벡터 검색
- 순수 BM25 검색
- 필터링 검색 (데이터셋, 카테고리, 문서유형, 연도)
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
import json

# .env 파일 로드
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# FastAPI 앱 생성
app = FastAPI(
    title="DDoksori Vector Search API",
    description="소비자 분쟁 사례 및 법령 하이브리드 검색 API",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenAI 클라이언트
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# PostgreSQL 연결 정보
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost").strip(),
    "port": int(os.getenv("DB_PORT", "5432").strip()),
    "database": os.getenv("DB_NAME", "ddoksori").strip(),
    "user": os.getenv("DB_USER", "postgres").strip(),
    "password": os.getenv("DB_PASSWORD", "postgres").strip()
}

# ========================================
# Pydantic 모델
# ========================================

class SearchRequest(BaseModel):
    """검색 요청"""
    query: str = Field(..., description="검색 쿼리", min_length=1)
    dataset_filter: Optional[Literal["law_guide", "case"]] = Field(None, description="데이터셋 필터")
    category_filter: Optional[str] = Field(None, description="카테고리 필터 (상담/해결/조정)")
    document_type_filter: Optional[Literal["법률", "시행령", "행정규칙", "별표"]] = Field(None, description="문서 유형 필터 (law_guide 전용)")
    year_filter: Optional[int] = Field(None, description="연도 필터")
    top_k: int = Field(10, description="반환할 결과 수", ge=1, le=100)
    search_type: Literal["hybrid", "vector", "bm25"] = Field("hybrid", description="검색 타입")


class SearchResult(BaseModel):
    """검색 결과 단일 항목"""
    chunk_id: str
    dataset_type: str
    text: str
    score: float
    category: Optional[str] = None
    law_name: Optional[str] = None
    source_url: Optional[str] = None
    source_file: Optional[str] = None
    printed_page: Optional[int] = None
    source_year: Optional[int] = None
    metadata: Optional[dict] = None


class SearchResponse(BaseModel):
    """검색 응답"""
    query: str
    total_results: int
    search_type: str
    results: List[SearchResult]
    search_time_ms: Optional[float] = None


class HealthResponse(BaseModel):
    """헬스 체크 응답"""
    status: str
    database: str
    total_chunks: int


# ========================================
# 데이터베이스 연결
# ========================================

def get_db_connection():
    """PostgreSQL 연결 생성 (재시도 로직 포함)"""
    import time
    max_retries = 3
    retry_delay = 1  # seconds

    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(
                **DB_CONFIG,
                cursor_factory=RealDictCursor,
                connect_timeout=10  # RDS 연결 타임아웃
            )
            return conn
        except psycopg2.OperationalError as e:
            if attempt < max_retries - 1:
                print(f"[WARNING] DB connection failed (attempt {attempt + 1}/{max_retries}), retrying...")
                time.sleep(retry_delay)
            else:
                raise HTTPException(
                    status_code=503,
                    detail=f"Database connection failed after {max_retries} attempts: {str(e)}"
                )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Unexpected database error: {str(e)}"
            )


# ========================================
# 임베딩 생성
# ========================================

def create_query_embedding(query: str) -> List[float]:
    """쿼리 텍스트를 임베딩으로 변환"""
    try:
        response = openai_client.embeddings.create(
            model="text-embedding-3-large",
            input=query,
            dimensions=1536
        )
        return response.data[0].embedding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding generation failed: {str(e)}")


# ========================================
# Re-ranking 함수
# ========================================

def rerank_case_chunks(results: List[dict], score_field: str) -> List[dict]:
    """
    case 데이터의 청크를 케이스별로 그룹화하여 re-ranking

    동일한 사례가 여러 청크로 분할된 경우:
    1. 케이스별로 청크를 그룹화 (source_url 또는 original_number 기준)
    2. 각 그룹에서 가장 높은 점수의 청크를 대표로 선택
    3. 같은 그룹의 다른 청크들을 텍스트 병합하여 완전한 문맥 제공

    그룹화 기준 우선순위:
    - source_url (웹 크롤링 데이터)
    - original_number (PDF 파싱 데이터)
    - chunk_id (fallback)

    Args:
        results: 검색 결과 리스트
        score_field: 점수 필드명 ('rrf_score', 'similarity', 'rank')

    Returns:
        Re-ranking된 결과 리스트
    """
    # case가 아닌 데이터는 그대로 유지
    law_guide_results = [r for r in results if r.get('dataset_type') != 'case']
    case_results = [r for r in results if r.get('dataset_type') == 'case']

    if not case_results:
        return results

    # 케이스별로 그룹화 (source_url 또는 original_number)
    from collections import defaultdict
    url_groups = defaultdict(list)

    for result in case_results:
        source_url = result.get('source_url')
        original_number = result.get('original_number')

        # 그룹 키 결정 우선순위:
        # 1. source_url (웹 크롤링 데이터)
        # 2. original_number (PDF 파싱 데이터)
        # 3. chunk_id (fallback)
        if source_url:
            group_key = source_url
        elif original_number:
            group_key = f"case_{original_number}"  # prefix로 구분
        else:
            group_key = result['chunk_id']

        url_groups[group_key].append(result)

    # 각 그룹에서 최고 점수 청크 선택 및 컨텍스트 병합
    reranked_cases = []
    for url, chunks in url_groups.items():
        # 점수 기준으로 정렬 (내림차순)
        sorted_chunks = sorted(chunks, key=lambda x: float(x.get(score_field, 0)), reverse=True)
        best_chunk = sorted_chunks[0]

        # 여러 청크가 있는 경우 컨텍스트 병합
        if len(sorted_chunks) > 1:
            # 모든 청크의 텍스트를 결합
            combined_text_parts = []
            for i, chunk in enumerate(sorted_chunks, 1):
                chunk_text = chunk.get('text', '')
                combined_text_parts.append(f"[청크 {i}/{len(sorted_chunks)}]\n{chunk_text}")

            # 병합된 텍스트로 업데이트
            best_chunk = dict(best_chunk)  # 복사본 생성
            best_chunk['text'] = "\n\n---\n\n".join(combined_text_parts)

            # metadata에 청크 수 정보 추가
            if best_chunk.get('metadata'):
                best_chunk['metadata'] = dict(best_chunk['metadata'])
            else:
                best_chunk['metadata'] = {}
            best_chunk['metadata']['merged_chunks_count'] = len(sorted_chunks)
            best_chunk['metadata']['chunk_ids'] = [c['chunk_id'] for c in sorted_chunks]

        reranked_cases.append(best_chunk)

    # case와 law_guide 결과 병합 후 점수 기준으로 재정렬
    all_results = law_guide_results + reranked_cases
    all_results.sort(key=lambda x: float(x.get(score_field, 0)), reverse=True)

    return all_results


# ========================================
# 검색 함수
# ========================================

def search_hybrid_rrf(
    conn,
    query_text: str,
    query_embedding: List[float],
    dataset_filter: Optional[str],
    category_filter: Optional[str],
    document_type_filter: Optional[str],
    year_filter: Optional[int],
    top_k: int
) -> List[dict]:
    """하이브리드 검색 (BM25 + 벡터 + RRF)"""
    cursor = conn.cursor()

    # PostgreSQL 함수 호출
    cursor.execute("""
        SELECT * FROM search_hybrid_rrf(
            %s::text,                  -- query_text
            %s::vector(1536),          -- query_embedding
            %s::varchar(20),           -- filter_dataset
            %s::varchar(50),           -- filter_category
            %s::varchar(20),           -- filter_document_type
            %s::integer,               -- filter_year
            %s::integer,               -- result_limit
            60                         -- rrf_k (고정값)
        )
    """, (query_text, query_embedding, dataset_filter, category_filter, document_type_filter, year_filter, top_k))

    results = cursor.fetchall()
    cursor.close()
    return results


def search_vector_only(
    conn,
    query_embedding: List[float],
    dataset_filter: Optional[str],
    category_filter: Optional[str],
    document_type_filter: Optional[str],
    year_filter: Optional[int],
    top_k: int
) -> List[dict]:
    """순수 벡터 검색"""
    cursor = conn.cursor()

    # 필터 조건 구성
    where_clauses = []
    params = [query_embedding]

    if dataset_filter:
        where_clauses.append("dataset_type = %s")
        params.append(dataset_filter)

    if category_filter:
        where_clauses.append("category = %s")
        params.append(category_filter)

    if document_type_filter:
        where_clauses.append("document_type = %s")
        params.append(document_type_filter)

    if year_filter:
        where_clauses.append("source_year = %s")
        params.append(year_filter)

    where_clause = " AND ".join(where_clauses) if where_clauses else "TRUE"

    # params 재구성: embedding을 두 번 사용하므로
    final_params = [query_embedding, query_embedding] + params[1:] + [top_k]

    query = f"""
        SELECT
            chunk_id,
            dataset_type,
            text,
            1 - (embedding <=> %s::vector(1536)) AS similarity,
            category,
            law_name,
            source_url,
            source_file,
            printed_page,
            source_year,
            metadata
        FROM vector_chunks
        WHERE {where_clause}
        ORDER BY embedding <=> %s::vector(1536)
        LIMIT %s
    """

    cursor.execute(query, final_params)
    results = cursor.fetchall()
    cursor.close()
    return results


def search_bm25_only(
    conn,
    query_text: str,
    dataset_filter: Optional[str],
    category_filter: Optional[str],
    document_type_filter: Optional[str],
    top_k: int
) -> List[dict]:
    """순수 BM25 검색"""
    cursor = conn.cursor()

    # PostgreSQL 함수 호출
    cursor.execute("""
        SELECT * FROM search_bm25(
            %s::text,           -- query_text
            %s::varchar(20),    -- filter_dataset
            %s::varchar(50),    -- filter_category
            %s::varchar(20),    -- filter_document_type
            %s::integer         -- result_limit
        )
    """, (query_text, dataset_filter, category_filter, document_type_filter, top_k))

    results = cursor.fetchall()
    cursor.close()
    return results


# ========================================
# Startup/Shutdown 이벤트
# ========================================

@app.on_event("startup")
async def startup_event():
    """서버 시작 시 DB 연결 테스트"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM vector_chunks")
        result = cursor.fetchone()
        total_chunks = result['count']
        cursor.close()
        conn.close()
        print(f"[OK] Database connected successfully ({total_chunks:,} chunks loaded)")
    except Exception as e:
        print(f"[ERROR] Database connection failed on startup: {e}")
        print("[WARNING] API will start but may not function correctly")


# ========================================
# API 엔드포인트
# ========================================

@app.get("/", tags=["Root"])
async def root():
    """API 루트"""
    return {
        "message": "DDoksori Vector Search API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "search": "/search",
            "stats": "/stats"
        }
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """헬스 체크"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 총 청크 수 확인
        cursor.execute("SELECT COUNT(*) as count FROM vector_chunks")
        result = cursor.fetchone()
        total_chunks = result['count']

        cursor.close()
        conn.close()

        return {
            "status": "healthy",
            "database": "connected",
            "total_chunks": total_chunks
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")


@app.get("/stats", tags=["Statistics"])
async def get_statistics():
    """데이터베이스 통계"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 데이터셋별 통계
        cursor.execute("""
            SELECT
                dataset_type,
                category,
                document_type,
                chunk_type,
                COUNT(*) as total_chunks,
                AVG(LENGTH(text)) as avg_text_length
            FROM vector_chunks
            GROUP BY dataset_type, category, document_type, chunk_type
            ORDER BY dataset_type, category, document_type, chunk_type
        """)

        stats = cursor.fetchall()

        # 문서 유형별 통계 (law_guide 전용)
        cursor.execute("""
            SELECT
                document_type,
                COUNT(*) as total_chunks
            FROM vector_chunks
            WHERE dataset_type = 'law_guide'
            GROUP BY document_type
            ORDER BY document_type
        """)

        document_type_stats = cursor.fetchall()

        cursor.close()
        conn.close()

        return {
            "statistics": stats,
            "document_type_statistics": document_type_stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch statistics: {str(e)}")


@app.post("/search", response_model=SearchResponse, tags=["Search"])
async def search(request: SearchRequest):
    """
    통합 검색 엔드포인트

    - **hybrid**: BM25 + 벡터 + RRF 통합 검색 (권장)
    - **vector**: 순수 벡터 유사도 검색
    - **bm25**: 순수 키워드 검색
    """
    import time
    start_time = time.time()

    try:
        conn = get_db_connection()

        # 쿼리 임베딩 생성 (벡터 검색 필요한 경우만)
        query_embedding = None
        if request.search_type in ["hybrid", "vector"]:
            query_embedding = create_query_embedding(request.query)

        # 검색 수행
        if request.search_type == "hybrid":
            results = search_hybrid_rrf(
                conn,
                request.query,
                query_embedding,
                request.dataset_filter,
                request.category_filter,
                request.document_type_filter,
                request.year_filter,
                request.top_k
            )
            score_field = "rrf_score"
        elif request.search_type == "vector":
            results = search_vector_only(
                conn,
                query_embedding,
                request.dataset_filter,
                request.category_filter,
                request.document_type_filter,
                request.year_filter,
                request.top_k
            )
            score_field = "similarity"
        else:  # bm25
            results = search_bm25_only(
                conn,
                request.query,
                request.dataset_filter,
                request.category_filter,
                request.document_type_filter,
                request.top_k
            )
            score_field = "rank"

        conn.close()

        # Re-ranking: case 청크 그룹화
        results = rerank_case_chunks(results, score_field)

        # 검색 시간 계산
        search_time_ms = (time.time() - start_time) * 1000

        # 결과 포맷팅
        formatted_results = []
        for row in results:
            formatted_results.append(SearchResult(
                chunk_id=row['chunk_id'],
                dataset_type=row['dataset_type'],
                text=row['text'],
                score=float(row.get(score_field, 0)),
                category=row.get('category'),
                law_name=row.get('law_name'),
                source_url=row.get('source_url'),
                source_file=row.get('source_file'),
                printed_page=row.get('printed_page'),
                source_year=row.get('source_year'),
                metadata=row.get('metadata')
            ))

        return SearchResponse(
            query=request.query,
            total_results=len(formatted_results),
            search_type=request.search_type,
            results=formatted_results,
            search_time_ms=round(search_time_ms, 2)
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


# ========================================
# 서버 실행
# ========================================

if __name__ == "__main__":
    import uvicorn

    print("=" * 80)
    print("DDoksori Vector Search API")
    print("=" * 80)
    print(f"Database: {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    print(f"Starting server at http://localhost:8000")
    print(f"API Docs: http://localhost:8000/docs")
    print("=" * 80)

    uvicorn.run(
        "03_01_search_api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
