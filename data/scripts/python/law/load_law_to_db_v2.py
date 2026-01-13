"""
법령 데이터 ETL 파이프라인 v2

XML 파일을 파싱하여 PostgreSQL에 적재하는 통합 파이프라인
"""
import os
import json
from typing import Any, Dict, List, Optional
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

import psycopg

try:
    from law_xml_parser_v2 import parse_xml_to_nodes
    from law_chunking_strategy import get_strategy_instance
except ImportError:
    # 상대 경로 import 시도
    import sys
    from pathlib import Path
    script_dir = Path(__file__).parent
    sys.path.insert(0, str(script_dir))
    from law_xml_parser_v2 import parse_xml_to_nodes
    from law_chunking_strategy import get_strategy_instance


def conninfo_from_env() -> str:
    return (
        f"host={os.environ.get('PGHOST','localhost')} "
        f"port={os.environ.get('PGPORT','5433')} "
        f"dbname={os.environ.get('PGDATABASE','postgres')} "
        f"user={os.environ.get('PGUSER','postgres')} "
        f"password={os.environ.get('PGPASSWORD','postgres')}"
    )


# 스키마 DDL (law_schema_v2.sql의 내용을 참고)
DDL_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS laws (
  law_id              TEXT PRIMARY KEY,
  law_name            TEXT NOT NULL,
  law_type            TEXT,
  ministry            TEXT,
  promulgation_date   DATE,
  enforcement_date     DATE,
  revision_type       TEXT,
  domain              TEXT
);

CREATE TABLE IF NOT EXISTS law_units (
  doc_id                 TEXT PRIMARY KEY,
  law_id                 TEXT NOT NULL REFERENCES laws(law_id) ON DELETE CASCADE,
  parent_id              TEXT,
  level                  TEXT NOT NULL,
  node_type              TEXT NOT NULL,
  is_indexable           BOOLEAN NOT NULL DEFAULT TRUE,
  article_no             TEXT,
  article_title          TEXT,
  paragraph_no           TEXT,
  item_no                TEXT,
  subitem_no             TEXT,
  section_path           TEXT,
  sort_key               TEXT,
  number_text            TEXT,
  path                   TEXT,
  text                   TEXT NOT NULL,
  amendment_note         TEXT,
  effective_date         DATE,
  ref_citations_internal JSONB NOT NULL DEFAULT '[]'::jsonb,
  ref_citations_external JSONB NOT NULL DEFAULT '[]'::jsonb,
  mentioned_laws         JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_law_units_law_id ON law_units(law_id);
CREATE INDEX IF NOT EXISTS idx_law_units_parent_id ON law_units(parent_id);
CREATE INDEX IF NOT EXISTS idx_law_units_level ON law_units(level);
CREATE INDEX IF NOT EXISTS idx_law_units_is_indexable ON law_units(is_indexable);
CREATE INDEX IF NOT EXISTS idx_law_units_law_article ON law_units(law_id, article_no);
"""


UPSERT_LAW_SQL = """
INSERT INTO laws (
  law_id, law_name, law_type, ministry,
  promulgation_date, enforcement_date, revision_type,
  domain
) VALUES (
  %(law_id)s, %(law_name)s, %(law_type)s, %(ministry)s,
  %(promulgation_date)s, %(enforcement_date)s, %(revision_type)s,
  %(domain)s
)
ON CONFLICT (law_id) DO UPDATE SET
  law_name=EXCLUDED.law_name,
  law_type=COALESCE(EXCLUDED.law_type, laws.law_type),
  ministry=COALESCE(EXCLUDED.ministry, laws.ministry),
  promulgation_date=COALESCE(EXCLUDED.promulgation_date, laws.promulgation_date),
  enforcement_date=COALESCE(EXCLUDED.enforcement_date, laws.enforcement_date),
  revision_type=COALESCE(EXCLUDED.revision_type, laws.revision_type),
  domain=COALESCE(EXCLUDED.domain, laws.domain);
"""


UPSERT_UNIT_SQL = """
INSERT INTO law_units (
  doc_id, law_id, parent_id,
  level, is_indexable,
  article_no, article_title, paragraph_no, item_no, subitem_no,
  path, text, amendment_note,
  section_path, chapter_no, chapter_name, section_no, section_name, search_stage,
  ref_citations_internal, ref_citations_external, mentioned_laws
) VALUES (
  %(doc_id)s, %(law_id)s, %(parent_id)s,
  %(level)s, %(is_indexable)s,
  %(article_no)s, %(article_title)s, %(paragraph_no)s, %(item_no)s, %(subitem_no)s,
  %(path)s, %(text)s, %(amendment_note)s,
  %(section_path)s::jsonb, %(chapter_no)s, %(chapter_name)s, %(section_no)s, %(section_name)s, %(search_stage)s,
  %(ref_citations_internal)s::jsonb, %(ref_citations_external)s::jsonb, %(mentioned_laws)s::jsonb
)
ON CONFLICT (doc_id) DO UPDATE SET
  law_id=EXCLUDED.law_id,
  parent_id=EXCLUDED.parent_id,
  level=EXCLUDED.level,
  is_indexable=EXCLUDED.is_indexable,
  article_no=EXCLUDED.article_no,
  article_title=EXCLUDED.article_title,
  paragraph_no=EXCLUDED.paragraph_no,
  item_no=EXCLUDED.item_no,
  subitem_no=EXCLUDED.subitem_no,
  path=EXCLUDED.path,
  text=EXCLUDED.text,
  amendment_note=EXCLUDED.amendment_note,
  section_path=EXCLUDED.section_path,
  chapter_no=EXCLUDED.chapter_no,
  chapter_name=EXCLUDED.chapter_name,
  section_no=EXCLUDED.section_no,
  section_name=EXCLUDED.section_name,
  search_stage=EXCLUDED.search_stage,
  ref_citations_internal=EXCLUDED.ref_citations_internal,
  ref_citations_external=EXCLUDED.ref_citations_external,
  mentioned_laws=EXCLUDED.mentioned_laws;
"""


def ensure_schema(conn: psycopg.Connection) -> None:
    """스키마 생성"""
    with conn.cursor() as cur:
        cur.execute(DDL_SQL)
    conn.commit()


def extract_law_info_from_xml(xml_path: str) -> Optional[Dict[str, Any]]:
    """XML 파일에서 법령 기본 정보 직접 추출"""
    import xml.etree.ElementTree as ET
    from law_xml_parser_v2 import parse_date
    
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        basic = root.find("기본정보")
        if basic is None:
            return None
        
        law_id = (basic.findtext("법령ID") or "").strip()
        law_name = (basic.findtext("법령명_한글") or "").strip()
        law_type = (basic.findtext("법종구분") or "").strip()
        ministry = (basic.findtext("소관부처") or "").strip()
        promulgation_date = parse_date(basic.findtext("공포일자"))
        enforcement_date = parse_date(basic.findtext("시행일자"))
        revision_type = (basic.findtext("제개정구분") or "").strip()
        
        return {
            "law_id": law_id,
            "law_name": law_name,
            "law_type": law_type,
            "ministry": ministry,
            "promulgation_date": promulgation_date,
            "enforcement_date": enforcement_date,
            "revision_type": revision_type,
            "domain": "statute",
        }
    except Exception as e:
        print(f"경고: XML에서 법령 정보 추출 실패: {e}")
        return None


def extract_law_info(nodes: List[Dict[str, Any]], xml_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """노드 리스트에서 법령 기본 정보 추출 (XML 직접 추출 우선)"""
    # XML에서 직접 추출 시도
    if xml_path:
        law_info = extract_law_info_from_xml(xml_path)
        if law_info:
            return law_info
    
    # 노드에서 추출 (폴백)
    if not nodes:
        return None
    
    first_node = None
    for node in nodes:
        if node.get("law_id"):
            first_node = node
            break
    
    if not first_node:
        return None
    
    return {
        "law_id": first_node.get("law_id"),
        "law_name": first_node.get("law_name"),
        "law_type": first_node.get("law_type"),
        "ministry": first_node.get("ministry"),
        "promulgation_date": None,
        "enforcement_date": None,  # 노드에서 추출 불가
        "revision_type": first_node.get("revision_type"),
        "domain": "statute",
    }


def extract_unit_row(node: Dict[str, Any]) -> Dict[str, Any]:
    """노드를 DB 적재용 딕셔너리로 변환"""
    # search_stage 결정
    level = node.get("level", "")
    is_indexable = node.get("is_indexable", False)
    
    if level == "article":
        search_stage = "stage1"
    elif level in ["paragraph", "item", "subitem"] and is_indexable:
        search_stage = "stage2"
    else:
        search_stage = "stage1"  # 기본값
    
    return {
        "doc_id": node.get("doc_id"),
        "law_id": node.get("law_id"),
        "parent_id": node.get("parent_id"),
        "level": level,
        "is_indexable": is_indexable,
        "article_no": node.get("article_no"),
        "article_title": node.get("article_title"),
        "paragraph_no": node.get("paragraph_no"),
        "item_no": node.get("item_no"),
        "subitem_no": node.get("subitem_no"),
        "path": node.get("path"),
        "text": node.get("text", ""),
        "amendment_note": node.get("amendment_note"),
        "section_path": json.dumps(node.get("section_path") or [], ensure_ascii=False),
        "chapter_no": node.get("chapter_no"),
        "chapter_name": node.get("chapter_name"),
        "section_no": node.get("section_no"),
        "section_name": node.get("section_name"),
        "search_stage": search_stage,
        "ref_citations_internal": json.dumps(node.get("ref_citations_internal") or [], ensure_ascii=False),
        "ref_citations_external": json.dumps(node.get("ref_citations_external") or [], ensure_ascii=False),
        "mentioned_laws": json.dumps(node.get("mentioned_laws") or [], ensure_ascii=False),
    }


def load_xml_to_db(
    xml_path: str,
    *,
    batch_size: int = 2000,
    strategy: Optional[Any] = None
) -> int:
    """
    XML 파일을 파싱하여 PostgreSQL에 적재
    
    Args:
        xml_path: XML 파일 경로
        batch_size: 배치 크기
        strategy: ChunkingStrategy 인스턴스 (None이면 자동 생성)
    
    Returns:
        적재된 노드 수
    """
    if strategy is None:
        strategy = get_strategy_instance()
    
    # XML 파싱
    print(f"파싱 중: {xml_path}")
    nodes = parse_xml_to_nodes(xml_path, strategy)
    print(f"파싱 완료: {len(nodes)}개 노드")
    
    if not nodes:
        print("경고: 파싱된 노드가 없습니다.")
        return 0
    
    # 법령 기본 정보 추출
    law_info = extract_law_info(nodes, xml_path=xml_path)
    if not law_info or not law_info.get("law_id"):
        print("경고: 법령 기본 정보를 추출할 수 없습니다.")
        return 0
    
    conninfo = conninfo_from_env()
    
    with psycopg.connect(conninfo) as conn:
        ensure_schema(conn)
        
        with conn.cursor() as cur:
            # 법령 정보 upsert
            cur.execute(UPSERT_LAW_SQL, law_info)
            
            # 노드 배치 적재
            unit_buffer: List[Dict[str, Any]] = []
            loaded_count = 0
            
            for node in nodes:
                unit_row = extract_unit_row(node)
                if not unit_row["doc_id"]:
                    continue
                
                unit_buffer.append(unit_row)
                
                if len(unit_buffer) >= batch_size:
                    cur.executemany(UPSERT_UNIT_SQL, unit_buffer)
                    loaded_count += len(unit_buffer)
                    unit_buffer.clear()
                    print(f"  적재 중: {loaded_count}/{len(nodes)}")
            
            # 남은 버퍼 flush
            if unit_buffer:
                cur.executemany(UPSERT_UNIT_SQL, unit_buffer)
                loaded_count += len(unit_buffer)
            
        conn.commit()
        print(f"적재 완료: {loaded_count}개 노드")
        return loaded_count


def load_multiple_xml_files(
    xml_paths: List[str],
    *,
    batch_size: int = 2000
) -> Dict[str, int]:
    """
    여러 XML 파일을 일괄 적재
    
    Returns:
        {파일명: 적재된_노드_수} 딕셔너리
    """
    results = {}
    strategy = get_strategy_instance()
    
    for xml_path in xml_paths:
        if not os.path.exists(xml_path):
            print(f"경고: 파일을 찾을 수 없습니다: {xml_path}")
            results[xml_path] = 0
            continue
        
        try:
            count = load_xml_to_db(xml_path, batch_size=batch_size, strategy=strategy)
            results[xml_path] = count
        except Exception as e:
            print(f"오류 발생 ({xml_path}): {e}")
            results[xml_path] = 0
    
    return results


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python load_law_to_db_v2.py <xml_path> [<xml_path2> ...]")
        print("또는: python load_law_to_db_v2.py --all <rawdata_dir>")
        sys.exit(1)
    
    if sys.argv[1] == "--all":
        # 모든 XML 파일 일괄 적재
        rawdata_dir = sys.argv[2] if len(sys.argv) > 2 else "../data/law_rawdata"
        xml_files = list(Path(rawdata_dir).glob("*.xml"))
        xml_paths = [str(f) for f in xml_files]
        
        print(f"일괄 적재 시작: {len(xml_paths)}개 파일")
        results = load_multiple_xml_files(xml_paths)
        
        print("\n=== 적재 결과 ===")
        for path, count in results.items():
            print(f"{Path(path).name}: {count}개 노드")
    else:
        # 단일 파일 적재
        xml_path = sys.argv[1]
        load_xml_to_db(xml_path)
