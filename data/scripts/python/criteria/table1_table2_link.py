#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
별표1-별표2 연결 스크립트
별표1 품목과 별표2 해결기준을 연결하는 매핑 테이블 생성
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Set, Any

# 입력/출력 경로
TABLE1_INPUT = "criteria_data_chunks/table1_item_chunks.jsonl"
TABLE2_INPUT = "preprocessed_data/table2_normalized.jsonl"
OUTPUT_PATH = "preprocessed_data/table1_table2_mapping.jsonl"


def normalize_item_group(item_group: str) -> str:
    """item_group 정규화 (숫자, 괄호 제거)"""
    if not item_group:
        return ""
    # "1. 농-수 - 축산물(7개 업종)" -> "농-수 - 축산물"
    s = item_group
    # 앞의 숫자와 점 제거
    s = re.sub(r"^\d+\.\s*", "", s)
    # 뒤의 괄호 내용 제거
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)
    return s.strip()


def load_table1_items(table1_path: Path) -> Dict[str, Dict[str, Any]]:
    """
    별표1 품목 로드
    반환: {stable_id: item_data}
    """
    items = {}
    
    if not table1_path.exists():
        print(f"[WARN] Table1 파일이 없습니다: {table1_path}")
        return items
    
    with table1_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                stable_id = rec.get("stable_id")
                if stable_id:
                    metadata = rec.get("metadata", {})
                    items[stable_id] = {
                        "stable_id": stable_id,
                        "item_name": metadata.get("item_name"),
                        "item_name_normalized": metadata.get("item_name"),
                        "category": metadata.get("category"),
                        "industry": metadata.get("industry"),
                        "item_group": metadata.get("item_group"),
                        "item_group_normalized": normalize_item_group(metadata.get("item_group", "")),
                        "aliases": metadata.get("aliases", []),
                    }
            except json.JSONDecodeError:
                continue
    
    return items


def load_table2_rows(table2_path: Path) -> List[Dict[str, Any]]:
    """별표2 정규화 데이터 로드"""
    rows = []
    
    if not table2_path.exists():
        print(f"[WARN] Table2 파일이 없습니다: {table2_path}")
        return rows
    
    with table2_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                rows.append(rec)
            except json.JSONDecodeError:
                continue
    
    return rows


def match_item_tokens(table1_item: Dict[str, Any], table2_row: Dict[str, Any]) -> bool:
    """
    별표1의 item_name/aliases와 별표2의 item_tokens 매칭
    """
    table1_names = set()
    table1_names.add(table1_item.get("item_name_normalized", "").lower())
    for alias in table1_item.get("aliases", []):
        if alias:
            table1_names.add(alias.lower())
    
    table2_tokens = [token.lower() for token in table2_row.get("item_tokens", [])]
    
    # 교집합 확인
    for token in table2_tokens:
        # 정확 매칭
        if token in table1_names:
            return True
        # 부분 매칭 (token이 item_name에 포함되거나 그 반대)
        for name in table1_names:
            if token in name or name in token:
                return True
    
    return False


def create_mapping(table1_items: Dict[str, Dict[str, Any]], table2_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    별표1과 별표2 연결 매핑 생성
    """
    mappings = []
    
    for table2_row in table2_rows:
        criteria_row_id = table2_row.get("criteria_row_id")
        table2_category = table2_row.get("category", "")
        table2_item_group = table2_row.get("item_group", "")
        table2_item_group_norm = normalize_item_group(table2_item_group)
        table2_item_tokens = table2_row.get("item_tokens", [])
        
        matched_table1_ids = []
        
        # 1차: category + item_group 매칭
        for table1_id, table1_item in table1_items.items():
            if table1_item.get("category") != table2_category:
                continue
            
            table1_item_group_norm = table1_item.get("item_group_normalized", "")
            
            # item_group 매칭
            if table1_item_group_norm and table2_item_group_norm:
                if table1_item_group_norm == table2_item_group_norm:
                    matched_table1_ids.append(table1_id)
                    continue
            
            # item_tokens 매칭
            if match_item_tokens(table1_item, table2_row):
                if table1_id not in matched_table1_ids:
                    matched_table1_ids.append(table1_id)
        
        # 매핑 레코드 생성
        if matched_table1_ids:
            mapping = {
                "table1_item_ids": matched_table1_ids,
                "table2_row_id": criteria_row_id,
                "match_type": "category_item_group" if table2_item_group_norm else "category_tokens",
                "table2_category": table2_category,
                "table2_item_group": table2_item_group,
                "table2_item_tokens": table2_item_tokens,
            }
            mappings.append(mapping)
    
    return mappings


def main():
    table1_path = Path(TABLE1_INPUT)
    table2_path = Path(TABLE2_INPUT)
    output_path = Path(OUTPUT_PATH)
    
    # 출력 디렉토리 생성
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print("[INFO] 별표1 품목 로드 중...")
    table1_items = load_table1_items(table1_path)
    print(f"  로드된 품목: {len(table1_items)}개")
    
    print("[INFO] 별표2 행 로드 중...")
    table2_rows = load_table2_rows(table2_path)
    print(f"  로드된 행: {len(table2_rows)}개")
    
    print("[INFO] 매핑 생성 중...")
    mappings = create_mapping(table1_items, table2_rows)
    print(f"  생성된 매핑: {len(mappings)}개")
    
    # 통계
    table2_with_mapping = len(mappings)
    table2_without_mapping = len(table2_rows) - table2_with_mapping
    
    print(f"\n[통계]")
    print(f"  별표2 행 중 매핑된 것: {table2_with_mapping}개")
    print(f"  별표2 행 중 매핑 안 된 것: {table2_without_mapping}개")
    
    # 저장
    with output_path.open("w", encoding="utf-8") as w:
        for mapping in mappings:
            w.write(json.dumps(mapping, ensure_ascii=False) + "\n")
    
    print(f"\n[DONE] table1_table2_link")
    print(f"  출력 파일: {output_path}")


if __name__ == "__main__":
    import re
    main()
