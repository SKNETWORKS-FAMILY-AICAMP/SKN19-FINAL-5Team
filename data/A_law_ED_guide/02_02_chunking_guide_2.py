"""
소비자분쟁해결기준 별표 청킹 스크립트 (계층적 청킹)

전략:
- 별표1: 단순 매핑 청크 (품목 → 카테고리)
- 별표2: 계층적 청킹 (부모-자식-손자 구조)
  * 부모 청크: 전체 dispute_type (임베딩 X)
  * 자식/손자 청크: 개별 조건 (임베딩 O)
- 별표3/4: 품목별 단순 청크
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime


class DisputeResolutionChunker:
    """소비자분쟁해결기준 별표 청킹 클래스"""

    def __init__(self, input_dir: Path, output_dir: Path):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 통계
        self.stats = {
            "별표1": {"total": 0},
            "별표2_1": {"부모": 0, "자식": 0, "손자": 0},
            "별표2_2": {"부모": 0, "자식": 0, "손자": 0},
            "별표3": {"total": 0},
            "별표4": {"total": 0}
        }

    def run(self):
        """전체 청킹 프로세스 실행"""
        print("=" * 60)
        print("소비자분쟁해결기준 별표 청킹 시작")
        print("=" * 60)

        all_chunks = []

        # 1. 별표1 청킹
        print("\n[1/5] 별표1 - 대상품목 청킹 중...")
        chunks_1 = self.chunk_별표1()
        all_chunks.extend(chunks_1)
        print(f"  [OK] 완료: {len(chunks_1)}개 청크 생성")

        # 2. 별표2-1 청킹 (상품/재화)
        print("\n[2/5] 별표2-1 - 품목별 해결기준 1 (상품/재화) 청킹 중...")
        chunks_2_1 = self.chunk_별표2("[별표 2] 품목별 해결기준 1.json", "별표2_1")
        all_chunks.extend(chunks_2_1)
        stats_2_1 = self.stats["별표2_1"]
        print(f"  [OK] 완료: 부모 {stats_2_1['부모']}개, 자식 {stats_2_1['자식']}개, 손자 {stats_2_1['손자']}개")

        # 3. 별표2-2 청킹 (서비스업)
        print("\n[3/5] 별표2-2 - 품목별 해결기준 2 (서비스업) 청킹 중...")
        chunks_2_2 = self.chunk_별표2("[별표 2] 품목별 해결기준 2.json", "별표2_2")
        all_chunks.extend(chunks_2_2)
        stats_2_2 = self.stats["별표2_2"]
        print(f"  [OK] 완료: 부모 {stats_2_2['부모']}개, 자식 {stats_2_2['자식']}개, 손자 {stats_2_2['손자']}개")

        # 4. 별표3 청킹
        print("\n[4/5] 별표3 - 품질보증기간 및 부품보유기간 청킹 중...")
        chunks_3 = self.chunk_별표3()
        all_chunks.extend(chunks_3)
        print(f"  [OK] 완료: {len(chunks_3)}개 청크 생성")

        # 5. 별표4 청킹
        print("\n[5/5] 별표4 - 품목별 내용연수표 청킹 중...")
        chunks_4 = self.chunk_별표4()
        all_chunks.extend(chunks_4)
        print(f"  [OK] 완료: {len(chunks_4)}개 청크 생성")

        # 결과 저장
        self.save_chunks(all_chunks)

        # 통계 출력
        self.print_statistics()

        print("\n" + "=" * 60)
        print("청킹 완료!")
        print("=" * 60)

    # ========================================
    # 별표1: 대상품목 청킹
    # ========================================

    def chunk_별표1(self) -> List[Dict]:
        """
        별표1 - 대상품목 청킹 (단순 매핑)

        역할: 품목 키워드 → 카테고리/소분류 매핑
        임베딩: [OK] (품목명 검색용)
        """
        file_path = self.input_dir / "[별표 1] 대상품목.json"
        data = json.load(open(file_path, 'r', encoding='utf-8'))

        chunks = []

        for section in data.get("sections", []):
            section_id = section.get("section_id", "")
            section_name = section.get("section_name", "")

            for category in section.get("categories", []):
                category_number = category.get("category_number", 0)
                category_name = category.get("category_name", "")

                for subcategory in category.get("subcategories", []):
                    subcategory_name = subcategory.get("subcategory_name", "")
                    items = subcategory.get("items", [])

                    # 청크 생성
                    chunk_id = f"별표1_{section_id}_{category_number}_{self._clean_name(subcategory_name)}"

                    # 텍스트 구성 (품목명 검색용)
                    item_str = ", ".join(items) if items else ""
                    text = f"【카테고리】{category_name}\n【소분류】{subcategory_name}\n【품목】{item_str}"

                    chunk = {
                        "chunk_id": chunk_id,
                        "chunk_type": "별표1_품목매핑",
                        "parent_chunk_id": None,
                        "is_indexed": True,  # 임베딩 대상
                        "has_embedding": False,  # 아직 임베딩 안 됨

                        "document_type": "소비자분쟁해결기준_별표1",
                        "section_id": section_id,
                        "section_name": section_name,
                        "category_number": category_number,
                        "category_name": category_name,
                        "subcategory_name": subcategory_name,
                        "items": items,

                        "text": text,

                        "created_at": datetime.now().isoformat()
                    }

                    chunks.append(chunk)
                    self.stats["별표1"]["total"] += 1

        return chunks

    # ========================================
    # 별표2: 품목별 해결기준 (계층적 청킹) ⭐
    # ========================================

    def chunk_별표2(self, filename: str, table_id: str) -> List[Dict]:
        """
        별표2 - 품목별 해결기준 청킹 (계층적)

        전략:
        - 부모 청크: dispute_type 전체 (임베딩 X)
        - 자식 청크: 1차 조건 (임베딩 O)
        - 손자 청크: 2차 조건 (임베딩 O)
        """
        file_path = self.input_dir / filename
        data = json.load(open(file_path, 'r', encoding='utf-8'))

        chunks = []

        for entry in data.get("data", []):
            대분류 = entry.get("대분류", "")
            중분류 = entry.get("중분류", "")
            소분류 = entry.get("소분류", "")
            reference = entry.get("reference", {})

            for item in entry.get("items", []):
                dispute_id = item.get("id", "")
                dispute_type = item.get("dispute_type", "")
                conditions = item.get("conditions", [])

                # 조건이 2개 이상이면 계층적 청킹
                if len(conditions) >= 2:
                    parent, children = self._create_hierarchical_chunks(
                        table_id, entry, item
                    )
                    chunks.append(parent)
                    chunks.extend(children)
                else:
                    # 조건이 0~1개면 단순 청크
                    chunk = self._create_simple_dispute_chunk(
                        table_id, entry, item
                    )
                    chunks.append(chunk)

        return chunks

    def _create_hierarchical_chunks(
        self, table_id: str, entry: Dict, item: Dict
    ) -> Tuple[Dict, List[Dict]]:
        """계층적 청킹: 부모 1개 + 자식 N개 + 손자 M개"""

        대분류 = entry.get("대분류", "")
        중분류 = entry.get("중분류", "")
        소분류 = entry.get("소분류", "")
        dispute_id = item.get("id", "")
        dispute_type = item.get("dispute_type", "")
        conditions = item.get("conditions", [])
        notes = item.get("notes", [])
        reference = entry.get("reference", {})

        # 1. 부모 청크 생성
        parent_id = (
            f"{table_id}_{self._clean_name(대분류)}_"
            f"{self._clean_name(중분류)}_{self._clean_name(소분류)}_"
            f"dispute{dispute_id}_부모"
        )

        parent_text = self._build_full_dispute_text(item)

        parent_chunk = {
            "chunk_id": parent_id,
            "chunk_type": "부모_청크",
            "parent_chunk_id": None,
            "is_indexed": False,  # 임베딩 안 함
            "has_embedding": False,

            "document_type": f"소비자분쟁해결기준_{table_id}",
            "대분류": 대분류,
            "중분류": 중분류,
            "소분류": 소분류,
            "dispute_id": dispute_id,
            "dispute_type": dispute_type,
            "reference": reference,

            "text": parent_text,
            "자식_청크_ids": [],

            "created_at": datetime.now().isoformat()
        }

        # 2. 자식/손자 청크 생성
        children = []

        for idx, condition_obj in enumerate(conditions, 1):
            # 2-1. 자식 청크 (1차 조건)
            child = self._create_condition_child(
                table_id=table_id,
                parent_id=parent_id,
                entry=entry,
                item=item,
                condition_obj=condition_obj,
                condition_level=1,
                condition_idx=idx
            )
            children.append(child)

            # 2-2. 손자 청크 (2차 조건)
            sub_conditions = condition_obj.get("sub_conditions", [])
            if sub_conditions:
                for sub_idx, sub_cond_obj in enumerate(sub_conditions, 1):
                    grandchild = self._create_condition_child(
                        table_id=table_id,
                        parent_id=parent_id,
                        entry=entry,
                        item=item,
                        condition_obj=sub_cond_obj,
                        condition_level=2,
                        condition_idx=idx,
                        sub_condition_idx=sub_idx,
                        parent_condition=condition_obj.get("condition", "")
                    )
                    children.append(grandchild)

        # 3. 부모에 자식 ID 연결
        parent_chunk["자식_청크_ids"] = [c["chunk_id"] for c in children]

        # 통계
        self.stats[table_id]["부모"] += 1
        for child in children:
            if child["chunk_type"] == "자식_청크":
                self.stats[table_id]["자식"] += 1
            elif child["chunk_type"] == "손자_청크":
                self.stats[table_id]["손자"] += 1

        return parent_chunk, children

    def _create_simple_dispute_chunk(
        self, table_id: str, entry: Dict, item: Dict
    ) -> Dict:
        """단순 dispute 청크 (조건 0~1개)"""

        대분류 = entry.get("대분류", "")
        중분류 = entry.get("중분류", "")
        소분류 = entry.get("소분류", "")
        dispute_id = item.get("id", "")
        dispute_type = item.get("dispute_type", "")
        resolution = item.get("resolution", "")
        conditions = item.get("conditions", [])
        notes = item.get("notes", [])
        reference = entry.get("reference", {})

        chunk_id = (
            f"{table_id}_{self._clean_name(대분류)}_"
            f"{self._clean_name(중분류)}_{self._clean_name(소분류)}_"
            f"dispute{dispute_id}_단순"
        )

        # 텍스트 구성
        text_parts = [f"【분쟁 유형】{dispute_type}"]

        if resolution:
            text_parts.append(f"\n→ {resolution}")

        if conditions and len(conditions) == 1:
            cond = conditions[0]
            text_parts.append(f"\n\n【조건】{cond.get('condition', '')}")
            text_parts.append(f"→ {cond.get('resolution', '')}")

            for note in cond.get("notes", []):
                text_parts.append(f"\n* {note.get('content', '')}")

        for note in notes:
            text_parts.append(f"\n* {note.get('content', '')}")

        text = "".join(text_parts)

        chunk = {
            "chunk_id": chunk_id,
            "chunk_type": "자식_청크",  # 임베딩 대상
            "parent_chunk_id": None,
            "is_indexed": True,
            "has_embedding": False,

            "document_type": f"소비자분쟁해결기준_{table_id}",
            "대분류": 대분류,
            "중분류": 중분류,
            "소분류": 소분류,
            "dispute_id": dispute_id,
            "dispute_type": dispute_type,
            "reference": reference,

            "text": text,

            "created_at": datetime.now().isoformat()
        }

        # 통계
        self.stats[table_id]["자식"] += 1

        return chunk

    def _create_condition_child(
        self,
        table_id: str,
        parent_id: str,
        entry: Dict,
        item: Dict,
        condition_obj: Dict,
        condition_level: int,
        condition_idx: int,
        sub_condition_idx: Optional[int] = None,
        parent_condition: str = ""
    ) -> Dict:
        """자식/손자 청크 생성"""

        대분류 = entry.get("대분류", "")
        중분류 = entry.get("중분류", "")
        소분류 = entry.get("소분류", "")
        dispute_id = item.get("id", "")
        dispute_type = item.get("dispute_type", "")
        reference = entry.get("reference", {})

        condition = condition_obj.get("condition", "")
        resolution = condition_obj.get("resolution", "")
        notes = condition_obj.get("notes", [])

        # chunk_id 생성
        if condition_level == 1:
            chunk_id = (
                f"{table_id}_{self._clean_name(대분류)}_"
                f"{self._clean_name(중분류)}_{self._clean_name(소분류)}_"
                f"dispute{dispute_id}_조건{condition_idx}"
            )
            chunk_type = "자식_청크"
        else:  # level 2
            chunk_id = (
                f"{table_id}_{self._clean_name(대분류)}_"
                f"{self._clean_name(중분류)}_{self._clean_name(소분류)}_"
                f"dispute{dispute_id}_조건{condition_idx}_하위{sub_condition_idx}"
            )
            chunk_type = "손자_청크"

        # 텍스트 구성
        text_parts = [
            f"【분쟁 유형】{dispute_type}\n"
        ]

        if condition_level == 2 and parent_condition:
            text_parts.append(f"\n【상위 조건】{parent_condition}")

        text_parts.append(f"\n【조건】{condition}")
        text_parts.append(f"\n→ {resolution}")

        for note in notes:
            text_parts.append(f"\n\n* {note.get('content', '')}")

        text = "".join(text_parts)

        chunk = {
            "chunk_id": chunk_id,
            "chunk_type": chunk_type,
            "parent_chunk_id": parent_id,
            "is_indexed": True,  # 임베딩 대상
            "has_embedding": False,

            "document_type": f"소비자분쟁해결기준_{table_id}",
            "대분류": 대분류,
            "중분류": 중분류,
            "소분류": 소분류,
            "dispute_id": dispute_id,
            "dispute_type": dispute_type,
            "reference": reference,

            "condition_level": condition_level,
            "condition": condition,
            "resolution": resolution,

            "text": text,

            "created_at": datetime.now().isoformat()
        }

        return chunk

    def _build_full_dispute_text(self, item: Dict) -> str:
        """부모 청크용 전체 텍스트 구성"""

        dispute_type = item.get("dispute_type", "")
        resolution = item.get("resolution", "")
        conditions = item.get("conditions", [])
        notes = item.get("notes", [])

        parts = [f"【분쟁 유형】{dispute_type}"]

        if resolution:
            parts.append(f"\n\n→ {resolution}")

        # 조건들
        for idx, cond in enumerate(conditions, 1):
            parts.append(f"\n\n【조건 {idx}】{cond.get('condition', '')}")
            parts.append(f"\n→ {cond.get('resolution', '')}")

            # 하위 조건
            sub_conditions = cond.get("sub_conditions", [])
            if sub_conditions:
                for sub_idx, sub_cond in enumerate(sub_conditions, 1):
                    parts.append(f"\n  【하위 조건 {idx}-{sub_idx}】{sub_cond.get('condition', '')}")
                    parts.append(f"\n  → {sub_cond.get('resolution', '')}")

                    # 하위 조건 notes
                    for note in sub_cond.get("notes", []):
                        parts.append(f"\n  * {note.get('content', '')}")

            # 조건별 notes
            for note in cond.get("notes", []):
                parts.append(f"\n* {note.get('content', '')}")

        # 전체 notes
        if notes:
            parts.append("\n\n【주의사항】")
            for note in notes:
                parts.append(f"\n* {note.get('content', '')}")

        return "".join(parts)

    # ========================================
    # 별표3: 품질보증기간 및 부품보유기간
    # ========================================

    def chunk_별표3(self) -> List[Dict]:
        """
        별표3 - 품질보증기간 및 부품보유기간 청킹 (단순)

        역할: 품목별 보증기간 정보
        임베딩: [OK] (품목명 검색용)
        """
        file_path = self.input_dir / "[별표 3] 품목별 품질보증기간 및 부품보유기간.json"
        data = json.load(open(file_path, 'r', encoding='utf-8'))

        chunks = []

        for idx, entry in enumerate(data.get("data", []), 1):
            품목 = entry.get("품목", "")
            하위1 = entry.get("하위카테고리1", "")
            하위2 = entry.get("하위카테고리2", "")
            품질보증 = entry.get("품질보증기간", [])
            부품보유 = entry.get("부품보유기간", [])

            chunk_id = f"별표3_{idx}_{self._clean_name(품목)}"

            # 텍스트 구성
            text_parts = [f"【품목】{품목}"]

            if 하위1:
                text_parts.append(f"\n【하위 카테고리 1】{하위1}")
            if 하위2:
                text_parts.append(f"\n【하위 카테고리 2】{하위2}")

            # 품질보증기간
            if 품질보증:
                text_parts.append("\n\n【품질보증기간】")
                for item in 품질보증:
                    text_parts.append(f"\n{item.get('notes', '')}")
                    for sub in item.get("sub_notes", []):
                        text_parts.append(f"\n  - {sub.get('content', '')}")

            # 부품보유기간
            if 부품보유:
                text_parts.append("\n\n【부품보유기간】")
                for item in 부품보유:
                    text_parts.append(f"\n{item.get('notes', '')}")
                    for sub in item.get("sub_notes", []):
                        text_parts.append(f"\n  - {sub.get('content', '')}")

            text = "".join(text_parts)

            chunk = {
                "chunk_id": chunk_id,
                "chunk_type": "별표3_품질보증",
                "parent_chunk_id": None,
                "is_indexed": True,  # 임베딩 대상
                "has_embedding": False,

                "document_type": "소비자분쟁해결기준_별표3",
                "품목": 품목,
                "하위카테고리1": 하위1,
                "하위카테고리2": 하위2,

                "text": text,

                "created_at": datetime.now().isoformat()
            }

            chunks.append(chunk)
            self.stats["별표3"]["total"] += 1

        return chunks

    # ========================================
    # 별표4: 품목별 내용연수표
    # ========================================

    def chunk_별표4(self) -> List[Dict]:
        """
        별표4 - 품목별 내용연수표 청킹 (단순)

        역할: 품목별 내용연수 정보
        임베딩: [OK] (품목명 검색용)
        """
        file_path = self.input_dir / "[별표 4] 품목별 내용연수표.json"
        data = json.load(open(file_path, 'r', encoding='utf-8'))

        chunks = []

        for idx, entry in enumerate(data.get("data", []), 1):
            품목 = entry.get("품목", "")
            내용연수 = entry.get("내용연수", "")

            chunk_id = f"별표4_{idx}_{self._clean_name(품목)}"

            # 텍스트 구성
            text = f"【품목】{품목}\n\n【내용연수】\n{내용연수}"

            chunk = {
                "chunk_id": chunk_id,
                "chunk_type": "별표4_내용연수",
                "parent_chunk_id": None,
                "is_indexed": True,  # 임베딩 대상
                "has_embedding": False,

                "document_type": "소비자분쟁해결기준_별표4",
                "품목": 품목,
                "내용연수": 내용연수,

                "text": text,

                "created_at": datetime.now().isoformat()
            }

            chunks.append(chunk)
            self.stats["별표4"]["total"] += 1

        return chunks

    # ========================================
    # 유틸리티 함수
    # ========================================

    def _clean_name(self, name: str) -> str:
        """chunk_id용 이름 정제 (특수문자 제거)"""
        # 로마 숫자 변환
        name = name.replace("Ⅰ", "I").replace("Ⅱ", "II").replace("Ⅲ", "III")
        name = name.replace("Ⅳ", "IV").replace("Ⅴ", "V")

        # 특수문자 제거 (한글, 영문, 숫자만 유지)
        name = re.sub(r'[^\w가-힣]', '', name)

        # 길이 제한 (너무 길면 잘라내기)
        if len(name) > 30:
            name = name[:30]

        return name

    def save_chunks(self, chunks: List[Dict]):
        """청크 저장 (JSON, JSONL)"""

        # JSON 파일 (전체) - chunks_guide_2로 네이밍
        json_path = self.output_dir / "chunks_guide_2.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(chunks, f, ensure_ascii=False, indent=2)
        print(f"\n[SAVE] JSON 저장: {json_path}")

        # JSONL 파일 (한 줄씩) - chunks_guide_2로 네이밍
        jsonl_path = self.output_dir / "chunks_guide_2.jsonl"
        with open(jsonl_path, 'w', encoding='utf-8') as f:
            for chunk in chunks:
                f.write(json.dumps(chunk, ensure_ascii=False) + '\n')
        print(f"[SAVE] JSONL 저장: {jsonl_path}")
        print(f"[SAVE] 총 {len(chunks)}개 청크 저장 완료")

    def print_statistics(self):
        """통계 출력"""
        print("\n" + "=" * 60)
        print("청킹 통계")
        print("=" * 60)

        total_chunks = 0
        total_indexed = 0

        print(f"\n별표1 (대상품목):")
        print(f"  - 총 청크: {self.stats['별표1']['total']}개")
        print(f"  - 임베딩 대상: {self.stats['별표1']['total']}개")
        total_chunks += self.stats['별표1']['total']
        total_indexed += self.stats['별표1']['total']

        for table in ["별표2_1", "별표2_2"]:
            table_name = "별표2-1 (상품/재화)" if table == "별표2_1" else "별표2-2 (서비스업)"
            stats = self.stats[table]
            total = stats['부모'] + stats['자식'] + stats['손자']
            indexed = stats['자식'] + stats['손자']

            print(f"\n{table_name}:")
            print(f"  - 부모 청크: {stats['부모']}개 (임베딩 안 함)")
            print(f"  - 자식 청크: {stats['자식']}개 (임베딩 대상)")
            print(f"  - 손자 청크: {stats['손자']}개 (임베딩 대상)")
            print(f"  - 총 청크: {total}개")
            print(f"  - 임베딩 대상: {indexed}개")
            total_chunks += total
            total_indexed += indexed

        print(f"\n별표3 (품질보증기간):")
        print(f"  - 총 청크: {self.stats['별표3']['total']}개")
        print(f"  - 임베딩 대상: {self.stats['별표3']['total']}개")
        total_chunks += self.stats['별표3']['total']
        total_indexed += self.stats['별표3']['total']

        print(f"\n별표4 (내용연수표):")
        print(f"  - 총 청크: {self.stats['별표4']['total']}개")
        print(f"  - 임베딩 대상: {self.stats['별표4']['total']}개")
        total_chunks += self.stats['별표4']['total']
        total_indexed += self.stats['별표4']['total']

        print(f"\n" + "-" * 60)
        print(f"전체 총계:")
        print(f"  - 총 청크: {total_chunks}개")
        print(f"  - 임베딩 대상: {total_indexed}개")
        print(f"  - 임베딩 비율: {total_indexed/total_chunks*100:.1f}%")


def main():
    """메인 실행 함수"""

    # 경로 설정
    input_dir = Path(r"C:\Users\Playdata\Desktop\project\05_5th_project\data_n_db\01_parsed\02_Guide\소비자분쟁해결기준_별표")
    output_dir = Path(r"C:\Users\Playdata\Desktop\project\05_5th_project\data_n_db\02_chunked")

    # 청킹 실행
    chunker = DisputeResolutionChunker(input_dir, output_dir)
    chunker.run()


if __name__ == "__main__":
    main()
