"""
법령별 청킹 전략 모듈

각 법령의 특성에 맞는 청킹 전략을 정의하고 적용합니다.
"""
import json
import os
from typing import Dict, List, Optional, Any, Set
from pathlib import Path


class ChunkingStrategy:
    """법령별 청킹 전략 클래스"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Args:
            config_path: 청킹 설정 파일 경로 (기본값: pdy/data/law_chunking_config.json)
        """
        if config_path is None:
            # 기본 경로: 스크립트 디렉토리 기준으로 상대 경로 계산
            script_dir = Path(__file__).parent
            config_path = script_dir.parent / "data" / "law_chunking_config.json"
        
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
        
        self.strategies = self.config.get("chunking_strategies", {})
        self.default_strategy = self.config.get("default_strategy", {})
    
    def get_strategy(self, law_code: str) -> Dict[str, Any]:
        """
        법령 코드에 해당하는 청킹 전략을 반환합니다.
        
        Args:
            law_code: 법령 파일 코드 (예: "Civil_Law", "Commercial_Law")
        
        Returns:
            청킹 전략 딕셔너리
        """
        # 파일명에서 확장자 제거
        law_code = law_code.replace(".xml", "").replace(".jsonl", "")
        
        strategy = self.strategies.get(law_code, self.default_strategy)
        return strategy.copy() if strategy else self.default_strategy.copy()
    
    def should_extract_sections(self, law_code: str) -> bool:
        """섹션 노드 추출 여부"""
        strategy = self.get_strategy(law_code)
        return strategy.get("section_extraction", False)
    
    def get_chunking_unit(self, law_code: str) -> str:
        """청킹 단위 반환 (article, paragraph, article_or_paragraph 등)"""
        strategy = self.get_strategy(law_code)
        return strategy.get("chunking_unit", "paragraph")
    
    def get_leaf_decomposition(self, law_code: str) -> List[str]:
        """leaf까지 분해할 노드 타입 리스트 (item, subitem 등)"""
        strategy = self.get_strategy(law_code)
        return strategy.get("leaf_decomposition", [])
    
    def get_embedding_unit(self, law_code: str) -> str:
        """임베딩 단위 반환"""
        strategy = self.get_strategy(law_code)
        return strategy.get("embedding_unit", "paragraph")
    
    def should_decompose_to_leaf(
        self, 
        law_code: str, 
        node_type: str,
        article_no: Optional[str] = None
    ) -> bool:
        """
        특정 노드 타입을 leaf까지 분해할지 여부
        
        Args:
            law_code: 법령 코드
            node_type: 노드 타입 (item, subitem 등)
            article_no: 조문 번호 (특수 규칙 적용용)
        
        Returns:
            분해 여부
        """
        strategy = self.get_strategy(law_code)
        leaf_decomp = strategy.get("leaf_decomposition", [])
        
        # 기본 전략 확인
        if node_type in leaf_decomp:
            return True
        
        # 특수 규칙 확인
        special_rules = strategy.get("special_rules", {})
        
        # 정의 조항 특수 처리 (예: Consumer_Basic_Law 제2조)
        if "definition_articles" in special_rules:
            def_rule = special_rules["definition_articles"]
            target_articles = def_rule.get("target_articles", [])
            if article_no and article_no in target_articles:
                def_leaf = def_rule.get("leaf_decomposition", [])
                return node_type in def_leaf
        
        # 정의 섹션 특수 처리 (예: Installment_Sales_Law)
        if "definition_section" in special_rules:
            def_rule = special_rules["definition_section"]
            def_leaf = def_rule.get("leaf_decomposition", [])
            return node_type in def_leaf
        
        # 예외/요건 열거 특수 처리 (예: Terms_Regulation_Law)
        if "exception_requirement_enumeration" in special_rules:
            enum_rule = special_rules["exception_requirement_enumeration"]
            enum_leaf = enum_rule.get("leaf_decomposition", [])
            return node_type in enum_leaf
        
        return False
    
    def is_indexable(
        self,
        law_code: str,
        node_type: str,
        article_no: Optional[str] = None,
        has_children: bool = False
    ) -> bool:
        """
        노드가 Vector 인덱싱 대상인지 여부
        
        Args:
            law_code: 법령 코드
            node_type: 노드 타입 (section, article, paragraph, item, subitem)
            article_no: 조문 번호
            has_children: 자식 노드 존재 여부
        
        Returns:
            인덱싱 가능 여부
        """
        # section 노드는 일반적으로 인덱싱하지 않음
        if node_type == "section":
            return False
        
        strategy = self.get_strategy(law_code)
        embedding_unit = strategy.get("embedding_unit", "paragraph")
        
        # embedding_unit에 따라 결정
        if embedding_unit == "article_or_whole":
            return node_type == "article" or (node_type == "article" and not has_children)
        elif embedding_unit == "paragraph":
            return node_type in ["paragraph", "item", "subitem"]
        elif embedding_unit == "leaf":
            return node_type in ["item", "subitem"] and not has_children
        elif embedding_unit == "paragraph_fine":
            # 정의/요건 문장은 더 잘게
            return node_type in ["paragraph", "item", "subitem"]
        else:
            # 기본: paragraph 이상은 인덱싱
            return node_type in ["paragraph", "item", "subitem"]
    
    def get_special_rule(self, law_code: str, rule_name: str) -> Optional[Dict[str, Any]]:
        """특수 규칙 조회"""
        strategy = self.get_strategy(law_code)
        special_rules = strategy.get("special_rules", {})
        return special_rules.get(rule_name)
    
    def list_law_codes(self) -> List[str]:
        """설정에 등록된 모든 법령 코드 리스트"""
        return list(self.strategies.keys())


# 전역 인스턴스 (선택적 사용)
_strategy_instance: Optional[ChunkingStrategy] = None


def get_strategy_instance(config_path: Optional[str] = None) -> ChunkingStrategy:
    """전역 전략 인스턴스 반환 (싱글톤 패턴)"""
    global _strategy_instance
    if _strategy_instance is None:
        _strategy_instance = ChunkingStrategy(config_path)
    return _strategy_instance


if __name__ == "__main__":
    # 테스트 코드
    strategy = ChunkingStrategy()
    
    print("=== 법령별 청킹 전략 테스트 ===\n")
    
    test_cases = [
        "Civil_Law",
        "Commercial_Law",
        "Consumer_Basic_Law",
        "Product_Liability_Law",
    ]
    
    for law_code in test_cases:
        print(f"[{law_code}]")
        s = strategy.get_strategy(law_code)
        print(f"  섹션 추출: {strategy.should_extract_sections(law_code)}")
        print(f"  청킹 단위: {strategy.get_chunking_unit(law_code)}")
        print(f"  Leaf 분해: {strategy.get_leaf_decomposition(law_code)}")
        print(f"  임베딩 단위: {strategy.get_embedding_unit(law_code)}")
        print(f"  item 분해 여부: {strategy.should_decompose_to_leaf(law_code, 'item')}")
        print()
