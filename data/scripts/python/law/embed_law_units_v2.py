"""
법령 데이터 Vector 인덱싱 v2

법령별 청킹 전략에 따라 임베딩을 생성하고 statute_chunk_vectors 테이블에 저장합니다.
"""
import os
import json
from typing import Any, Dict, Iterable, List, Optional
from dotenv import load_dotenv

load_dotenv()

import psycopg
from pgvector.psycopg import register_vector
from pgvector import Vector

try:
    from law_chunking_strategy import get_strategy_instance
except ImportError:
    # 상대 경로 import 시도
    import sys
    from pathlib import Path
    script_dir = Path(__file__).parent
    sys.path.insert(0, str(script_dir))
    from law_chunking_strategy import get_strategy_instance


def conninfo_from_env() -> str:
    return (
        f"host={os.environ.get('PGHOST','localhost')} "
        f"port={os.environ.get('PGPORT','5433')} "
        f"dbname={os.environ.get('PGDATABASE','postgres')} "
        f"user={os.environ.get('PGUSER','postgres')} "
        f"password={os.environ.get('PGPASSWORD','postgres')}"
    )


DDL_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS statute_chunk_vectors (
  unit_id         TEXT NOT NULL,
  embedding_model TEXT NOT NULL,
  law_id          TEXT NOT NULL,
  unit_level      TEXT,
  path            TEXT,
  node_refs       JSONB NOT NULL DEFAULT '[]'::jsonb,
  index_text      TEXT,
  embedding       VECTOR(1024) NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (unit_id, embedding_model)
);

CREATE INDEX IF NOT EXISTS idx_statute_chunk_vectors_law_id
  ON statute_chunk_vectors(law_id);

CREATE INDEX IF NOT EXISTS idx_statute_chunk_vectors_unit_level
  ON statute_chunk_vectors(unit_level);

CREATE INDEX IF NOT EXISTS idx_statute_chunk_vectors_embedding_model
  ON statute_chunk_vectors(embedding_model);

CREATE INDEX IF NOT EXISTS idx_statute_chunk_vectors_embedding_hnsw
  ON statute_chunk_vectors
  USING hnsw (embedding vector_cosine_ops);
"""


UPSERT_SQL = """
INSERT INTO statute_chunk_vectors (
  unit_id, embedding_model, law_id, unit_level, path,
  node_refs, index_text, embedding
) VALUES (
  %(unit_id)s, %(embedding_model)s, %(law_id)s, %(unit_level)s, %(path)s,
  %(node_refs)s::jsonb, %(index_text)s, %(embedding)s
)
ON CONFLICT (unit_id, embedding_model) DO UPDATE SET
  law_id=EXCLUDED.law_id,
  unit_level=EXCLUDED.unit_level,
  path=EXCLUDED.path,
  node_refs=EXCLUDED.node_refs,
  index_text=EXCLUDED.index_text,
  embedding=EXCLUDED.embedding;
"""


def embed_texts(texts: List[str], model: str = "text-embedding-3-large") -> List[List[float]]:
    """
    텍스트 리스트를 임베딩 벡터로 변환
    
    TODO: 실제 임베딩 API 호출을 여기에 구현하세요.
    예: OpenAI API, HuggingFace 모델, 또는 로컬 모델
    
    Args:
        texts: 임베딩할 텍스트 리스트
        model: 임베딩 모델명
    
    Returns:
        1024차원 벡터 리스트
    """
    # 실제 구현 필요: OpenAI API, HuggingFace 등
    raise NotImplementedError(
        "embed_texts()에 실제 임베딩 호출을 연결하세요.\n"
        "예: OpenAI API, HuggingFace transformers, sentence-transformers 등"
    )


def build_index_text(node: Dict[str, Any]) -> str:
    """
    노드에서 임베딩용 index_text 생성
    
    조문 번호, 본문을 조합하여 의미 있는 텍스트 생성
    """
    parts = []
    
    # 조문 번호 및 제목
    article_no = node.get("article_no")
    article_title = node.get("article_title")
    if article_no:
        article_str = article_no
        if article_title:
            article_str += f"({article_title})"
        parts.append(article_str)
    
    # 항/호/목 번호
    paragraph_no = node.get("paragraph_no")
    item_no = node.get("item_no")
    subitem_no = node.get("subitem_no")
    
    if paragraph_no:
        parts.append(f"제{paragraph_no}항")
    if item_no:
        parts.append(f"제{item_no}호")
    if subitem_no:
        parts.append(f"{subitem_no}목")
    
    # 본문
    text = node.get("text", "").strip()
    if text:
        parts.append(text)
    
    return " ".join(parts)


def load_units_from_db(
    law_id: Optional[str] = None,
    is_indexable: bool = True,
    search_stage: Optional[str] = "stage2"
) -> Iterable[Dict[str, Any]]:
    """
    law_units 테이블에서 인덱싱 가능한 노드 조회
    
    Args:
        law_id: 특정 법령만 조회 (None이면 전체)
        is_indexable: is_indexable=True인 노드만 조회
        search_stage: 'stage2'인 노드만 조회 (계층적 검색용)
    """
    conninfo = conninfo_from_env()
    
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            if law_id:
                if search_stage:
                    cur.execute(
                        """
                        SELECT doc_id, law_id, level, article_no, article_title,
                               paragraph_no, item_no, subitem_no,
                               path, text,
                               ref_citations_internal, ref_citations_external
                        FROM law_units
                        WHERE law_id = %s AND is_indexable = %s AND search_stage = %s
                        ORDER BY article_no, paragraph_no, item_no, subitem_no
                        """,
                        (law_id, is_indexable, search_stage)
                    )
                else:
                    cur.execute(
                        """
                        SELECT doc_id, law_id, level, article_no, article_title,
                               paragraph_no, item_no, subitem_no,
                               path, text,
                               ref_citations_internal, ref_citations_external
                        FROM law_units
                        WHERE law_id = %s AND is_indexable = %s
                        ORDER BY article_no, paragraph_no, item_no, subitem_no
                        """,
                        (law_id, is_indexable)
                    )
            else:
                if search_stage:
                    cur.execute(
                        """
                        SELECT doc_id, law_id, level, article_no, article_title,
                               paragraph_no, item_no, subitem_no,
                               path, text,
                               ref_citations_internal, ref_citations_external
                        FROM law_units
                        WHERE is_indexable = %s AND search_stage = %s
                        ORDER BY law_id, article_no, paragraph_no, item_no, subitem_no
                        """,
                        (is_indexable, search_stage)
                    )
                else:
                    cur.execute(
                        """
                        SELECT doc_id, law_id, level, article_no, article_title,
                               paragraph_no, item_no, subitem_no,
                               path, text,
                               ref_citations_internal, ref_citations_external
                        FROM law_units
                        WHERE is_indexable = %s
                        ORDER BY law_id, article_no, paragraph_no, item_no, subitem_no
                        """,
                        (is_indexable,)
                    )
            
            columns = [desc[0] for desc in cur.description]
            for row in cur:
                node = dict(zip(columns, row))
                # JSONB 필드 처리
                if node.get("ref_citations_internal"):
                    node["ref_citations_internal"] = json.loads(node["ref_citations_internal"])
                else:
                    node["ref_citations_internal"] = []
                
                if node.get("ref_citations_external"):
                    node["ref_citations_external"] = json.loads(node["ref_citations_external"])
                else:
                    node["ref_citations_external"] = []
                
                yield node


def create_embeddings_and_save(
    law_id: Optional[str] = None,
    *,
    embedding_model: str = "text-embedding-3-large",
    batch_size: int = 512
) -> int:
    """
    law_units에서 인덱싱 가능한 노드를 조회하여 임베딩 생성 및 저장
    
    Args:
        law_id: 특정 법령만 처리 (None이면 전체)
        embedding_model: 임베딩 모델명
        batch_size: 배치 크기
    
    Returns:
        저장된 벡터 수
    """
    conninfo = conninfo_from_env()
    
    with psycopg.connect(conninfo) as conn:
        register_vector(conn)
        
        with conn.cursor() as cur:
            # 스키마 생성
            cur.execute(DDL_SQL)
            conn.commit()
            
            buffer_nodes: List[Dict[str, Any]] = []
            buffer_texts: List[str] = []
            saved_count = 0
            
            print(f"노드 조회 중 (law_id={law_id}, search_stage=stage2)...")
            for node in load_units_from_db(law_id=law_id, is_indexable=True, search_stage="stage2"):
                # index_text 생성
                index_text = build_index_text(node)
                if not index_text or not index_text.strip():
                    continue
                
                buffer_nodes.append(node)
                buffer_texts.append(index_text)
                
                if len(buffer_texts) >= batch_size:
                    # 임베딩 생성
                    print(f"  임베딩 생성 중: {len(buffer_texts)}개 텍스트...")
                    try:
                        vectors = embed_texts(buffer_texts, model=embedding_model)
                    except NotImplementedError:
                        print("오류: embed_texts()가 구현되지 않았습니다.")
                        print("      실제 임베딩 API를 연결하거나, JSONL 파일에서 embedding 필드를 읽어야 합니다.")
                        return 0
                    
                    # DB 저장
                    rows = []
                    for node, vec in zip(buffer_nodes, vectors):
                        if len(vec) != 1024:
                            print(f"경고: 벡터 차원 불일치 (예상: 1024, 실제: {len(vec)})")
                            continue
                        
                        row = {
                            "unit_id": node["doc_id"],
                            "embedding_model": embedding_model,
                            "law_id": node["law_id"],
                            "unit_level": node["level"],
                            "path": node["path"],
                            "node_refs": json.dumps([
                                *node.get("ref_citations_internal", []),
                                *node.get("ref_citations_external", [])
                            ], ensure_ascii=False),
                            "index_text": build_index_text(node),
                            "embedding": Vector(vec),
                        }
                        rows.append(row)
                    
                    cur.executemany(UPSERT_SQL, rows)
                    saved_count += len(rows)
                    print(f"  저장 완료: {saved_count}개 벡터")
                    
                    buffer_nodes.clear()
                    buffer_texts.clear()
            
            # 남은 버퍼 처리
            if buffer_texts:
                print(f"  임베딩 생성 중: {len(buffer_texts)}개 텍스트...")
                try:
                    vectors = embed_texts(buffer_texts, model=embedding_model)
                except NotImplementedError:
                    print("오류: embed_texts()가 구현되지 않았습니다.")
                    return saved_count
                
                rows = []
                for node, vec in zip(buffer_nodes, vectors):
                    if len(vec) != 1024:
                        continue
                    
                    row = {
                        "unit_id": node["doc_id"],
                        "embedding_model": embedding_model,
                        "law_id": node["law_id"],
                        "unit_level": node["level"],
                        "path": node["path"],
                        "node_refs": json.dumps([
                            *node.get("ref_citations_internal", []),
                            *node.get("ref_citations_external", [])
                        ], ensure_ascii=False),
                        "index_text": build_index_text(node),
                        "embedding": Vector(vec),
                    }
                    rows.append(row)
                
                cur.executemany(UPSERT_SQL, rows)
                saved_count += len(rows)
            
            conn.commit()
            print(f"완료: 총 {saved_count}개 벡터 저장")
            return saved_count


if __name__ == "__main__":
    import sys
    
    law_id = sys.argv[1] if len(sys.argv) > 1 else None
    embedding_model = sys.argv[2] if len(sys.argv) > 2 else "text-embedding-3-large"
    
    print(f"Vector 인덱싱 시작 (law_id={law_id}, model={embedding_model})")
    create_embeddings_and_save(law_id=law_id, embedding_model=embedding_model)
