#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
분쟁조정기준 데이터를 criteria + criteria_units 테이블에 적재하는 스크립트
새로운 통합 스키마 사용
"""

import json
import hashlib
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

# 데이터베이스 연결 정보
conninfo = (
    f"host={os.environ.get('PGHOST', 'localhost')} "
    f"port={os.environ.get('PGPORT', '5432')} "
    f"dbname={os.environ.get('PGDATABASE', 'ddoksori_db')} "
    f"user={os.environ.get('PGUSER', 'postgres')} "
    f"password={os.environ.get('PGPASSWORD', '')}"
)


def md5_hash(text: str) -> str:
    """텍스트의 MD5 해시 반환"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def extract_unit_text(rec: Dict[str, Any], source_id: str) -> str:
    """
    원천별로 unit_text 추출
    """
    if source_id == "table1":
        # 별표1: embed_text 사용
        return rec.get("embed_text", "")
    elif source_id == "table2":
        # 별표2: search_text 또는 dispute_type + resolution
        payload = rec.get("payload", {})
        parts = []
        if payload.get("dispute_type"):
            parts.append(payload["dispute_type"])
        if payload.get("dispute_detail"):
            parts.append(payload["dispute_detail"])
        if payload.get("resolution"):
            parts.append(payload["resolution"])
        return " | ".join(parts) if parts else rec.get("text", {}).get("normalized", "")
    elif source_id in ["table3", "table4"]:
        # 별표3/4: text.normalized 사용
        return rec.get("text", {}).get("normalized", "")
    elif source_id in ["ecommerce_guideline", "content_guideline"]:
        # 지침: payload.body 또는 text.normalized
        payload = rec.get("payload", {})
        return payload.get("body") or rec.get("text", {}).get("normalized", "")
    else:
        # 기본: text.normalized
        return rec.get("text", {}).get("normalized", "")


def extract_path_hint(rec: Dict[str, Any], source_id: str) -> Optional[str]:
    """
    path_hint 추출 (문서/헤딩 기반 경로 요약)
    """
    if source_id in ["ecommerce_guideline", "content_guideline"]:
        payload = rec.get("payload", {})
        clause_path = payload.get("clause_path", [])
        if clause_path:
            return " > ".join(clause_path)
        heading = payload.get("heading")
        if heading:
            return heading
    return None


def load_table1_items():
    """별표1 데이터 적재"""
    input_path = Path("criteria_data_chunks/table1_item_chunks.jsonl")
    if not input_path.exists():
        print(f"[WARN] 파일이 없습니다: {input_path}")
        return 0
    
    conn = psycopg.connect(conninfo, row_factory=dict_row)
    cur = conn.cursor()
    
    count = 0
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            try:
                rec = json.loads(line)
                stable_id = rec.get("stable_id")
                if not stable_id:
                    continue
                
                unit_text = extract_unit_text(rec, "table1")
                content_md5 = md5_hash(unit_text) if unit_text else None
                
                # unit_id = source_id:stable_id
                unit_id = f"table1:{stable_id}"
                
                # 계층 정보 추출 (별표1)
                payload = rec.get("payload", {})
                category = payload.get("category")
                industry = payload.get("industry")
                item_group = payload.get("item_group")
                item = None  # 별표1은 item_group 레벨
                dispute_type = None
                search_stage = "stage1"  # category/industry/item_group 레벨
                
                cur.execute("""
                    INSERT INTO criteria_units (
                        unit_id, source_id, record_type, unit_type,
                        path_hint, unit_text, content_md5, doc,
                        category, industry, item_group, item, dispute_type, search_stage
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (unit_id) DO UPDATE SET
                        unit_text = EXCLUDED.unit_text,
                        content_md5 = EXCLUDED.content_md5,
                        doc = EXCLUDED.doc,
                        category = EXCLUDED.category,
                        industry = EXCLUDED.industry,
                        item_group = EXCLUDED.item_group,
                        item = EXCLUDED.item,
                        dispute_type = EXCLUDED.dispute_type,
                        search_stage = EXCLUDED.search_stage,
                        updated_at = now()
                """, (
                    unit_id,
                    "table1",
                    rec.get("record_type", "item_chunk"),
                    None,
                    None,
                    unit_text,
                    content_md5,
                    json.dumps(rec, ensure_ascii=False),
                    category,
                    industry,
                    item_group,
                    item,
                    dispute_type,
                    search_stage
                ))
                count += 1
                
            except Exception as e:
                print(f"[ERROR] 처리 실패: {e}")
                continue
    
    conn.commit()
    cur.close()
    conn.close()
    
    return count


def load_table2_resolutions():
    """별표2 해결기준 데이터 적재 (reference_block, citation_edges, law_nodes 포함)"""
    # reference_block 로드
    ref_blocks_by_page: Dict[int, List[Dict[str, Any]]] = {}
    ref_blocks_by_ref_id: Dict[str, Dict[str, Any]] = {}
    ref_block_path = Path("criteria_jsonl_data/consumer_dispute_resolution_criteria_table2_resolutions_reference_block.jsonl")
    
    if ref_block_path.exists():
        with ref_block_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    ref_id = obj.get("ref_id")
                    page = obj.get("page")
                    if ref_id:
                        ref_blocks_by_ref_id[ref_id] = obj
                    if page is not None:
                        if page not in ref_blocks_by_page:
                            ref_blocks_by_page[page] = []
                        ref_blocks_by_page[page].append(obj)
                except json.JSONDecodeError:
                    continue
    
    # citation_edges 로드 (ref_id -> edges 매핑)
    citation_edges_by_ref_id: Dict[str, List[Dict[str, Any]]] = {}
    citation_edges_path = Path("criteria_jsonl_data/consumer_dispute_resolution_criteria_table2_reference_citation_edges.jsonl")
    
    if citation_edges_path.exists():
        with citation_edges_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    from_ref_id = obj.get("from_ref_id")
                    if from_ref_id:
                        if from_ref_id not in citation_edges_by_ref_id:
                            citation_edges_by_ref_id[from_ref_id] = []
                        citation_edges_by_ref_id[from_ref_id].append(obj)
                except json.JSONDecodeError:
                    continue
    
    # law_nodes 로드 (doc_id -> node 매핑)
    law_nodes_by_doc_id: Dict[str, Dict[str, Any]] = {}
    law_nodes_path = Path("criteria_jsonl_data/consumer_dispute_resolution_criteria_table2_reference_as_law_nodes.jsonl")
    
    if law_nodes_path.exists():
        with law_nodes_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    doc_id = obj.get("doc_id")
                    if doc_id:
                        law_nodes_by_doc_id[doc_id] = obj
                except json.JSONDecodeError:
                    continue
    
    # 별표2 resolutions 로드
    input_path = Path("criteria_jsonl_data/consumer_dispute_resolution_criteria_table2_resolutions.jsonl")
    if not input_path.exists():
        print(f"[WARN] 파일이 없습니다: {input_path}")
        return 0
    
    conn = psycopg.connect(conninfo, row_factory=dict_row)
    cur = conn.cursor()
    
    count = 0
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            try:
                rec = json.loads(line)
                payload = rec.get("payload", {})
                loc = rec.get("loc", {})
                
                page = payload.get("page") or loc.get("page")
                element_id = payload.get("element_id") or loc.get("element_id") or "unknown"
                
                if page is None:
                    continue
                
                # unit_id 생성
                criteria_row_id = f"table2:row:{page}:{element_id}:{md5_hash(str(payload))[:10]}"
                unit_id = f"table2:{criteria_row_id}"
                
                # reference_block 찾기 (같은 페이지)
                nearest_ref_block = None
                if page in ref_blocks_by_page:
                    nearest_ref_block = ref_blocks_by_page[page][0] if ref_blocks_by_page[page] else None
                
                # doc에 reference_block, citation_edges, law_nodes 포함
                doc_data = rec.copy()
                if nearest_ref_block:
                    ref_id = nearest_ref_block.get("ref_id")
                    doc_data["reference_block"] = nearest_ref_block
                    
                    # citation_edges 찾기
                    citation_edges = citation_edges_by_ref_id.get(ref_id, [])
                    if citation_edges:
                        # 각 citation_edge에 해당하는 law_node 찾기
                        enriched_edges = []
                        for edge in citation_edges:
                            to_doc_id = edge.get("to_doc_id")
                            enriched_edge = edge.copy()
                            if to_doc_id and to_doc_id in law_nodes_by_doc_id:
                                enriched_edge["law_node"] = law_nodes_by_doc_id[to_doc_id]
                            enriched_edges.append(enriched_edge)
                        doc_data["citation_edges"] = enriched_edges
                
                unit_text = extract_unit_text(rec, "table2")
                content_md5 = md5_hash(unit_text) if unit_text else None
                
                # 계층 정보 추출 (별표2)
                category = payload.get("category")
                industry = None  # 별표2에는 industry 정보 없음
                item_group = payload.get("item_group")
                item = payload.get("item")
                dispute_type = payload.get("dispute_type")
                search_stage = "stage2"  # items/dispute_type/resolution 레벨
                
                cur.execute("""
                    INSERT INTO criteria_units (
                        unit_id, source_id, record_type, unit_type,
                        path_hint, unit_text, content_md5, doc,
                        category, industry, item_group, item, dispute_type, search_stage
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (unit_id) DO UPDATE SET
                        unit_text = EXCLUDED.unit_text,
                        content_md5 = EXCLUDED.content_md5,
                        doc = EXCLUDED.doc,
                        category = EXCLUDED.category,
                        industry = EXCLUDED.industry,
                        item_group = EXCLUDED.item_group,
                        item = EXCLUDED.item,
                        dispute_type = EXCLUDED.dispute_type,
                        search_stage = EXCLUDED.search_stage,
                        updated_at = now()
                """, (
                    unit_id,
                    "table2",
                    rec.get("record_type", "table_row"),
                    None,
                    None,
                    unit_text,
                    content_md5,
                    json.dumps(doc_data, ensure_ascii=False),
                    category,
                    industry,
                    item_group,
                    item,
                    dispute_type,
                    search_stage
                ))
                count += 1
                
            except Exception as e:
                print(f"[ERROR] 처리 실패: {e}")
                continue
    
    conn.commit()
    cur.close()
    conn.close()
    
    return count


def load_table3_warranty():
    """별표3 데이터 적재"""
    input_path = Path("criteria_jsonl_data/consumer_dispute_resolution_criteria_table3_warranty.jsonl")
    if not input_path.exists():
        print(f"[WARN] 파일이 없습니다: {input_path}")
        return 0
    
    conn = psycopg.connect(conninfo, row_factory=dict_row)
    cur = conn.cursor()
    
    count = 0
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            try:
                rec = json.loads(line)
                loc = rec.get("loc", {})
                payload = rec.get("payload", {})
                
                # unit_id 생성
                page = loc.get("page") or payload.get("page")
                element_id = loc.get("element_id") or payload.get("element_id") or "unknown"
                row_index = loc.get("row_index", 0)
                unit_id = f"table3:{page}:{element_id}:{row_index}"
                
                unit_text = extract_unit_text(rec, "table3")
                content_md5 = md5_hash(unit_text) if unit_text else None
                
                cur.execute("""
                    INSERT INTO criteria_units (
                        unit_id, source_id, record_type, unit_type,
                        path_hint, unit_text, content_md5, doc
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (unit_id) DO UPDATE SET
                        unit_text = EXCLUDED.unit_text,
                        content_md5 = EXCLUDED.content_md5,
                        doc = EXCLUDED.doc,
                        updated_at = now()
                """, (
                    unit_id,
                    "table3",
                    rec.get("record_type", "warranty_parts"),
                    None,
                    None,
                    unit_text,
                    content_md5,
                    json.dumps(rec, ensure_ascii=False)
                ))
                count += 1
                
            except Exception as e:
                print(f"[ERROR] 처리 실패: {e}")
                continue
    
    conn.commit()
    cur.close()
    conn.close()
    
    return count


def load_table4_lifespan():
    """별표4 데이터 적재"""
    input_path = Path("criteria_jsonl_data/consumer_dispute_resolution_criteria_table4_lifespan.jsonl")
    if not input_path.exists():
        print(f"[WARN] 파일이 없습니다: {input_path}")
        return 0
    
    conn = psycopg.connect(conninfo, row_factory=dict_row)
    cur = conn.cursor()
    
    count = 0
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            try:
                rec = json.loads(line)
                loc = rec.get("loc", {})
                payload = rec.get("payload", {})
                
                # unit_id 생성
                page = loc.get("page") or payload.get("page")
                element_id = loc.get("element_id") or payload.get("element_id") or "unknown"
                row_index = loc.get("row_index", 0)
                unit_id = f"table4:{page}:{element_id}:{row_index}"
                
                unit_text = extract_unit_text(rec, "table4")
                content_md5 = md5_hash(unit_text) if unit_text else None
                
                cur.execute("""
                    INSERT INTO criteria_units (
                        unit_id, source_id, record_type, unit_type,
                        path_hint, unit_text, content_md5, doc
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (unit_id) DO UPDATE SET
                        unit_text = EXCLUDED.unit_text,
                        content_md5 = EXCLUDED.content_md5,
                        doc = EXCLUDED.doc,
                        updated_at = now()
                """, (
                    unit_id,
                    "table4",
                    rec.get("record_type", "lifespan"),
                    None,
                    None,
                    unit_text,
                    content_md5,
                    json.dumps(rec, ensure_ascii=False)
                ))
                count += 1
                
            except Exception as e:
                print(f"[ERROR] 처리 실패: {e}")
                continue
    
    conn.commit()
    cur.close()
    conn.close()
    
    return count


def load_guidelines(source_id: str, input_path: Path):
    """지침 데이터 적재"""
    if not input_path.exists():
        print(f"[WARN] 파일이 없습니다: {input_path}")
        return 0
    
    conn = psycopg.connect(conninfo, row_factory=dict_row)
    cur = conn.cursor()
    
    count = 0
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            try:
                rec = json.loads(line)
                loc = rec.get("loc", {})
                
                # unit_id 생성
                page = loc.get("page")
                element_id = loc.get("element_id") or "unknown"
                unit_id = f"{source_id}:{page}:{element_id}"
                
                unit_text = extract_unit_text(rec, source_id)
                content_md5 = md5_hash(unit_text) if unit_text else None
                path_hint = extract_path_hint(rec, source_id)
                
                cur.execute("""
                    INSERT INTO criteria_units (
                        unit_id, source_id, record_type, unit_type,
                        path_hint, unit_text, content_md5, doc
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (unit_id) DO UPDATE SET
                        unit_text = EXCLUDED.unit_text,
                        content_md5 = EXCLUDED.content_md5,
                        path_hint = EXCLUDED.path_hint,
                        doc = EXCLUDED.doc,
                        updated_at = now()
                """, (
                    unit_id,
                    source_id,
                    rec.get("record_type", "guideline_chunk"),
                    None,
                    path_hint,
                    unit_text,
                    content_md5,
                    json.dumps(rec, ensure_ascii=False)
                ))
                count += 1
                
            except Exception as e:
                print(f"[ERROR] 처리 실패: {e}")
                continue
    
    conn.commit()
    cur.close()
    conn.close()
    
    return count


def main():
    print("[INFO] 분쟁조정기준 데이터 적재 시작...")
    
    # criteria 원천은 스키마에서 자동 생성됨
    
    print("\n[1] 별표1 데이터 적재 중...")
    count1 = load_table1_items()
    print(f"  적재 완료: {count1}개")
    
    print("\n[2] 별표2 데이터 적재 중...")
    count2 = load_table2_resolutions()
    print(f"  적재 완료: {count2}개")
    
    print("\n[3] 별표3 데이터 적재 중...")
    count3 = load_table3_warranty()
    print(f"  적재 완료: {count3}개")
    
    print("\n[4] 별표4 데이터 적재 중...")
    count4 = load_table4_lifespan()
    print(f"  적재 완료: {count4}개")
    
    print("\n[5] 전자상거래 지침 적재 중...")
    count5 = load_guidelines("ecommerce_guideline", Path("criteria_jsonl_data/ecommerce_guideline.jsonl"))
    print(f"  적재 완료: {count5}개")
    
    print("\n[6] 콘텐츠 지침 적재 중...")
    count6 = load_guidelines("content_guideline", Path("criteria_jsonl_data/content_guideline.jsonl"))
    print(f"  적재 완료: {count6}개")
    
    total = count1 + count2 + count3 + count4 + count5 + count6
    print(f"\n[DONE] 전체 적재 완료: {total}개")


if __name__ == "__main__":
    main()
