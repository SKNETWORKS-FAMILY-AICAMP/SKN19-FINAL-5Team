"""
계층적 검색용 JSONL 생성 스크립트

XML 파일을 파싱하여 계층적 검색에 필요한 구조의 JSONL 파일을 생성합니다.
- Stage 1: 장/절/조 검색용 (article 레벨)
- Stage 2: 항/호/목 Vector 검색용 (paragraph/item/subitem 레벨)
"""
import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    from law_xml_parser_v2 import parse_xml_to_nodes
except ImportError:
    import sys
    from pathlib import Path
    script_dir = Path(__file__).parent
    sys.path.insert(0, str(script_dir))
    from law_xml_parser_v2 import parse_xml_to_nodes


def determine_search_stage(level: str, is_indexable: bool) -> str:
    """노드의 검색 단계 결정"""
    if level == "article":
        return "stage1"
    elif level in ["paragraph", "item", "subitem"] and is_indexable:
        return "stage2"
    else:
        return "stage1"  # 기본값


def build_children_map(nodes: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """parent_id를 기반으로 children 맵 생성"""
    children_map: Dict[str, List[str]] = {}
    
    for node in nodes:
        parent_id = node.get("parent_id")
        if parent_id:
            if parent_id not in children_map:
                children_map[parent_id] = []
            children_map[parent_id].append(node["doc_id"])
    
    return children_map


def format_node_for_jsonl(
    node: Dict[str, Any],
    children: Optional[List[str]] = None
) -> Dict[str, Any]:
    """노드를 JSONL 형식으로 변환"""
    formatted = {
        "doc_id": node["doc_id"],
        "law_id": node["law_id"],
        "law_name": node.get("law_name", ""),
        "level": node["level"],
        "section_path": node.get("section_path", []),
        "chapter_no": node.get("chapter_no"),
        "chapter_name": node.get("chapter_name"),
        "section_no": node.get("section_no"),
        "section_name": node.get("section_name"),
        "article_no": node.get("article_no"),
        "article_title": node.get("article_title"),
        "paragraph_no": node.get("paragraph_no"),
        "item_no": node.get("item_no"),
        "subitem_no": node.get("subitem_no"),
        "path": node.get("path", ""),
        "text": node.get("text", ""),
        "parent_id": node.get("parent_id"),
        "is_indexable": node.get("is_indexable", False),
        "search_stage": determine_search_stage(
            node["level"],
            node.get("is_indexable", False)
        ),
    }
    
    # children 추가 (있는 경우)
    if children:
        formatted["children"] = children
    
    # Stage 2 노드의 경우 embedding_text 생성
    if formatted["search_stage"] == "stage2":
        embedding_parts = []
        if formatted["article_no"]:
            embedding_parts.append(formatted["article_no"])
        if formatted["paragraph_no"]:
            embedding_parts.append(f"제{formatted['paragraph_no']}항")
        if formatted["item_no"]:
            embedding_parts.append(f"제{formatted['item_no']}호")
        if formatted["subitem_no"]:
            embedding_parts.append(f"{formatted['subitem_no']}목")
        
        embedding_text = ": ".join(embedding_parts) if embedding_parts else ""
        if embedding_text and formatted["text"]:
            embedding_text += ": " + formatted["text"]
        elif formatted["text"]:
            embedding_text = formatted["text"]
        
        formatted["embedding_text"] = embedding_text
    
    return formatted


def generate_hierarchical_jsonl(
    xml_path: str,
    output_path: str
) -> int:
    """
    XML 파일을 파싱하여 계층적 검색용 JSONL 생성
    
    Args:
        xml_path: 입력 XML 파일 경로
        output_path: 출력 JSONL 파일 경로
    
    Returns:
        생성된 노드 수
    """
    # XML 파싱
    print(f"파싱 중: {xml_path}")
    nodes = parse_xml_to_nodes(xml_path)
    print(f"파싱 완료: {len(nodes)}개 노드")
    
    # children 맵 생성
    children_map = build_children_map(nodes)
    
    # JSONL 파일 생성
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    count = 0
    with open(output_file, "w", encoding="utf-8") as f:
        for node in nodes:
            children = children_map.get(node["doc_id"])
            formatted_node = format_node_for_jsonl(node, children)
            f.write(json.dumps(formatted_node, ensure_ascii=False) + "\n")
            count += 1
    
    print(f"JSONL 생성 완료: {output_path} ({count}개 노드)")
    return count


def generate_all_hierarchical_jsonl(
    xml_dir: str,
    output_dir: str
) -> Dict[str, int]:
    """
    디렉토리 내 모든 XML 파일을 처리
    
    Args:
        xml_dir: XML 파일이 있는 디렉토리
        output_dir: 출력 JSONL 파일이 저장될 디렉토리
    
    Returns:
        파일별 노드 수 딕셔너리
    """
    xml_path = Path(xml_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    results = {}
    xml_files = list(xml_path.glob("*.xml"))
    
    print(f"총 {len(xml_files)}개 XML 파일 발견")
    
    for xml_file in xml_files:
        output_file = output_path / f"{xml_file.stem}.jsonl"
        try:
            count = generate_hierarchical_jsonl(
                str(xml_file),
                str(output_file)
            )
            results[xml_file.name] = count
        except Exception as e:
            print(f"오류 발생 ({xml_file.name}): {e}")
            results[xml_file.name] = 0
    
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  단일 파일: python generate_hierarchical_jsonl.py <xml_path> [output_path]")
        print("  전체 디렉토리: python generate_hierarchical_jsonl.py --all <xml_dir> [output_dir]")
        sys.exit(1)
    
    if sys.argv[1] == "--all":
        # 전체 디렉토리 처리
        xml_dir = sys.argv[2] if len(sys.argv) > 2 else "../data/law_rawdata"
        output_dir = sys.argv[3] if len(sys.argv) > 3 else "../data/law_hierarchical"
        
        results = generate_all_hierarchical_jsonl(xml_dir, output_dir)
        
        print("\n=== 처리 결과 ===")
        total = 0
        for filename, count in results.items():
            print(f"{filename}: {count}개 노드")
            total += count
        print(f"\n총 {total}개 노드 생성")
    else:
        # 단일 파일 처리
        xml_path = sys.argv[1]
        output_path = sys.argv[2] if len(sys.argv) > 2 else None
        
        if output_path is None:
            # 기본 출력 경로: ../data/law_hierarchical/<filename>.jsonl
            xml_file = Path(xml_path)
            output_dir = Path(__file__).parent.parent / "data" / "law_hierarchical"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(output_dir / f"{xml_file.stem}.jsonl")
        
        generate_hierarchical_jsonl(xml_path, output_path)
