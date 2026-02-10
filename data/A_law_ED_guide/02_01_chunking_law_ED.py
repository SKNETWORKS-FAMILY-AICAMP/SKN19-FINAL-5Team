"""
법률 및 시행령 청킹 스크립트
- 대상: 01_parsed/01_law_ED/*.json (법률 11개, 시행령 8개)
- 청킹 유형: 조_전체, 항_분할, 호_분할
- 전략: 메타데이터 인식 청킹 + 도입 본문 포함
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime


class LawChunker:
    """법률/시행령 청킹 클래스"""

    def __init__(self, law_dir: str = "01_parsed/01_law_ED"):
        self.law_dir = Path(law_dir)
        self.chunks = []

    def process_all_laws(self) -> List[Dict]:
        """모든 법률 파일 처리"""
        json_files = list(self.law_dir.glob("*.json"))

        print(f"총 {len(json_files)}개 파일 발견")

        for json_file in json_files:
            if json_file.name in ["01_법률_URL.txt", "02_시행령_URL.txt", "구조.md"]:
                continue

            print(f"\n처리 중: {json_file.name}")
            law_chunks = self.chunk_law_file(json_file)
            self.chunks.extend(law_chunks)
            print(f"  → {len(law_chunks)}개 청크 생성")

        print(f"\n총 {len(self.chunks)}개 청크 생성 완료")
        return self.chunks

    def chunk_law_file(self, file_path: Path) -> List[Dict]:
        """단일 법률 파일 청킹"""
        with open(file_path, 'r', encoding='utf-8') as f:
            law_data = json.load(f)

        법령명 = law_data["법령명"]
        법령번호 = law_data["법령번호"]
        시행일 = law_data["시행일"]

        # 법령 유형 판단
        법령유형 = "시행령" if "시행령" in 법령명 or "대통령령" in 법령번호 else "법률"
        모법 = 법령명.replace(" 시행령", "") if 법령유형 == "시행령" else None

        chunks = []

        # 구조가 있는 경우 (편/장/절)
        if "구조" in law_data and law_data["구조"]:
            chunks = self._process_structure(
                law_data["구조"],
                법령명, 법령번호, 시행일, 법령유형, 모법
            )
        # 단순 조문 구조
        elif "조문" in law_data and law_data["조문"]:
            chunks = self._process_articles(
                law_data["조문"],
                법령명, 법령번호, 시행일, 법령유형, 모법,
                hierarchy={}, path=[]
            )

        return chunks

    def _process_structure(
        self,
        structure: List[Dict],
        법령명: str, 법령번호: str, 시행일: str, 법령유형: str, 모법: Optional[str]
    ) -> List[Dict]:
        """편/장/절 구조 순회"""
        chunks = []

        for item in structure:
            제목 = item.get("제목", "")

            # 편 단위
            if "편" in 제목 or item == structure[0]:  # 첫 번째 항목은 편일 가능성
                편 = 제목 if "편" in 제목 else None

                # 편 내 장 처리
                if "장" in item:
                    for 장_item in item["장"]:
                        chunks.extend(
                            self._process_장(
                                장_item, 법령명, 법령번호, 시행일, 법령유형, 모법,
                                편=편
                            )
                        )

            # 장 단위 (편 없이 바로 장)
            elif "장" in 제목 or "조문" in item:
                chunks.extend(
                    self._process_장(
                        item, 법령명, 법령번호, 시행일, 법령유형, 모법,
                        편=None
                    )
                )

        return chunks

    def _process_장(
        self,
        장_item: Dict,
        법령명: str, 법령번호: str, 시행일: str, 법령유형: str, 모법: Optional[str],
        편: Optional[str]
    ) -> List[Dict]:
        """장 단위 처리"""
        chunks = []
        장 = 장_item.get("제목", "")

        # 절이 있는 경우
        if "절" in 장_item:
            for 절_item in 장_item["절"]:
                절 = 절_item.get("제목", "")

                # 관이 있는 경우 (매우 드묾)
                if "관" in 절_item:
                    for 관_item in 절_item["관"]:
                        관 = 관_item.get("제목", "")
                        조문들 = 관_item.get("조문", [])

                        hierarchy = {"편": 편, "장": 장, "절": 절, "관": 관}
                        path = [x for x in [편, 장, 절, 관] if x]

                        chunks.extend(
                            self._process_articles(
                                조문들, 법령명, 법령번호, 시행일, 법령유형, 모법,
                                hierarchy, path
                            )
                        )
                else:
                    조문들 = 절_item.get("조문", [])
                    hierarchy = {"편": 편, "장": 장, "절": 절, "관": None}
                    path = [x for x in [편, 장, 절] if x]

                    chunks.extend(
                        self._process_articles(
                            조문들, 법령명, 법령번호, 시행일, 법령유형, 모법,
                            hierarchy, path
                        )
                    )

        # 절 없이 조문만 있는 경우
        elif "조문" in 장_item:
            조문들 = 장_item["조문"]
            hierarchy = {"편": 편, "장": 장, "절": None, "관": None}
            path = [x for x in [편, 장] if x]

            chunks.extend(
                self._process_articles(
                    조문들, 법령명, 법령번호, 시행일, 법령유형, 모법,
                    hierarchy, path
                )
            )

        return chunks

    def _process_articles(
        self,
        조문들: List[Dict],
        법령명: str, 법령번호: str, 시행일: str, 법령유형: str, 모법: Optional[str],
        hierarchy: Dict, path: List[str]
    ) -> List[Dict]:
        """조문 배열 처리"""
        chunks = []

        for 조문 in 조문들:
            조문번호 = 조문["조문번호"]
            조문제목 = 조문.get("조문제목", "")
            내용 = 조문["내용"]

            # 청크 유형 결정
            chunk_type = self._determine_chunk_type(조문번호, 조문제목, 내용)

            # 청크 생성
            if chunk_type == "조_전체":
                chunk = self._create_조_전체_chunk(
                    조문번호, 조문제목, 내용,
                    법령명, 법령번호, 시행일, 법령유형, 모법,
                    hierarchy, path
                )
                chunks.append(chunk)

            elif chunk_type == "항_분할":
                항_chunks = self._split_by_항(
                    조문번호, 조문제목, 내용,
                    법령명, 법령번호, 시행일, 법령유형, 모법,
                    hierarchy, path
                )
                chunks.extend(항_chunks)

            elif chunk_type == "호_분할":
                호_chunks = self._split_by_호(
                    조문번호, 조문제목, 내용,
                    법령명, 법령번호, 시행일, 법령유형, 모법,
                    hierarchy, path
                )
                chunks.extend(호_chunks)

        return chunks

    def _determine_chunk_type(self, 조문번호: str, 조문제목: str, 내용: List[Dict]) -> str:
        """청크 유형 결정"""
        # 조문 텍스트 생성
        full_text = self._build_article_text(조문번호, 조문제목, 내용)
        조문_길이 = len(full_text)

        # 1순위: 짧은 조문 → 조_전체
        if 조문_길이 < 500:
            return "조_전체"

        # 2순위: 호 분할 (조 다음 바로 호가 나오는 경우)
        if self._has_직접_호(내용):
            호_개수 = self._count_호(내용)
            if 호_개수 >= 3:
                return "호_분할"

        # 3순위: 항 분할 (긴 조문 + 항 존재)
        if 조문_길이 >= 1000 and self._has_항(내용):
            return "항_분할"

        # 기본값: 조_전체
        return "조_전체"

    def _has_직접_호(self, 내용: List[Dict]) -> bool:
        """조 다음에 항 없이 바로 호가 나오는지 확인"""
        for item in 내용:
            if "본문" in item:
                continue
            # 항이 아닌 호가 먼저 나오면 True
            if "호" in item and "항번호" not in item:
                return True
            # 항이 먼저 나오면 False
            if "항번호" in item:
                return False
        return False

    def _count_호(self, 내용: List[Dict]) -> int:
        """호의 개수 세기"""
        count = 0
        for item in 내용:
            if "호" in item and "항번호" not in item:
                count += 1
            # 항 안의 세부에 있는 호도 카운트
            elif "항번호" in item and "세부" in item:
                count += self._count_호_in_세부(item["세부"])
        return count

    def _count_호_in_세부(self, 세부: List[Dict]) -> int:
        """세부 내 호 개수 세기"""
        count = 0
        for item in 세부:
            if "호" in item:
                count += 1
        return count

    def _has_항(self, 내용: List[Dict]) -> bool:
        """항이 있는지 확인"""
        for item in 내용:
            if "항번호" in item:
                return True
        return False

    def _create_조_전체_chunk(
        self,
        조문번호: str, 조문제목: str, 내용: List[Dict],
        법령명: str, 법령번호: str, 시행일: str, 법령유형: str, 모법: Optional[str],
        hierarchy: Dict, path: List[str]
    ) -> Dict:
        """조 전체를 하나의 청크로 생성"""
        text = self._build_article_text(조문번호, 조문제목, 내용)

        return self._create_chunk(
            chunk_type="조_전체",
            법령명=법령명,
            법령번호=법령번호,
            시행일=시행일,
            법령유형=법령유형,
            모법=모법,
            hierarchy=hierarchy,
            path=path,
            조문번호=조문번호,
            조문제목=조문제목,
            text=text,
            항번호=None,
            호번호=None,
            원문_조문=조문번호
        )

    def _split_by_항(
        self,
        조문번호: str, 조문제목: str, 내용: List[Dict],
        법령명: str, 법령번호: str, 시행일: str, 법령유형: str, 모법: Optional[str],
        hierarchy: Dict, path: List[str]
    ) -> List[Dict]:
        """항 단위로 청크 분할"""
        chunks = []

        # 도입 본문 (조문번호 + 제목 + 본문들)
        도입_부분 = [f"{조문번호}({조문제목})"]

        for item in 내용:
            if "본문" in item:
                도입_부분.append(item["본문"])
            elif "항번호" in item:
                항번호 = item["항번호"]
                항_내용 = item["내용"]

                # 항 텍스트 구성
                항_text = "\n".join(도입_부분) + f"\n\n{항번호} {항_내용}"

                # 세부 (호/목) 포함
                if "세부" in item:
                    항_text += "\n" + self._format_세부(item["세부"])

                chunk = self._create_chunk(
                    chunk_type="항_분할",
                    법령명=법령명,
                    법령번호=법령번호,
                    시행일=시행일,
                    법령유형=법령유형,
                    모법=모법,
                    hierarchy=hierarchy,
                    path=path,
                    조문번호=조문번호,
                    조문제목=조문제목,
                    text=항_text,
                    항번호=항번호,
                    호번호=None,
                    원문_조문=조문번호
                )
                chunks.append(chunk)

        return chunks

    def _split_by_호(
        self,
        조문번호: str, 조문제목: str, 내용: List[Dict],
        법령명: str, 법령번호: str, 시행일: str, 법령유형: str, 모법: Optional[str],
        hierarchy: Dict, path: List[str]
    ) -> List[Dict]:
        """호 단위로 청크 분할 (목 포함!)"""
        chunks = []

        # 도입 본문 (조문번호 + 제목 + 본문들)
        도입_본문_parts = [f"{조문번호}({조문제목})"]

        for item in 내용:
            if "본문" in item:
                도입_본문_parts.append(item["본문"])

        도입_본문 = "\n".join(도입_본문_parts)

        # 각 호를 개별 청크로 생성
        for item in 내용:
            if "호" in item and "항번호" not in item:  # 직접 호만
                호_번호 = item["호"]
                호_내용 = item["내용"]

                # 호 텍스트 = 도입 본문 + 해당 호 + 목(세부)
                호_text = f"{도입_본문}\n\n{호_번호}. {호_내용}"

                # 세부(목) 포함 - 목은 별도 청크로 분할하지 않음!
                if "세부" in item:
                    호_text += "\n" + self._format_세부(item["세부"])

                chunk = self._create_chunk(
                    chunk_type="호_분할",
                    법령명=법령명,
                    법령번호=법령번호,
                    시행일=시행일,
                    법령유형=법령유형,
                    모법=모법,
                    hierarchy=hierarchy,
                    path=path,
                    조문번호=조문번호,
                    조문제목=조문제목,
                    text=호_text,
                    항번호=None,
                    호번호=호_번호,
                    원문_조문=조문번호
                )
                chunks.append(chunk)

        return chunks

    def _build_article_text(self, 조문번호: str, 조문제목: str, 내용: List[Dict]) -> str:
        """조문 내용을 텍스트로 구성"""
        parts = [f"{조문번호}({조문제목})"]

        for item in 내용:
            if "본문" in item:
                parts.append(item["본문"])
            elif "항번호" in item:
                parts.append(f'{item["항번호"]} {item["내용"]}')
                if "세부" in item:
                    parts.append(self._format_세부(item["세부"]))
            elif "호" in item:
                parts.append(f'{item["호"]}. {item["내용"]}')
                if "세부" in item:
                    parts.append(self._format_세부(item["세부"]))

        return "\n".join(parts)

    def _format_세부(self, 세부: List[Dict], indent: int = 1) -> str:
        """목/호 세부 내용 포맷팅 (재귀적 처리)"""
        lines = []
        prefix = "   " * indent

        for item in 세부:
            if "호" in item:
                lines.append(f'{prefix}{item["호"]}. {item["내용"]}')
            elif "목" in item:
                lines.append(f'{prefix}{item["목"]}. {item["내용"]}')

            # 중첩된 세부 항목
            if "세부" in item:
                lines.append(self._format_세부(item["세부"], indent + 1))

        return "\n".join(lines)

    def _create_chunk(
        self,
        chunk_type: str,
        법령명: str, 법령번호: str, 시행일: str, 법령유형: str, 모법: Optional[str],
        hierarchy: Dict, path: List[str],
        조문번호: str, 조문제목: str, text: str,
        항번호: Optional[str], 호번호: Optional[str], 원문_조문: str
    ) -> Dict:
        """단일 청크 생성"""
        # chunk_id 생성
        chunk_id = f"{법령명}_{조문번호}"
        if 항번호:
            chunk_id += f"_{항번호}"
        if 호번호:
            chunk_id += f"_{호번호}호"

        # 위계 경로 구성
        path_with_조 = path + [f"{조문번호} {조문제목}"]
        hierarchy_path = " > ".join(path_with_조)

        # 참조 관계 추출
        references = self._extract_references(text, 조문번호)

        # 키워드 추출
        keywords = self._extract_keywords(text, 조문제목)

        return {
            "chunk_id": chunk_id,
            "법령명": 법령명,
            "법령번호": 법령번호,
            "시행일": 시행일,
            "법령유형": 법령유형,
            "모법": 모법,
            "편": hierarchy.get("편"),
            "장": hierarchy.get("장"),
            "절": hierarchy.get("절"),
            "관": hierarchy.get("관"),
            "조문번호": 조문번호,
            "조문제목": 조문제목,
            "항번호": 항번호,
            "호번호": 호번호,
            "chunk_type": chunk_type,
            "원문_조문": 원문_조문,
            "hierarchy_path": hierarchy_path,
            "text": text,
            "text_length": len(text),
            "참조조문": references["참조"],
            "준용조문": references["준용"],
            "위임대상": [],  # 추후 시행령 매칭 시 채움
            "위임근거": references["위임근거"],
            "keywords": keywords,
            "example_cases": [],  # 추후 OpenAI로 생성
            "metadata": {
                "위임": references["위임"],
                "created_at": datetime.now().isoformat()
            }
        }

    def _extract_references(self, text: str, current_조문번호: str) -> Dict:
        """조문 텍스트에서 참조 관계 추출"""
        references = {
            "준용": [],
            "참조": [],
            "위임": False,
            "위임근거": None
        }

        # 준용 패턴: "제X조제Y항을 준용한다"
        준용_패턴 = r'제(\d+)조(?:의(\d+))?(?:제(\d+)항)?(?:제(\d+)호)?를?\s*준용'
        for match in re.finditer(준용_패턴, text):
            ref = self._construct_article_id(match)
            if ref and ref != current_조문번호:
                references["준용"].append(ref)

        # 참조 패턴: "제X조에 따라", "제X조에 의하여"
        참조_패턴 = r'제(\d+)조(?:의(\d+))?(?:제(\d+)항)?(?:제(\d+)호)?에?\s*(?:따라|의하여|규정된|정하는|해당하는)'
        for match in re.finditer(참조_패턴, text):
            ref = self._construct_article_id(match)
            if ref and ref != current_조문번호:
                references["참조"].append(ref)

        # 위임 패턴: "대통령령으로 정한다"
        위임_패턴 = r'대통령령으로\s*정한다|대통령령이\s*정하는|시행령으로\s*정한다'
        if re.search(위임_패턴, text):
            references["위임"] = True

        # 근거 패턴 (시행령 → 법률): "법 제X조에 따라"
        근거_패턴 = r'법\s*제(\d+)조(?:의(\d+))?(?:제(\d+)항)?에?\s*따라'
        match = re.search(근거_패턴, text)
        if match:
            references["위임근거"] = self._construct_article_id(match)

        return references

    def _construct_article_id(self, match) -> Optional[str]:
        """정규식 매치에서 조문 ID 구성"""
        groups = match.groups()
        조 = groups[0]
        의 = groups[1] if len(groups) > 1 and groups[1] else None
        항 = groups[2] if len(groups) > 2 and groups[2] else None
        호 = groups[3] if len(groups) > 3 and groups[3] else None

        ref = f"제{조}조"
        if 의:
            ref += f"의{의}"
        if 항:
            ref += f"제{항}항"
        if 호:
            ref += f"제{호}호"

        return ref

    def _extract_keywords(self, text: str, 조문제목: str) -> List[str]:
        """조문에서 주요 키워드 추출"""
        keywords = set()

        # 조문제목에서 키워드
        if 조문제목:
            keywords.add(조문제목)

        # 주요 법률 용어 패턴
        patterns = [
            r'(청약철회|계약해제|손해배상|위약금|환급|교환|반품)',
            r'(사기|강박|착오|의사표시|취소|무효)',
            r'(소비자|사업자|판매자|구매자|판매원)',
            r'(물품|용역|재화|서비스)',
            r'(권리|의무|책임|보호)',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text)
            keywords.update(matches)

        # 중복 제거 및 리스트 변환
        return list(keywords)

    def save_chunks(self, output_path: str = "chunks_law_ED.json"):
        """청크를 JSON 파일로 저장"""
        output_file = Path(output_path)

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.chunks, f, ensure_ascii=False, indent=2)

        print(f"\n청크 저장 완료: {output_file}")
        print(f"총 {len(self.chunks)}개 청크")

        # 통계 출력
        self._print_statistics()

    def save_chunks_jsonl(self, output_path: str = "chunks_law_ED.jsonl"):
        """청크를 JSONL(JSON Lines) 파일로 저장

        JSONL 형식의 장점:
        - 라인 단위 스트리밍 처리 가능
        - 메모리 효율적 (한 줄씩 읽기 가능)
        - 대용량 데이터 처리에 유리
        - 벡터DB 배치 업로드에 최적화
        """
        output_file = Path(output_path)

        with open(output_file, 'w', encoding='utf-8') as f:
            for chunk in self.chunks:
                # 각 청크를 한 줄의 JSON으로 작성
                json_line = json.dumps(chunk, ensure_ascii=False)
                f.write(json_line + '\n')

        print(f"\nJSONL 청크 저장 완료: {output_file}")
        print(f"총 {len(self.chunks)}개 청크 (라인 단위)")

        # 파일 크기 비교
        json_size = Path(output_path.replace('.jsonl', '.json')).stat().st_size if Path(output_path.replace('.jsonl', '.json')).exists() else 0
        jsonl_size = output_file.stat().st_size

        if json_size > 0:
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
        chunk_types = {}
        for chunk in self.chunks:
            ct = chunk["chunk_type"]
            chunk_types[ct] = chunk_types.get(ct, 0) + 1

        print(f"청크 유형별:")
        for ct, count in chunk_types.items():
            print(f"  {ct}: {count}개")

        # 법령별 개수
        law_counts = {}
        for chunk in self.chunks:
            law = chunk["법령명"]
            law_counts[law] = law_counts.get(law, 0) + 1

        print(f"\n법령별 청크 개수 (상위 5개):")
        for law, count in sorted(law_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
            print(f"  {law}: {count}개")

        # 평균 청크 크기
        avg_length = sum(c["text_length"] for c in self.chunks) / len(self.chunks)
        print(f"\n평균 청크 크기: {avg_length:.0f}자")


def main():
    """메인 실행 함수"""
    print("=" * 60)
    print("법률 및 시행령 청킹 스크립트")
    print("=" * 60)

    # 청킹 실행
    chunker = LawChunker(law_dir="01_parsed/01_law_ED")
    chunks = chunker.process_all_laws()

    # 결과 저장 (JSON 및 JSONL 모두)
    chunker.save_chunks("02_chunked/chunks_law_ED.json")
    chunker.save_chunks_jsonl("02_chunked/chunks_law_ED.jsonl")

    print("\n완료!")


if __name__ == "__main__":
    main()
