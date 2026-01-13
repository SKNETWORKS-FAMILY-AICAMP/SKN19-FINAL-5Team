#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
별표3/4 정규화 스크립트
별표3(보증기간)과 별표4(내용연수)를 품목 기준으로 정규화
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

# 입력/출력 경로
TABLE3_INPUT = "criteria_jsonl_data/consumer_dispute_resolution_criteria_table3_warranty.jsonl"
TABLE4_INPUT = "criteria_jsonl_data/consumer_dispute_resolution_criteria_table4_lifespan.jsonl"
OUTPUT_TABLE3 = "preprocessed_data/table3_normalized.jsonl"
OUTPUT_TABLE4 = "preprocessed_data/table4_normalized.jsonl"


def norm_spaces(s: str) -> str:
    """공백 정규화"""
    return re.sub(r"\s+", " ", (s or "").strip())


def normalize_item_name(item_str: str) -> str:
    """
    품목명 정규화
    예: "1. 자동차" -> "자동차"
    """
    if not item_str:
        return ""
    
    s = item_str
    # 앞의 숫자와 점 제거
    s = re.sub(r"^\d+\.\s*", "", s)
    # 앞뒤 공백 정리
    s = norm_spaces(s)
    
    return s


def split_item_names(item_str: str) -> List[str]:
    """
    별표4의 item 필드에서 품목명 리스트 explode
    예: "보일러, 에어컨, TV" -> ["보일러", "에어컨", "TV"]
    """
    if not item_str:
        return []
    
    # 쉼표로 분리
    items = [norm_spaces(item) for item in item_str.split(",")]
    return [item for item in items if item]


def normalize_table3_row(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """별표3 행 정규화"""
    payload = rec.get("payload") or {}
    loc = rec.get("loc") or {}
    
    item_raw = payload.get("item") or ""
    item_name = normalize_item_name(item_raw)
    
    if not item_name:
        return None
    
    normalized = {
        "item_name": item_name,
        "item_name_normalized": item_name,
        "category": payload.get("category"),
        "item_group": payload.get("item_group"),
        "warranty_period": payload.get("warranty_period"),
        "parts_retention_period": payload.get("parts_retention_period"),
        "note": payload.get("note"),
        "page": loc.get("page") or payload.get("page"),
        "element_id": loc.get("element_id") or payload.get("element_id"),
        "metadata": {
            "source": rec.get("source"),
            "record_type": rec.get("record_type"),
            "doc": rec.get("doc"),
            "loc": loc,
            "text": rec.get("text"),
        }
    }
    
    return normalized


def normalize_table4_row(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """별표4 행 정규화"""
    payload = rec.get("payload") or {}
    loc = rec.get("loc") or {}
    
    item_raw = payload.get("item") or ""
    item_names = split_item_names(item_raw)
    
    if not item_names:
        return None
    
    normalized = {
        "item_names": item_names,
        "item_names_normalized": item_names,
        "lifespan": payload.get("lifespan"),
        "unit": payload.get("unit"),
        "note": payload.get("note"),
        "page": loc.get("page") or payload.get("page"),
        "element_id": loc.get("element_id") or payload.get("element_id"),
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
    table3_path = Path(TABLE3_INPUT)
    table4_path = Path(TABLE4_INPUT)
    output_table3 = Path(OUTPUT_TABLE3)
    output_table4 = Path(OUTPUT_TABLE4)
    
    # 출력 디렉토리 생성
    output_table3.parent.mkdir(parents=True, exist_ok=True)
    output_table4.parent.mkdir(parents=True, exist_ok=True)
    
    # 별표3 정규화
    if table3_path.exists():
        print("[INFO] 별표3 정규화 중...")
        n_input = 0
        n_output = 0
        n_skipped = 0
        
        with output_table3.open("w", encoding="utf-8") as w:
            with table3_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    n_input += 1
                    
                    try:
                        rec = json.loads(line)
                        normalized = normalize_table3_row(rec)
                        
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
        
        print(f"  입력: {n_input}개")
        print(f"  출력: {n_output}개")
        print(f"  스킵: {n_skipped}개")
        print(f"  출력 파일: {output_table3}")
    else:
        print(f"[WARN] 별표3 파일이 없습니다: {table3_path}")
    
    # 별표4 정규화
    if table4_path.exists():
        print("\n[INFO] 별표4 정규화 중...")
        n_input = 0
        n_output = 0
        n_skipped = 0
        
        with output_table4.open("w", encoding="utf-8") as w:
            with table4_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    n_input += 1
                    
                    try:
                        rec = json.loads(line)
                        normalized = normalize_table4_row(rec)
                        
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
        
        print(f"  입력: {n_input}개")
        print(f"  출력: {n_output}개")
        print(f"  스킵: {n_skipped}개")
        print(f"  출력 파일: {output_table4}")
    else:
        print(f"[WARN] 별표4 파일이 없습니다: {table4_path}")
    
    print(f"\n[DONE] table3_table4_normalize")


if __name__ == "__main__":
    main()
