"""
계층 검색용 JSONL 생성 스크립트

분쟁조정기준 데이터를 파싱하여 계층 정보를 포함한 JSONL 파일을 생성합니다.
- Stage 1: category/industry/item_group 레벨 (별표1)
- Stage 2: items/dispute_type/resolution 레벨 (별표2)
"""
import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional


def determine_search_stage(source_id: str, record_type: str, payload: Dict[str, Any]) -> str:
    """노드의 검색 단계 결정"""
    if source_id == "table1":
        return "stage1"  # category/industry/item_group 레벨
    elif source_id == "table2":
        return "stage2"  # items/dispute_type/resolution 레벨
    elif source_id in ["table3", "table4"]:
        return "stage1"  # 기본값
    else:
        return "stage1"


def format_table1_node(rec: Dict[str, Any]) -> Dict[str, Any]:
    """별표1 노드 포맷팅"""
    payload = rec.get("payload", {})
    
    return {
        "doc_id": rec.get("doc", {}).get("doc_id", ""),
        "source": "table1",
        "record_type": rec.get("record_type", "target_item"),
        "category": payload.get("category"),
        "industry": payload.get("industry"),
        "item_group": payload.get("item_group"),
        "item": None,  # 별표1은 item_group 레벨
        "items": payload.get("items", []),
        "dispute_type": None,
        "search_stage": "stage1",
        "text": rec.get("text", {}).get("normalized", ""),
        "doc": rec.get("doc", {})
    }


def format_table2_node(rec: Dict[str, Any]) -> Dict[str, Any]:
    """별표2 노드 포맷팅"""
    payload = rec.get("payload", {})
    
    return {
        "doc_id": rec.get("doc", {}).get("doc_id", ""),
        "source": "table2",
        "record_type": rec.get("record_type", "table_row"),
        "category": payload.get("category"),
        "industry": None,  # 별표2에는 industry 정보 없음
        "item_group": payload.get("item_group"),
        "item": payload.get("item"),
        "items": None,
        "dispute_type": payload.get("dispute_type"),
        "dispute_type_id": payload.get("dispute_type_id"),
        "resolution": payload.get("resolution"),
        "search_stage": "stage2",
        "text": rec.get("text", {}).get("normalized", ""),
        "doc": rec.get("doc", {})
    }


def format_table3_node(rec: Dict[str, Any]) -> Dict[str, Any]:
    """별표3 노드 포맷팅"""
    payload = rec.get("payload", {})
    
    return {
        "doc_id": rec.get("doc", {}).get("doc_id", ""),
        "source": "table3",
        "record_type": rec.get("record_type", "warranty_parts"),
        "category": None,
        "industry": None,
        "item_group": None,
        "item": payload.get("item"),
        "items": None,
        "dispute_type": None,
        "warranty_period": payload.get("warranty_period"),
        "parts_retention_period": payload.get("parts_retention_period"),
        "search_stage": "stage1",
        "text": rec.get("text", {}).get("normalized", ""),
        "doc": rec.get("doc", {})
    }


def format_table4_node(rec: Dict[str, Any]) -> Dict[str, Any]:
    """별표4 노드 포맷팅"""
    payload = rec.get("payload", {})
    
    return {
        "doc_id": rec.get("doc", {}).get("doc_id", ""),
        "source": "table4",
        "record_type": rec.get("record_type", "lifespan"),
        "category": None,
        "industry": None,
        "item_group": None,
        "item": payload.get("item"),
        "items": None,
        "dispute_type": None,
        "lifespan": payload.get("lifespan"),
        "search_stage": "stage1",
        "text": rec.get("text", {}).get("normalized", ""),
        "doc": rec.get("doc", {})
    }


def format_node(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """노드 포맷팅 (원천별 분기)"""
    source = rec.get("source", "")
    
    if source == "table1":
        return format_table1_node(rec)
    elif source == "table2":
        return format_table2_node(rec)
    elif source == "table3":
        return format_table3_node(rec)
    elif source == "table4":
        return format_table4_node(rec)
    else:
        # 지침 등 기타
        return {
            "doc_id": rec.get("doc", {}).get("doc_id", ""),
            "source": source,
            "record_type": rec.get("record_type", ""),
            "category": None,
            "industry": None,
            "item_group": None,
            "item": None,
            "items": None,
            "dispute_type": None,
            "search_stage": "stage1",
            "text": rec.get("text", {}).get("normalized", ""),
            "doc": rec.get("doc", {})
        }


def generate_hierarchical_jsonl(
    input_path: str,
    output_path: str
) -> int:
    """
    JSONL 파일을 파싱하여 계층 정보를 포함한 JSONL 생성
    
    Args:
        input_path: 입력 JSONL 파일 경로
        output_path: 출력 JSONL 파일 경로
    
    Returns:
        생성된 노드 수
    """
    input_file = Path(input_path)
    if not input_file.exists():
        print(f"[ERROR] 파일이 없습니다: {input_path}")
        return 0
    
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    count = 0
    with input_file.open("r", encoding="utf-8") as f_in, \
         output_file.open("w", encoding="utf-8") as f_out:
        
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            
            try:
                rec = json.loads(line)
                formatted = format_node(rec)
                
                if formatted:
                    f_out.write(json.dumps(formatted, ensure_ascii=False) + "\n")
                    count += 1
            except json.JSONDecodeError as e:
                print(f"[WARN] JSON 파싱 실패: {e}")
                continue
            except Exception as e:
                print(f"[WARN] 처리 실패: {e}")
                continue
    
    print(f"JSONL 생성 완료: {output_path} ({count}개 노드)")
    return count


def generate_all_hierarchical_jsonl(
    input_dir: str,
    output_dir: str
) -> Dict[str, int]:
    """
    디렉토리 내 모든 JSONL 파일을 처리
    
    Args:
        input_dir: 입력 JSONL 파일이 있는 디렉토리
        output_dir: 출력 JSONL 파일이 저장될 디렉토리
    
    Returns:
        파일별 노드 수 딕셔너리
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    results = {}
    jsonl_files = list(input_path.glob("*.jsonl"))
    
    print(f"총 {len(jsonl_files)}개 JSONL 파일 발견")
    
    for jsonl_file in jsonl_files:
        output_file = output_path / f"{jsonl_file.stem}_hierarchical.jsonl"
        try:
            count = generate_hierarchical_jsonl(
                str(jsonl_file),
                str(output_file)
            )
            results[jsonl_file.name] = count
        except Exception as e:
            print(f"오류 발생 ({jsonl_file.name}): {e}")
            results[jsonl_file.name] = 0
    
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  단일 파일: python generate_criteria_hierarchical_jsonl.py <input_path> [output_path]")
        print("  전체 디렉토리: python generate_criteria_hierarchical_jsonl.py --all <input_dir> [output_dir]")
        sys.exit(1)
    
    if sys.argv[1] == "--all":
        # 전체 디렉토리 처리
        input_dir = sys.argv[2] if len(sys.argv) > 2 else "criteria_jsonl_data"
        output_dir = sys.argv[3] if len(sys.argv) > 3 else "criteria_hierarchical_jsonl"
        
        results = generate_all_hierarchical_jsonl(input_dir, output_dir)
        
        print("\n=== 처리 결과 ===")
        total = 0
        for filename, count in results.items():
            print(f"{filename}: {count}개 노드")
            total += count
        print(f"\n총 {total}개 노드 생성")
    else:
        # 단일 파일 처리
        input_path = sys.argv[1]
        output_path = sys.argv[2] if len(sys.argv) > 2 else None
        
        if output_path is None:
            # 기본 출력 경로
            input_file = Path(input_path)
            output_dir = Path("criteria_hierarchical_jsonl")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(output_dir / f"{input_file.stem}_hierarchical.jsonl")
        
        generate_hierarchical_jsonl(input_path, output_path)
