#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
별표2 정규화 스크립트
별표2 해결기준 행을 검색 가능한 구조로 정규화
- item 필드의 품목 리스트를 item_tokens 배열로 explode
- 각 행에 고유 criteria_row_id (stable_id) 생성
- ref_id 매핑: 별표2 행과 가장 가까운 reference_block을 page/element_id 기반으로 매핑
"""

import json
import re
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional

# 입력/출력 경로
TABLE2_INPUT = "criteria_jsonl_data/consumer_dispute_resolution_criteria_table2_resolutions.jsonl"
REF_BLOCK_INPUT = "criteria_jsonl_data/consumer_dispute_resolution_criteria_table2_resolutions_reference_block.jsonl"
OUTPUT_PATH = "preprocessed_data/table2_normalized.jsonl"


def md5_10(s: str) -> str:
    """문자열의 MD5 해시 앞 10자리 반환"""
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:10]


def norm_spaces(s: str) -> str:
    """공백 정규화"""
    return re.sub(r"\s+", " ", (s or "").strip())


def split_item_tokens(item_str: str) -> List[str]:
    """
    item 필드의 품목 리스트를 explode
    예: "1란류, 2육류, 3곡류" -> ["1란류", "2육류", "3곡류"]
    """
    if not item_str:
        return []
    
    # 쉼표로 분리하되, 괄호 안의 쉼표는 무시
    items = []
    current = []
    depth = 0
    
    for char in item_str:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            token = "".join(current).strip()
            if token:
                items.append(norm_spaces(token))
            current = []
            continue
        current.append(char)
    
    # 마지막 토큰
    token = "".join(current).strip()
    if token:
        items.append(norm_spaces(token))
    
    return [item for item in items if item]


def create_criteria_row_id(page: int, element_id: str, payload: Dict[str, Any]) -> str:
    """고유 criteria_row_id 생성"""
    # 고유성을 위한 해시 생성
    key_parts = [
        str(page),
        str(element_id),
        payload.get("category", ""),
        payload.get("item_group", ""),
        payload.get("item", ""),
        payload.get("dispute_type_id", ""),
    ]
    key_str = "|".join(key_parts)
    hash_part = md5_10(key_str)
    return f"table2:row:{page}:{element_id}:{hash_part}"


def build_search_text(dispute_type: Optional[str], dispute_detail: Optional[str], resolution: Optional[str]) -> str:
    """검색용 텍스트 생성"""
    parts = []
    if dispute_type:
        parts.append(dispute_type)
    if dispute_detail:
        parts.append(dispute_detail)
    if resolution:
        parts.append(resolution)
    return " ".join(parts)


def load_reference_blocks(ref_block_path: str) -> Dict[int, List[Dict[str, Any]]]:
    """
    reference_block을 page별로 그룹화하여 반환
    {page: [ref_blocks]}
    """
    ref_blocks_by_page: Dict[int, List[Dict[str, Any]]] = {}
    
    if not Path(ref_block_path).exists():
        print(f"[WARN] Reference block 파일이 없습니다: {ref_block_path}")
        return ref_blocks_by_page
    
    with open(ref_block_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                page = obj.get("page")
                if page is not None:
                    if page not in ref_blocks_by_page:
                        ref_blocks_by_page[page] = []
                    ref_blocks_by_page[page].append(obj)
            except json.JSONDecodeError:
                continue
    
    return ref_blocks_by_page


def find_nearest_ref_id(page: int, element_id: str, ref_blocks_by_page: Dict[int, List[Dict[str, Any]]]) -> Optional[str]:
    """
    별표2 행과 가장 가까운 reference_block의 ref_id 찾기
    같은 페이지의 reference_block 중에서 선택
    """
    # 같은 페이지의 reference_block 찾기
    same_page_blocks = ref_blocks_by_page.get(page, [])
    if not same_page_blocks:
        # 이전 페이지나 다음 페이지 확인
        for p in [page - 1, page + 1]:
            if p in ref_blocks_by_page:
                same_page_blocks = ref_blocks_by_page[p]
                break
    
    if not same_page_blocks:
        return None
    
    # 첫 번째 블록 반환 (더 정교한 매칭은 나중에 개선 가능)
    return same_page_blocks[0].get("ref_id")


def normalize_table2_row(rec: Dict[str, Any], ref_blocks_by_page: Dict[int, List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """별표2 행 정규화"""
    payload = rec.get("payload") or {}
    loc = rec.get("loc") or {}
    
    page = payload.get("page") or loc.get("page")
    element_id = payload.get("element_id") or loc.get("element_id") or "unknown"
    
    if page is None:
        return None
    
    # item_tokens explode
    item_str = payload.get("item") or ""
    item_tokens = split_item_tokens(item_str)
    
    # criteria_row_id 생성
    criteria_row_id = create_criteria_row_id(page, element_id, payload)
    
    # ref_id 매핑
    ref_id = find_nearest_ref_id(page, element_id, ref_blocks_by_page)
    
    # 검색용 텍스트 생성
    search_text = build_search_text(
        payload.get("dispute_type"),
        payload.get("dispute_detail"),
        payload.get("resolution")
    )
    
    # 정규화된 레코드 생성
    normalized = {
        "criteria_row_id": criteria_row_id,
        "category": payload.get("category"),
        "item_group": payload.get("item_group"),
        "item_tokens": item_tokens,
        "dispute_type_id": payload.get("dispute_type_id"),
        "dispute_type": payload.get("dispute_type"),
        "dispute_detail": payload.get("dispute_detail"),
        "resolution": payload.get("resolution"),
        "note": payload.get("note"),
        "search_text": search_text,
        "page": page,
        "element_id": element_id,
        "ref_id": ref_id,  # 가장 가까운 reference_block의 ref_id
        "metadata": {
            "source": rec.get("source"),
            "record_type": rec.get("record_type"),
            "doc": rec.get("doc"),
            "loc": loc,
            "text": rec.get("text"),
        }
    }
    
    return normalized


def main():
    input_path = Path(TABLE2_INPUT)
    ref_block_path = Path(REF_BLOCK_INPUT)
    output_path = Path(OUTPUT_PATH)
    
    if not input_path.exists():
        raise FileNotFoundError(f"입력 파일을 찾을 수 없습니다: {input_path}")
    
    # reference_block 로드
    ref_blocks_by_page = load_reference_blocks(str(ref_block_path))
    print(f"[INFO] Reference blocks 로드: {sum(len(blocks) for blocks in ref_blocks_by_page.values())}개")
    
    # 출력 디렉토리 생성
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    n_input = 0
    n_output = 0
    n_skipped = 0
    
    with output_path.open("w", encoding="utf-8") as w:
        with input_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                n_input += 1
                
                try:
                    rec = json.loads(line)
                    normalized = normalize_table2_row(rec, ref_blocks_by_page)
                    
                    if normalized:
                        w.write(json.dumps(normalized, ensure_ascii=False) + "\n")
                        n_output += 1
                    else:
                        n_skipped += 1
                        
                except json.JSONDecodeError as e:
                    print(f"[ERROR] JSON 파싱 실패 (line {n_input}): {e}")
                    n_skipped += 1
                    continue
                except Exception as e:
                    print(f"[ERROR] 처리 실패 (line {n_input}): {e}")
                    n_skipped += 1
                    continue
    
    print(f"\n[DONE] table2_normalize_for_search")
    print(f"  입력: {n_input}개")
    print(f"  출력: {n_output}개")
    print(f"  스킵: {n_skipped}개")
    print(f"  출력 파일: {output_path}")


if __name__ == "__main__":
    main()
