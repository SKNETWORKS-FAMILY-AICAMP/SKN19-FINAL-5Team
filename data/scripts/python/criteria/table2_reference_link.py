#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
별표2-근거-법령 연결 스크립트
별표2 행 → reference_block → citation_edges → law_nodes 연결 구조 생성
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional

# 입력/출력 경로
TABLE2_INPUT = "preprocessed_data/table2_normalized.jsonl"
REF_BLOCK_INPUT = "criteria_jsonl_data/consumer_dispute_resolution_criteria_table2_resolutions_reference_block.jsonl"
CITATION_EDGES_INPUT = "criteria_jsonl_data/consumer_dispute_resolution_criteria_table2_reference_citation_edges.jsonl"
LAW_NODES_INPUT = "criteria_jsonl_data/consumer_dispute_resolution_criteria_table2_reference_as_law_nodes.jsonl"
LAW_MAP_INPUT = "criteria_jsonl_data/law_map.jsonl"
OUTPUT_PATH = "preprocessed_data/table2_reference_chain.jsonl"


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """JSONL 파일 로드"""
    records = []
    if not path.exists():
        print(f"[WARN] 파일이 없습니다: {path}")
        return records
    
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                records.append(rec)
            except json.JSONDecodeError:
                continue
    
    return records


def build_reference_chain(
    table2_rows: List[Dict[str, Any]],
    ref_blocks: List[Dict[str, Any]],
    citation_edges: List[Dict[str, Any]],
    law_nodes: List[Dict[str, Any]],
    law_map: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    별표2 행 → reference_block → citation_edges → law_nodes 연결 체인 생성
    """
    # 인덱스 생성
    ref_blocks_by_id = {block.get("ref_id"): block for block in ref_blocks}
    citation_edges_by_ref_id: Dict[str, List[Dict[str, Any]]] = {}
    for edge in citation_edges:
        ref_id = edge.get("from_ref_id")
        if ref_id:
            if ref_id not in citation_edges_by_ref_id:
                citation_edges_by_ref_id[ref_id] = []
            citation_edges_by_ref_id[ref_id].append(edge)
    
    law_nodes_by_doc_id = {node.get("doc_id"): node for node in law_nodes}
    law_map_by_name: Dict[str, Dict[str, Any]] = {}
    law_map_by_id: Dict[str, Dict[str, Any]] = {}
    for law in law_map:
        law_name = law.get("law_name")
        law_id = law.get("law_id")
        if law_name:
            law_map_by_name[law_name] = law
        if law_id:
            law_map_by_id[law_id] = law
    
    chains = []
    
    for table2_row in table2_rows:
        criteria_row_id = table2_row.get("criteria_row_id")
        ref_id = table2_row.get("ref_id")
        
        if not ref_id:
            continue
        
        # reference_block 찾기
        ref_block = ref_blocks_by_id.get(ref_id)
        if not ref_block:
            continue
        
        # citation_edges 찾기
        edges = citation_edges_by_ref_id.get(ref_id, [])
        
        # 각 edge에 대해 law_node 찾기
        law_references = []
        for edge in edges:
            to_doc_id = edge.get("to_doc_id")
            law_node = law_nodes_by_doc_id.get(to_doc_id) if to_doc_id else None
            
            law_id = edge.get("law_id")
            law_name = edge.get("law_name")
            
            # law_map에서 정규화된 정보 찾기
            law_info = None
            if law_id and law_id in law_map_by_id:
                law_info = law_map_by_id[law_id]
            elif law_name and law_name in law_map_by_name:
                law_info = law_map_by_name[law_name]
            
            law_ref = {
                "edge": edge,
                "law_node": law_node,
                "law_map": law_info,
            }
            law_references.append(law_ref)
        
        # 연결 체인 생성
        chain = {
            "criteria_row_id": criteria_row_id,
            "ref_id": ref_id,
            "ref_block": ref_block,
            "law_references": law_references,
        }
        chains.append(chain)
    
    return chains


def main():
    table2_path = Path(TABLE2_INPUT)
    ref_block_path = Path(REF_BLOCK_INPUT)
    citation_edges_path = Path(CITATION_EDGES_INPUT)
    law_nodes_path = Path(LAW_NODES_INPUT)
    law_map_path = Path(LAW_MAP_INPUT)
    output_path = Path(OUTPUT_PATH)
    
    # 출력 디렉토리 생성
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print("[INFO] 데이터 로드 중...")
    
    print("  - 별표2 정규화 데이터...")
    table2_rows = load_jsonl(table2_path)
    print(f"    로드: {len(table2_rows)}개")
    
    print("  - Reference blocks...")
    ref_blocks = load_jsonl(ref_block_path)
    print(f"    로드: {len(ref_blocks)}개")
    
    print("  - Citation edges...")
    citation_edges = load_jsonl(citation_edges_path)
    print(f"    로드: {len(citation_edges)}개")
    
    print("  - Law nodes...")
    law_nodes = load_jsonl(law_nodes_path)
    print(f"    로드: {len(law_nodes)}개")
    
    print("  - Law map...")
    law_map = load_jsonl(law_map_path)
    print(f"    로드: {len(law_map)}개")
    
    print("[INFO] 연결 체인 생성 중...")
    chains = build_reference_chain(
        table2_rows,
        ref_blocks,
        citation_edges,
        law_nodes,
        law_map
    )
    print(f"  생성된 체인: {len(chains)}개")
    
    # 통계
    chains_with_laws = sum(1 for chain in chains if chain.get("law_references"))
    print(f"\n[통계]")
    print(f"  체인 중 법령 참조가 있는 것: {chains_with_laws}개")
    print(f"  체인 중 법령 참조가 없는 것: {len(chains) - chains_with_laws}개")
    
    # 저장
    with output_path.open("w", encoding="utf-8") as w:
        for chain in chains:
            w.write(json.dumps(chain, ensure_ascii=False) + "\n")
    
    print(f"\n[DONE] table2_reference_link")
    print(f"  출력 파일: {output_path}")


if __name__ == "__main__":
    main()
