"""
행정규칙 청킹 스크립트 (계층적 청킹)
- 대상: 01_parsed/02_Guide/*.json (행정규칙 5개)
- 청킹 유형: 계층적 청킹 (부모-자식), 일반 청킹
- 전략: 예시 중심 사례 검색을 위한 계층적 청킹
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime


class GuideChunker:
    """행정규칙 계층적 청킹 클래스"""

    def __init__(self, guide_dir: str = "01_parsed/02_Guide"):
        self.guide_dir = Path(guide_dir)
        self.chunks = []

    def process_all_guides(self) -> List[Dict]:
        """모든 행정규칙 파일 처리"""
        json_files = list(self.guide_dir.glob("*.json"))

        print(f"총 {len(json_files)}개 파일 발견")

        for json_file in json_files:
            print(f"\n처리 중: {json_file.name}")
            guide_chunks = self.chunk_guide_file(json_file)
            self.chunks.extend(guide_chunks)
            print(f"  → {len(guide_chunks)}개 청크 생성")

        print(f"\n총 {len(self.chunks)}개 청크 생성 완료")
        return self.chunks

    def chunk_guide_file(self, file_path: Path) -> List[Dict]:
        """단일 행정규칙 파일 청킹"""
        with open(file_path, 'r', encoding='utf-8') as f:
            guide_data = json.load(f)

        법령명 = guide_data["법령명"]
        법령번호 = guide_data.get("법령번호", "")
        시행일 = guide_data.get("시행일", "")
        소관부처 = guide_data.get("소관부처", "")

        chunks = []

        # 구조 유형 판단
        구조유형 = self._determine_structure_type(guide_data)
        print(f"  구조 유형: {구조유형}")

        if 구조유형 == "계층형":
            chunks = self._chunk_hierarchical(
                guide_data["본문"],
                법령명, 법령번호, 시행일, 소관부처
            )
        else:  # 조문형
            chunks = self._chunk_article_based(
                guide_data["본문"],
                법령명, 법령번호, 시행일, 소관부처
            )

        return chunks

    def _determine_structure_type(self, guide_data: Dict) -> str:
        """구조 유형 판단: 계층형 vs 조문형"""
        본문 = guide_data.get("본문", [])

        if not 본문:
            return "조문형"

        # 첫 번째 항목 확인
        first_item = 본문[0]

        # 계층형: "번호" 필드가 있고, 로마 숫자나 숫자 형식
        if "번호" in first_item:
            return "계층형"

        # 조문형: "조" 필드가 있음
        if "조" in first_item:
            return "조문형"

        # 기본값: 계층형
        return "계층형"

    def _chunk_hierarchical(
        self,
        본문: List[Dict],
        법령명: str, 법령번호: str, 시행일: str, 소관부처: str
    ) -> List[Dict]:
        """계층형 행정규칙 계층적 청킹"""
        chunks = []

        for 대분류_item in 본문:
            대분류 = 대분류_item.get("분류", "")
            대분류_제목 = 대분류_item.get("제목", "")

            for 중분류_item in 대분류_item.get("내용", []):
                중분류 = 중분류_item.get("번호", "")
                중분류_제목 = 중분류_item.get("제목", "")

                for 소분류_item in 중분류_item.get("내용", []):
                    소분류 = 소분류_item.get("번호", "")
                    소분류_제목 = 소분류_item.get("제목", "")

                    # 예시 추출
                    예시_항목들 = self._extract_examples(소분류_item.get("내용", []))

                    # 계층적 청킹 조건: 예시가 2개 이상
                    if len(예시_항목들) >= 2:
                        # 부모 + 자식 청크 생성
                        parent, children = self._create_hierarchical_chunks(
                            소분류_item,
                            법령명, 법령번호, 시행일, 소관부처,
                            대분류, 대분류_제목,
                            중분류, 중분류_제목,
                            소분류, 소분류_제목
                        )
                        chunks.append(parent)
                        chunks.extend(children)
                    else:
                        # 일반 청크 (자식만, 부모 없음)
                        chunk = self._create_single_chunk(
                            소분류_item,
                            법령명, 법령번호, 시행일, 소관부처,
                            대분류, 대분류_제목,
                            중분류, 중분류_제목,
                            소분류, 소분류_제목
                        )
                        chunks.append(chunk)

        return chunks

    def _extract_examples(self, 내용: List[Dict]) -> List[Dict]:
        """예시 항목 추출"""
        examples = []

        for item in 내용:
            # 예시 구분자 확인
            if "구분" in item and "예시" in item.get("구분", ""):
                continue

            # 번호가 있는 예시 (1), (2), (3)
            if "번호" in item and item["번호"].startswith("("):
                examples.append(item)

            # 기호 예시 (ㅇ)
            elif "기호" in item:
                examples.append(item)

        return examples

    def _create_hierarchical_chunks(
        self,
        소분류_item: Dict,
        법령명: str, 법령번호: str, 시행일: str, 소관부처: str,
        대분류: str, 대분류_제목: str,
        중분류: str, 중분류_제목: str,
        소분류: str, 소분류_제목: str
    ) -> Tuple[Dict, List[Dict]]:
        """계층적 청킹: 부모 1개 + 자식 N개"""

        # 1. 부모 청크 생성 (소분류 전체)
        parent_id = f"{법령명}_{대분류}_{중분류}_{소분류}_부모"
        parent_text = self._build_full_section_text(소분류, 소분류_제목, 소분류_item.get("내용", []))
        hierarchy_path = f"{대분류}. {대분류_제목} > {중분류}. {중분류_제목} > {소분류}. {소분류_제목}"

        parent_chunk = {
            "chunk_id": parent_id,
            "법령명": 법령명,
            "법령번호": 법령번호,
            "시행일": 시행일,
            "소관부처": 소관부처,
            "문서유형": "행정규칙",
            "구조유형": "계층형",

            "대분류": 대분류,
            "대분류_제목": 대분류_제목,
            "중분류": 중분류,
            "중분류_제목": 중분류_제목,
            "소분류": 소분류,
            "소분류_제목": 소분류_제목,

            "hierarchy_path": hierarchy_path,

            "text": parent_text,
            "text_length": len(parent_text),

            # 계층적 청킹 메타데이터
            "chunk_type": "부모_청크",
            "parent_chunk_id": None,
            "자식_청크_ids": [],  # 나중에 채움

            "is_indexed": False,  # 검색 대상 아님!
            "has_embedding": False,  # 임베딩 안 함!

            "is_example": False,
            "keywords": self._extract_keywords_from_title(소분류_제목),
            "metadata": {
                "created_at": datetime.now().isoformat()
            }
        }

        # 2. 자식 청크들 생성
        children = []

        # 2-1. 도입 본문 자식 (정의/개념)
        도입_본문 = self._extract_intro_text(소분류_item.get("내용", []))
        if 도입_본문:
            intro_child = self._create_intro_child(
                도입_본문,
                parent_id,
                법령명, 법령번호, 시행일, 소관부처,
                대분류, 대분류_제목,
                중분류, 중분류_제목,
                소분류, 소분류_제목,
                hierarchy_path
            )
            children.append(intro_child)

        # 2-2. 예시별 자식
        예시_항목들 = self._extract_examples(소분류_item.get("내용", []))
        for 예시 in 예시_항목들:
            example_child = self._create_example_child(
                예시,
                parent_id,
                법령명, 법령번호, 시행일, 소관부처,
                대분류, 대분류_제목,
                중분류, 중분류_제목,
                소분류, 소분류_제목,
                hierarchy_path
            )
            children.append(example_child)

        # 3. 부모에 자식 ID 연결
        parent_chunk['자식_청크_ids'] = [c['chunk_id'] for c in children]

        return parent_chunk, children

    def _extract_intro_text(self, 내용: List[Dict]) -> Optional[str]:
        """도입 본문 추출 (정의/개념)"""
        intro_parts = []

        for item in 내용:
            # 본문만 추출
            if "본문" in item:
                intro_parts.append(item["본문"])
            # 예시 구분자나 예시가 나오면 중단
            elif "구분" in item or "번호" in item or "기호" in item:
                break

        if intro_parts:
            return "\n".join(intro_parts)
        return None

    def _create_intro_child(
        self,
        도입_본문: str,
        parent_id: str,
        법령명: str, 법령번호: str, 시행일: str, 소관부처: str,
        대분류: str, 대분류_제목: str,
        중분류: str, 중분류_제목: str,
        소분류: str, 소분류_제목: str,
        hierarchy_path: str
    ) -> Dict:
        """도입 본문 자식 청크 생성 (개념 요약)"""

        child_id = f"{법령명}_{대분류}_{중분류}_{소분류}_도입"
        text = f"{소분류}. {소분류_제목}\n\n{도입_본문}"

        return {
            "chunk_id": child_id,
            "법령명": 법령명,
            "법령번호": 법령번호,
            "시행일": 시행일,
            "소관부처": 소관부처,
            "문서유형": "행정규칙",
            "구조유형": "계층형",

            "대분류": 대분류,
            "대분류_제목": 대분류_제목,
            "중분류": 중분류,
            "중분류_제목": 중분류_제목,
            "소분류": 소분류,
            "소분류_제목": 소분류_제목,

            "hierarchy_path": f"{hierarchy_path} > 도입",

            "text": text,
            "text_length": len(text),

            # 계층적 청킹 메타데이터
            "chunk_type": "자식_청크",
            "parent_chunk_id": parent_id,
            "자식_청크_ids": None,

            "is_indexed": True,  # 검색 대상!
            "has_embedding": True,  # 임베딩 생성!

            "is_example": False,
            "is_definition": True,  # 정의 청크

            "keywords": self._extract_keywords_from_title(소분류_제목),
            "metadata": {
                "created_at": datetime.now().isoformat()
            }
        }

    def _create_example_child(
        self,
        예시: Dict,
        parent_id: str,
        법령명: str, 법령번호: str, 시행일: str, 소관부처: str,
        대분류: str, 대분류_제목: str,
        중분류: str, 중분류_제목: str,
        소분류: str, 소분류_제목: str,
        hierarchy_path: str
    ) -> Dict:
        """예시 자식 청크 생성"""

        # 예시 ID 추출
        예시_type = None
        예시_id = None

        if "번호" in 예시:
            예시_type = "번호"
            예시_id = 예시["번호"]
        elif "기호" in 예시:
            예시_type = "기호"
            예시_id = 예시["기호"]

        # chunk_id 생성
        safe_예시_id = 예시_id.replace("(", "").replace(")", "") if 예시_id else "unknown"
        child_id = f"{법령명}_{대분류}_{중분류}_{소분류}_예시{safe_예시_id}"

        # 텍스트 구성
        예시_내용 = 예시.get("내용", "")
        text_parts = [f"{소분류}. {소분류_제목}\n"]

        if 예시_type == "번호":
            text_parts.append(f"\n<예시 {예시_id}>")
        elif 예시_type == "기호":
            text_parts.append(f"\n{예시_id}")

        text_parts.append(예시_내용)

        # 세부 (설명, 항목, 참고 등)
        세부 = 예시.get("세부", [])
        설명_text = self._format_세부(세부)
        if 설명_text:
            text_parts.append(f"\n{설명_text}")

        text = "\n".join(text_parts)

        # 메타데이터 추출
        has_explanation = self._has_explanation(세부)
        has_counterexample = self._has_counterexample(세부)
        has_reference = self._has_reference(세부)
        explanation_summary = self._extract_explanation_summary(세부)
        case_keywords = self._extract_case_keywords(예시_내용)
        판단결과 = self._extract_judgment(세부)
        판단근거 = self._extract_reasoning(세부)

        return {
            "chunk_id": child_id,
            "법령명": 법령명,
            "법령번호": 법령번호,
            "시행일": 시행일,
            "소관부처": 소관부처,
            "문서유형": "행정규칙",
            "구조유형": "계층형",

            "대분류": 대분류,
            "대분류_제목": 대분류_제목,
            "중분류": 중분류,
            "중분류_제목": 중분류_제목,
            "소분류": 소분류,
            "소분류_제목": 소분류_제목,

            "hierarchy_path": f"{hierarchy_path} > 예시 {예시_id}",

            "text": text,
            "text_length": len(text),

            # 계층적 청킹 메타데이터
            "chunk_type": "자식_청크",
            "parent_chunk_id": parent_id,
            "자식_청크_ids": None,

            "is_indexed": True,  # 검색 대상!
            "has_embedding": True,  # 임베딩 생성!

            # 예시 관련 메타데이터
            "is_example": True,
            "example_type": 예시_type,
            "example_id": 예시_id,

            "has_explanation": has_explanation,
            "has_counterexample": has_counterexample,
            "has_reference": has_reference,

            "explanation_summary": explanation_summary,
            "case_keywords": case_keywords,
            "판단결과": 판단결과,
            "판단근거": 판단근거,

            "keywords": case_keywords + self._extract_keywords_from_title(소분류_제목),
            "metadata": {
                "created_at": datetime.now().isoformat()
            }
        }

    def _create_single_chunk(
        self,
        소분류_item: Dict,
        법령명: str, 법령번호: str, 시행일: str, 소관부처: str,
        대분류: str, 대분류_제목: str,
        중분류: str, 중분류_제목: str,
        소분류: str, 소분류_제목: str
    ) -> Dict:
        """일반 청크 생성 (예시 없거나 1개 이하)"""

        chunk_id = f"{법령명}_{대분류}_{중분류}_{소분류}"
        text = self._build_full_section_text(소분류, 소분류_제목, 소분류_item.get("내용", []))
        hierarchy_path = f"{대분류}. {대분류_제목} > {중분류}. {중분류_제목} > {소분류}. {소분류_제목}"

        return {
            "chunk_id": chunk_id,
            "법령명": 법령명,
            "법령번호": 법령번호,
            "시행일": 시행일,
            "소관부처": 소관부처,
            "문서유형": "행정규칙",
            "구조유형": "계층형",

            "대분류": 대분류,
            "대분류_제목": 대분류_제목,
            "중분류": 중분류,
            "중분류_제목": 중분류_제목,
            "소분류": 소분류,
            "소분류_제목": 소분류_제목,

            "hierarchy_path": hierarchy_path,

            "text": text,
            "text_length": len(text),

            # 일반 청크 메타데이터
            "chunk_type": "자식_청크",  # 부모 없는 자식
            "parent_chunk_id": None,
            "자식_청크_ids": None,

            "is_indexed": True,  # 검색 대상
            "has_embedding": True,  # 임베딩 생성

            "is_example": False,

            "keywords": self._extract_keywords_from_title(소분류_제목),
            "metadata": {
                "created_at": datetime.now().isoformat()
            }
        }

    def _build_full_section_text(self, 소분류: str, 소분류_제목: str, 내용: List[Dict]) -> str:
        """소분류 전체 텍스트 구성 (부모 청크용)"""
        parts = [f"{소분류}. {소분류_제목}\n"]

        for item in 내용:
            if "본문" in item:
                parts.append(item["본문"])

            elif "구분" in item and "예시" in item.get("구분", ""):
                parts.append(f"\n<예시>")

            elif "번호" in item and item["번호"].startswith("("):
                # 예시
                예시_번호 = item["번호"]
                예시_내용 = item.get("내용", "")
                parts.append(f"\n<예시 {예시_번호}>")
                parts.append(예시_내용)

                # 세부 (설명 등)
                if "세부" in item:
                    parts.append(self._format_세부(item["세부"]))

            elif "기호" in item:
                # ㅇ 기호 예시
                기호 = item["기호"]
                내용_text = item.get("내용", "")
                parts.append(f"\n{기호} {내용_text}")

                if "세부" in item:
                    parts.append(self._format_세부(item["세부"]))

        return "\n".join(parts)

    def _format_세부(self, 세부: List[Dict], indent: int = 0) -> str:
        """세부 항목 포맷팅 (설명, 항목, 참고 등)"""
        lines = []
        prefix = "   " * indent

        for item in 세부:
            if "설명" in item:
                lines.append(f"{prefix}⇒ {item['설명']}")

            elif "항목" in item:
                lines.append(f"{prefix}• {item['항목']}")

            elif "참고" in item:
                lines.append(f"{prefix}※ {item['참고']}")

            # 중첩된 세부
            if "세부" in item:
                lines.append(self._format_세부(item["세부"], indent + 1))

        return "\n".join(lines)

    def _has_explanation(self, 세부: List[Dict]) -> bool:
        """설명(⇒) 포함 여부"""
        for item in 세부:
            if "설명" in item:
                return True
        return False

    def _has_counterexample(self, 세부: List[Dict]) -> bool:
        """반대 사례("반면에") 포함 여부"""
        for item in 세부:
            if "항목" in item and "반면" in item["항목"]:
                return True
        return False

    def _has_reference(self, 세부: List[Dict]) -> bool:
        """참고(※) 포함 여부"""
        for item in 세부:
            if "참고" in item:
                return True
        return False

    def _extract_explanation_summary(self, 세부: List[Dict]) -> str:
        """설명 요약 추출"""
        for item in 세부:
            if "설명" in item:
                설명 = item["설명"]
                # 첫 문장만 추출 (50자 제한)
                if len(설명) > 50:
                    return 설명[:50] + "..."
                return 설명
        return ""

    def _extract_case_keywords(self, text: str) -> List[str]:
        """사례 키워드 추출"""
        keywords = []

        # 1. 주체 패턴
        주체_패턴 = r'(소비자|사업자|판매자|판매원|통신판매업자|[A-Z][\w]*(?:사|은|는|가|이))'
        keywords.extend(re.findall(주체_패턴, text))

        # 2. 행위 패턴
        행위_패턴 = r'(방문|전화|구매|판매|체결|청약|계약|배송|반품|교환|철회)'
        keywords.extend(re.findall(행위_패턴, text))

        # 3. 장소/매체 패턴
        장소_패턴 = r'(사이버몰|인터넷|가정|사업장|상점|전화|카탈로그|우편|이메일)'
        keywords.extend(re.findall(장소_패턴, text))

        # 4. 특징 패턴
        특징_패턴 = r'(비대면|대면|직접|간접|사업장\s*외)'
        keywords.extend(re.findall(특징_패턴, text))

        # 중복 제거
        return list(set(keywords))

    def _extract_judgment(self, 세부: List[Dict]) -> str:
        """판단 결과 추출 ("~에 해당한다" / "~에 해당하지 않는다")"""
        for item in 세부:
            if "설명" in item:
                text = item["설명"]

                # "~에 해당한다" 패턴
                if "해당한다" in text and "해당하지" not in text:
                    match = re.search(r'(.+?)에?\s*해당한다', text)
                    if match:
                        return match.group(1).strip() + " 해당"

                # "~에 해당하지 않는다" 패턴
                elif "해당하지" in text or "해당되지" in text:
                    match = re.search(r'(.+?)에?\s*해당하지', text)
                    if match:
                        return match.group(1).strip() + " 해당 안 함"

        return ""

    def _extract_reasoning(self, 세부: List[Dict]) -> str:
        """판단 근거 추출"""
        for item in 세부:
            if "설명" in item:
                text = item["설명"]

                # "~이므로" 앞의 근거 추출
                match = re.search(r'(.+?)(?:이므로|므로)', text)
                if match:
                    근거 = match.group(1).strip()
                    # 불필요한 접두사 제거
                    근거 = re.sub(r'^이는\s*', '', 근거)
                    return 근거

        return ""

    def _extract_keywords_from_title(self, 제목: str) -> List[str]:
        """제목에서 키워드 추출"""
        # 따옴표 안의 용어 추출
        keywords = re.findall(r'"([^"]+)"', 제목)
        keywords.extend(re.findall(r'\'([^\']+)\'', 제목))

        # 주요 법률 용어
        patterns = [
            r'(청약철회|계약해제|손해배상|환급|교환|반품)',
            r'(통신판매|전자상거래|방문판매|전화권유판매)',
            r'(소비자|사업자|판매자)',
        ]

        for pattern in patterns:
            keywords.extend(re.findall(pattern, 제목))

        return list(set(keywords))

    def _chunk_article_based(
        self,
        본문: List[Dict],
        법령명: str, 법령번호: str, 시행일: str, 소관부처: str
    ) -> List[Dict]:
        """조문형 행정규칙 일반 청킹"""
        chunks = []

        for 조_item in 본문:
            조 = 조_item.get("조", "")
            제목 = 조_item.get("제목", "")
            내용 = 조_item.get("내용", [])

            # 조 단위로 청크 생성
            text = self._build_article_text(조, 제목, 내용)
            chunk_id = f"{법령명}_{조}"

            chunk = {
                "chunk_id": chunk_id,
                "법령명": 법령명,
                "법령번호": 법령번호,
                "시행일": 시행일,
                "소관부처": 소관부처,
                "문서유형": "행정규칙",
                "구조유형": "조문형",

                "조": 조,
                "조문제목": 제목,

                "hierarchy_path": f"{조} {제목}",

                "text": text,
                "text_length": len(text),

                # 일반 청크 메타데이터
                "chunk_type": "자식_청크",
                "parent_chunk_id": None,
                "자식_청크_ids": None,

                "is_indexed": True,
                "has_embedding": True,

                "is_example": False,

                "keywords": self._extract_keywords_from_title(제목),
                "metadata": {
                    "created_at": datetime.now().isoformat()
                }
            }

            chunks.append(chunk)

        return chunks

    def _build_article_text(self, 조: str, 제목: str, 내용: List[Dict]) -> str:
        """조문 텍스트 구성"""
        parts = [f"{조}({제목})\n"]

        for item in 내용:
            if "본문" in item:
                parts.append(item["본문"])

            elif "호" in item:
                호 = item["호"]
                호_내용 = item.get("내용", "")
                parts.append(f"{호}. {호_내용}")

                # 세부 (목 등)
                if "세부" in item:
                    parts.append(self._format_article_세부(item["세부"]))

        return "\n".join(parts)

    def _format_article_세부(self, 세부: List[Dict], indent: int = 1) -> str:
        """조문형 세부 포맷팅"""
        lines = []
        prefix = "   " * indent

        for item in 세부:
            if "목" in item:
                목 = item["목"]
                목_내용 = item.get("내용", "")
                lines.append(f"{prefix}{목}. {목_내용}")

            # 중첩된 세부
            if "세부" in item:
                lines.append(self._format_article_세부(item["세부"], indent + 1))

        return "\n".join(lines)

    def save_chunks(self, output_path: str = "chunks_guide_1.json"):
        """청크를 JSON 파일로 저장"""
        output_file = Path(output_path)

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.chunks, f, ensure_ascii=False, indent=2)

        print(f"\n청크 저장 완료: {output_file}")
        print(f"총 {len(self.chunks)}개 청크")

        # 통계 출력
        self._print_statistics()

    def save_chunks_jsonl(self, output_path: str = "chunks_guide_1.jsonl"):
        """청크를 JSONL(JSON Lines) 파일로 저장"""
        output_file = Path(output_path)

        with open(output_file, 'w', encoding='utf-8') as f:
            for chunk in self.chunks:
                json_line = json.dumps(chunk, ensure_ascii=False)
                f.write(json_line + '\n')

        print(f"\nJSONL 청크 저장 완료: {output_file}")
        print(f"총 {len(self.chunks)}개 청크 (라인 단위)")

        # 파일 크기 비교
        json_path = Path(output_path.replace('.jsonl', '.json'))
        if json_path.exists():
            json_size = json_path.stat().st_size
            jsonl_size = output_file.stat().st_size

            print(f"\n파일 크기 비교:")
            print(f"  JSON:  {json_size:,} bytes")
            print(f"  JSONL: {jsonl_size:,} bytes")
            print(f"  차이:  {jsonl_size - json_size:+,} bytes ({(jsonl_size/json_size - 1)*100:+.1f}%)")

    def _print_statistics(self):
        """청킹 통계 출력"""
        if not self.chunks:
            print("\n경고: 생성된 청크가 없습니다.")
            return

        print("\n=== 청킹 통계 ===")

        # 청크 유형별 개수
        chunk_types = {"부모_청크": 0, "자식_청크": 0}
        for chunk in self.chunks:
            ct = chunk["chunk_type"]
            chunk_types[ct] = chunk_types.get(ct, 0) + 1

        print(f"청크 유형별:")
        print(f"  부모_청크: {chunk_types['부모_청크']}개")
        print(f"  자식_청크: {chunk_types['자식_청크']}개")

        # 검색 대상 청크
        indexed_count = sum(1 for c in self.chunks if c.get("is_indexed", False))
        print(f"\n검색 대상 (임베딩 생성): {indexed_count}개")
        print(f"검색 제외 (부모 청크): {len(self.chunks) - indexed_count}개")

        # 예시 청크
        example_count = sum(1 for c in self.chunks if c.get("is_example", False))
        print(f"\n예시 청크: {example_count}개")

        # 법령별 개수
        law_counts = {}
        for chunk in self.chunks:
            law = chunk["법령명"]
            law_counts[law] = law_counts.get(law, 0) + 1

        print(f"\n법령별 청크 개수:")
        for law, count in sorted(law_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {law}: {count}개")

        # 평균 청크 크기
        avg_length = sum(c["text_length"] for c in self.chunks) / len(self.chunks)
        print(f"\n평균 청크 크기: {avg_length:.0f}자")


def main():
    """메인 실행 함수"""
    print("=" * 60)
    print("행정규칙 계층적 청킹 스크립트")
    print("=" * 60)

    # 청킹 실행
    chunker = GuideChunker(guide_dir="01_parsed/02_Guide")
    chunks = chunker.process_all_guides()

    # 결과 저장 (JSON 및 JSONL 모두)
    chunker.save_chunks("02_chunked/chunks_guide_1.json")
    chunker.save_chunks_jsonl("02_chunked/chunks_guide_1.jsonl")

    print("\n완료!")


if __name__ == "__main__":
    main()
