"""
행정규칙 크롤링 스크립트
법제처 국가법령정보센터에서 행정규칙을 크롤링하여 JSON으로 저장
- 부칙 제외
- 별표 메타데이터 저장 (소비자분쟁해결기준 등)
"""
from playwright.sync_api import sync_playwright
import json
import re
import os


def load_guide_urls(file_path):
    """URL 파일에서 행정규칙명과 URL 목록 로드"""
    guides = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or " : " not in line:
                continue
            parts = line.split(" : ", 1)
            if len(parts) == 2:
                name = parts[0].strip()
                url = parts[1].strip()
                guides.append({"name": name, "url": url})
    return guides


def clean_text(text):
    """텍스트 정리"""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    text = text.replace('\xa0', ' ')
    return text.strip()


def extract_law_info(page):
    """페이지에서 행정규칙 정보 추출"""
    info = {"법령명": "", "시행일": "", "법령번호": "", "소관부처": ""}

    try:
        # 제목 추출 - hidden input 또는 h2에서
        title_input = page.query_selector("input#lsNm")
        if title_input:
            info["법령명"] = title_input.get_attribute("value") or ""
        else:
            title_elem = page.query_selector("div.subtit1 h2, h2")
            if title_elem:
                info["법령명"] = clean_text(title_elem.inner_text())

        # 시행일, 법령번호 추출 (div.subtit1에 있음)
        info_elem = page.query_selector("div.subtit1")
        if info_elem:
            info_text = clean_text(info_elem.inner_text())

            # 시행일 추출: [시행 2024. 1. 9.]
            date_match = re.search(r'\[시행\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\]', info_text)
            if date_match:
                info["시행일"] = f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"

            # 법령번호 추출: [공정거래위원회예규 제451호, ...]
            num_match = re.search(r'\[([^\]]+제\d+호)', info_text)
            if num_match:
                info["법령번호"] = num_match.group(1)

        # 소관부처 추출 (div.subtit2에 있음)
        dept_elem = page.query_selector("div.subtit2")
        if dept_elem:
            dept_text = clean_text(dept_elem.inner_text())
            # 공정거래위원회(특수거래정책과), 044-200-4431 형식
            dept_match = re.search(r'^([^\(]+)\(([^\)]+)\)', dept_text)
            if dept_match:
                info["소관부처"] = dept_match.group(1).strip()
    except:
        pass

    return info


def extract_byulpyo_info(page):
    """별표 메타데이터 추출"""
    byulpyo_list = []

    try:
        # 별표 링크들 찾기
        links = page.query_selector_all('a')
        for link in links:
            text = link.inner_text().replace('\xa0', ' ').strip()
            # [별표 1], [별표 2] 등의 패턴
            if re.match(r'\[별표\s*\d+\]', text):
                onclick = link.get_attribute('onclick') or ''
                # bylInfoDiv('3110555') 형태에서 ID 추출
                id_match = re.search(r"bylInfoDiv\('(\d+)'\)", onclick)
                byulpyo_id = id_match.group(1) if id_match else ""

                byulpyo_list.append({
                    "제목": text,
                    "ID": byulpyo_id
                })
    except:
        pass

    return byulpyo_list


def is_appendix_start(text):
    """부칙 시작 여부 확인"""
    # 부칙 패턴: "부      칙" 또는 "부칙"
    appendix_pattern = r'^부\s*칙'
    return bool(re.match(appendix_pattern, text.strip()))


def parse_hang_ho_from_text(text):
    """
    텍스트에서 항(①②③)과 호(1. 2. 3.)를 계층적으로 추출

    케이스 1 - 항이 있는 경우:
      입력: "① 사업자는... 1. 첫번째... ② 이용자는..."
      출력: [{"항": "①", "내용": "사업자는...", "세부": [{"호": "1", ...}]}, ...]

    케이스 2 - 항 없이 호만 있는 경우 (조 -> 호 직접):
      입력: "이 지침에서 사용하는 용어의 뜻은 다음과 같다. 1. 콘텐츠란... 2. 이용자란..."
      출력: [{"본문": "이 지침에서..."}, {"호": "1", "내용": "콘텐츠란..."}, ...]
    """
    if not text:
        return []

    hang_pattern = r'([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮])'
    ho_pattern = r'(\d+)\.\s+'

    # 항(①) 패턴이 있는지 확인
    has_hang = bool(re.search(hang_pattern, text))

    result = []

    if has_hang:
        # 케이스 1: 항이 있는 경우 - 기존 로직
        parts = re.split(hang_pattern, text)
        i = 0

        # 첫 번째 부분 처리
        if parts:
            first_part = parts[0].strip()
            if not first_part:
                i = 1
            elif not re.match(hang_pattern, first_part):
                # 항 앞에 본문이 있으면 호 패턴 확인
                ho_parts = re.split(ho_pattern, first_part)
                if len(ho_parts) > 1:
                    # 호가 있는 경우
                    if ho_parts[0].strip():
                        result.append({"본문": ho_parts[0].strip()})
                    j = 1
                    while j < len(ho_parts) - 1:
                        ho_num = ho_parts[j]
                        ho_content = ho_parts[j + 1].strip() if j + 1 < len(ho_parts) else ""
                        if ho_num.isdigit() and ho_content:
                            result.append({"호": ho_num, "내용": ho_content})
                        j += 2
                else:
                    result.append({"본문": first_part})
                i = 1

        # 항 기호와 내용 쌍으로 처리
        while i < len(parts):
            if i >= len(parts):
                break

            hang_symbol = parts[i]

            if re.match(hang_pattern, hang_symbol):
                hang_content = parts[i + 1].strip() if i + 1 < len(parts) else ""
                ho_parts = re.split(ho_pattern, hang_content)

                hang_item = {"항": hang_symbol, "내용": "", "세부": []}

                if ho_parts and ho_parts[0].strip():
                    hang_item["내용"] = ho_parts[0].strip()

                j = 1
                while j < len(ho_parts) - 1:
                    ho_num = ho_parts[j]
                    ho_content = ho_parts[j + 1].strip() if j + 1 < len(ho_parts) else ""
                    if ho_num.isdigit() and ho_content:
                        hang_item["세부"].append({"호": ho_num, "내용": ho_content})
                    j += 2

                if not hang_item["세부"]:
                    del hang_item["세부"]

                result.append(hang_item)
                i += 2
            else:
                i += 1
    else:
        # 케이스 2: 항 없이 호만 있는 경우 (조 -> 호 직접)
        ho_parts = re.split(ho_pattern, text)

        # 첫 번째 부분은 본문
        if ho_parts and ho_parts[0].strip():
            result.append({"본문": ho_parts[0].strip()})

        # 호 번호와 내용 쌍으로 처리
        j = 1
        while j < len(ho_parts) - 1:
            ho_num = ho_parts[j]
            ho_content = ho_parts[j + 1].strip() if j + 1 < len(ho_parts) else ""
            if ho_num.isdigit() and ho_content:
                result.append({"호": ho_num, "내용": ho_content})
            j += 2

    return result


def parse_content_structure(paragraphs):
    """
    본문을 계층 구조로 파싱 (부칙 제외)

    행정규칙 계층 구조:
    - Ⅰ, Ⅱ, Ⅲ... (대분류)
    - 1. 2. 3... (중분류)
    - 가. 나. 다... (소분류)
    - 1) 2) 3)... (세부항목)
    - ① ② ③... (세세부항목)

    법령 스타일 계층 구조:
    - 제N장 (장)
    - 제N조 (조)
    - ① ② ③ (항) - CSS 클래스: pty1_de2_1
    - 1. 2. 3. (호) - CSS 클래스: pty1_de2h
    - 가. 나. 다. (목) - CSS 클래스: pty1_de3
    """
    result = []

    # 현재 위치 추적
    current = {
        "chapter": None,      # 장 (제1장, 제2장...)
        "article": None,      # 조 (제1조, 제2조...)
        "section": None,      # 대분류 (Ⅰ, Ⅱ, ... 또는 I, II, ...)
        "subsection": None,   # 중분류 (1. 2. ...)
        "item": None,         # 소분류 (가. 나. ...)
        "subitem": None,      # 세부항목 (1) 2) ...) 또는 항(①)
        "detail": None,       # 세세부항목 (① ② ... 또는 (1) (2) ...) 또는 호(1.)
        "subdetail": None,    # 세세세부항목 (ㅇ 항목) 또는 목(가.)
    }

    # 패턴 정의
    patterns = {
        # 장: 제1장, 제2장 등
        "chapter": r'^제(\d+)장\s*(.*)$',
        # 조: 제1조(목적), 제2조(정의) 등
        "article": r'^제(\d+)조\(([^)]+)\)\s*(.*)$',
        # 조 (제목 없이): 제1조 내용...
        "article_simple": r'^제(\d+)조\s+(.+)$',
        # 대분류: 로마 숫자 (Ⅰ, Ⅱ) 또는 라틴 문자 (I, II, III, IV, V)
        "roman": r'^(Ⅰ|Ⅱ|Ⅲ|Ⅳ|Ⅴ|Ⅵ|Ⅶ|Ⅷ|Ⅸ|Ⅹ|I|II|III|IV|V|VI|VII|VIII|IX|X)\.\s*(.+)$',
        "number_dot": r'^(\d+)\.\s*(.+)$',
        "korean": r'^([가나다라마바사아자차카타파하])\.\s*(.+)$',
        "number_paren": r'^(\d+)\)\s*(.+)$',
        "circled": r'^([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮])\s*(.+)$',
        # 괄호 숫자: (1), (2), (3)... - 세부항목 레벨
        "paren_number": r'^\((\d+)\)\s*(.+)$',
        "example_header": r'^<([^>]+)>$',
        # ㅇ 기호 항목
        "circle_o": r'^[ㅇ]\s*(.+)$',
        "dash": r'^[-]\s*(.+)$',
        "arrow": r'^[⇒]\s*(.+)$',
        # ※ 참고 항목
        "note": r'^[※]\s*(.+)$',
    }

    # 법령 스타일 여부 확인
    # paragraphs가 dict 리스트면 법령 스타일 (CSS 클래스 정보 포함)
    is_law_style_with_class = paragraphs and isinstance(paragraphs[0], dict)

    if is_law_style_with_class:
        # 텍스트만 추출해서 확인
        is_law_style = any(
            re.match(r'^제\d+조', p.get("text", ""))
            for p in paragraphs[:10] if isinstance(p, dict)
        )
    else:
        is_law_style = any(re.match(r'^제\d+조', clean_text(p)) for p in paragraphs[:10])

    in_appendix = False  # 부칙 영역 진입 여부

    for p_item in paragraphs:
        # 법령 스타일(CSS 클래스 포함)인 경우 text와 class 분리
        if isinstance(p_item, dict):
            text = p_item.get("text", "")
            css_class = p_item.get("class", "")
        else:
            text = clean_text(p_item)
            css_class = ""

        if not text:
            continue

        # 부칙 시작 확인 - 부칙 이후는 모두 무시
        if is_appendix_start(text):
            in_appendix = True
            continue

        if in_appendix:
            continue

        # ===== 법령 스타일 처리 (장 -> 조 -> ① -> 1. -> 가.) =====
        if is_law_style:
            # CSS 클래스 기반 계층 구조 결정 (법령 스타일 with class info)
            if is_law_style_with_class and css_class:
                # pty1_p4: 조 (제N조)
                if "pty1_p4" in css_class:
                    # 장 확인 (제1장, 제2장...)
                    match = re.match(patterns["chapter"], text)
                    if match:
                        current["chapter"] = {
                            "장": f"제{match.group(1)}장",
                            "제목": match.group(2) if match.group(2) else "",
                            "내용": []
                        }
                        result.append(current["chapter"])
                        current["article"] = None
                        current["subitem"] = None
                        current["detail"] = None
                        current["subdetail"] = None
                        continue

                    # 조 확인 (제1조(목적) 내용...)
                    match = re.match(patterns["article"], text)
                    if match:
                        article_content = match.group(3).strip() if match.group(3) else ""
                        current["article"] = {
                            "조": f"제{match.group(1)}조",
                            "제목": match.group(2),
                            "내용": []
                        }
                        # 조 내용이 있으면 본문으로 저장
                        if article_content:
                            current["article"]["내용"].append({"본문": article_content})

                        if current["chapter"]:
                            current["chapter"]["내용"].append(current["article"])
                        else:
                            result.append(current["article"])
                        current["subitem"] = None
                        current["detail"] = None
                        current["subdetail"] = None
                        continue

                    # 기타 pty1_p4 본문
                    text_obj = {"본문": text}
                    if current["article"]:
                        current["article"]["내용"].append(text_obj)
                    elif current["chapter"]:
                        current["chapter"]["내용"].append(text_obj)
                    else:
                        result.append(text_obj)
                    continue

                # pty1_de2_1: 항 (①②③...)
                elif "pty1_de2_1" in css_class:
                    match = re.match(patterns["circled"], text)
                    if match:
                        current["subitem"] = {
                            "항": match.group(1),
                            "내용": match.group(2),
                            "세부": []
                        }
                    else:
                        # ① 없이 시작하는 경우
                        current["subitem"] = {
                            "항": "",
                            "내용": text,
                            "세부": []
                        }
                    if current["article"]:
                        current["article"]["내용"].append(current["subitem"])
                    elif current["chapter"]:
                        current["chapter"]["내용"].append(current["subitem"])
                    else:
                        result.append(current["subitem"])
                    current["detail"] = None
                    current["subdetail"] = None
                    continue

                # pty1_de2h: 호 (1. 2. 3...)
                elif "pty1_de2h" in css_class:
                    match = re.match(patterns["number_dot"], text)
                    if match:
                        current["detail"] = {
                            "호": match.group(1),
                            "내용": match.group(2),
                            "세부": []
                        }
                    else:
                        current["detail"] = {
                            "호": "",
                            "내용": text,
                            "세부": []
                        }
                    # 호는 항 아래 또는 조 바로 아래에 붙을 수 있음
                    if current["subitem"]:
                        current["subitem"]["세부"].append(current["detail"])
                    elif current["article"]:
                        current["article"]["내용"].append(current["detail"])
                    elif current["chapter"]:
                        current["chapter"]["내용"].append(current["detail"])
                    else:
                        result.append(current["detail"])
                    current["subdetail"] = None
                    continue

                # pty1_de3: 목 (가. 나. 다...)
                elif "pty1_de3" in css_class:
                    match = re.match(patterns["korean"], text)
                    if match:
                        current["subdetail"] = {
                            "목": match.group(1),
                            "내용": match.group(2)
                        }
                    else:
                        current["subdetail"] = {
                            "목": "",
                            "내용": text
                        }
                    # 목은 호 아래에 붙음
                    if current["detail"]:
                        current["detail"]["세부"].append(current["subdetail"])
                    elif current["subitem"]:
                        current["subitem"]["세부"].append(current["subdetail"])
                    elif current["article"]:
                        current["article"]["내용"].append(current["subdetail"])
                    continue

            # 기존 로직 (CSS 클래스 정보 없는 경우)
            else:
                # 장 확인 (제1장, 제2장...)
                match = re.match(patterns["chapter"], text)
                if match:
                    current["chapter"] = {
                        "장": f"제{match.group(1)}장",
                        "제목": match.group(2) if match.group(2) else "",
                        "내용": []
                    }
                    result.append(current["chapter"])
                    current["article"] = None
                    current["subitem"] = None
                    current["detail"] = None
                    continue

                # 조 확인 (제1조(목적) 내용...)
                match = re.match(patterns["article"], text)
                if match:
                    article_content = match.group(3).strip() if match.group(3) else ""
                    current["article"] = {
                        "조": f"제{match.group(1)}조",
                        "제목": match.group(2),
                        "내용": []
                    }
                    # 조 내용에서 항(①)과 호(1.) 추출
                    if article_content:
                        parsed_items = parse_hang_ho_from_text(article_content)
                        for item in parsed_items:
                            current["article"]["내용"].append(item)
                            # 마지막 항을 current["subitem"]으로 설정 (후속 처리를 위해)
                            if "항" in item:
                                current["subitem"] = item

                    if current["chapter"]:
                        current["chapter"]["내용"].append(current["article"])
                    else:
                        result.append(current["article"])
                    current["detail"] = None
                    continue

                # 항 확인 (① ② ③...)
                match = re.match(patterns["circled"], text)
                if match:
                    current["subitem"] = {
                        "항": match.group(1),
                        "내용": match.group(2),
                        "세부": []
                    }
                    if current["article"]:
                        current["article"]["내용"].append(current["subitem"])
                    elif current["chapter"]:
                        current["chapter"]["내용"].append(current["subitem"])
                    else:
                        result.append(current["subitem"])
                    current["detail"] = None
                    continue

                # 호 확인 (1. 2. 3...)
                match = re.match(patterns["number_dot"], text)
                if match:
                    current["detail"] = {
                        "호": match.group(1),
                        "내용": match.group(2),
                        "세부": []
                    }
                    if current["subitem"]:
                        current["subitem"]["세부"].append(current["detail"])
                    elif current["article"]:
                        current["article"]["내용"].append(current["detail"])
                    continue

                # 일반 본문 - 항(①)과 호(1.) 추출 시도
                # 텍스트에 ① 패턴이 있으면 항/호로 분리
                if re.search(r'[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮]', text):
                    parsed_items = parse_hang_ho_from_text(text)
                    for item in parsed_items:
                        if current["article"]:
                            current["article"]["내용"].append(item)
                            if "항" in item:
                                current["subitem"] = item
                        elif current["chapter"]:
                            current["chapter"]["내용"].append(item)
                        else:
                            result.append(item)
                else:
                    text_obj = {"본문": text}
                    if current["detail"]:
                        current["detail"]["세부"].append(text_obj)
                    elif current["subitem"]:
                        if "세부" not in current["subitem"]:
                            current["subitem"]["세부"] = []
                        current["subitem"]["세부"].append(text_obj)
                    elif current["article"]:
                        current["article"]["내용"].append(text_obj)
                    elif current["chapter"]:
                        current["chapter"]["내용"].append(text_obj)
                    else:
                        result.append(text_obj)
            continue

        # ===== 행정규칙 스타일 처리 (Ⅰ -> 1. -> 가. -> (1) -> ㅇ) =====

        # 1. 대분류 확인 (Ⅰ. 목적 및 구성)
        match = re.match(patterns["roman"], text)
        if match:
            current["section"] = {
                "분류": match.group(1),
                "제목": match.group(2),
                "내용": []
            }
            result.append(current["section"])
            current["subsection"] = None
            current["item"] = None
            current["subitem"] = None
            current["detail"] = None
            continue

        # 2. 중분류 확인 (1. 목적)
        match = re.match(patterns["number_dot"], text)
        if match:
            current["subsection"] = {
                "번호": match.group(1),
                "제목": match.group(2),
                "내용": []
            }
            if current["section"]:
                current["section"]["내용"].append(current["subsection"])
            else:
                result.append(current["subsection"])
            current["item"] = None
            current["subitem"] = None
            current["detail"] = None
            continue

        # 3. 소분류 확인 (가. 계약체결 전 정보제공의무)
        match = re.match(patterns["korean"], text)
        if match:
            current["item"] = {
                "번호": match.group(1),
                "제목": match.group(2),
                "내용": []
            }
            if current["subsection"]:
                current["subsection"]["내용"].append(current["item"])
            elif current["section"]:
                current["section"]["내용"].append(current["item"])
            else:
                result.append(current["item"])
            current["subitem"] = None
            current["detail"] = None
            continue

        # 4. 세부항목 확인 (1) 선불식 할부거래업자...)
        match = re.match(patterns["number_paren"], text)
        if match:
            current["subitem"] = {
                "번호": match.group(1) + ")",
                "내용": match.group(2),
                "세부": []
            }
            if current["item"]:
                current["item"]["내용"].append(current["subitem"])
            elif current["subsection"]:
                current["subsection"]["내용"].append(current["subitem"])
            current["detail"] = None
            current["subdetail"] = None
            continue

        # 4-1. 괄호 숫자 확인 ((1) 갑은 인터넷상의...) - subitem 레벨
        match = re.match(patterns["paren_number"], text)
        if match:
            current["subitem"] = {
                "번호": f"({match.group(1)})",
                "내용": match.group(2),
                "세부": []
            }
            if current["item"]:
                current["item"]["내용"].append(current["subitem"])
            elif current["subsection"]:
                current["subsection"]["내용"].append(current["subitem"])
            current["detail"] = None
            current["subdetail"] = None
            continue

        # 5. 세세부항목 확인 (① 유류할증료...)
        match = re.match(patterns["circled"], text)
        if match:
            current["detail"] = {
                "번호": match.group(1),
                "내용": match.group(2),
                "세부": []
            }
            if current["subitem"]:
                current["subitem"]["세부"].append(current["detail"])
            elif current["item"]:
                current["item"]["내용"].append(current["detail"])
            current["subdetail"] = None
            continue

        # 6. 예시/업종 헤더 확인 (<예시>, <여행업종의 경우> 등)
        match = re.match(patterns["example_header"], text)
        if match:
            header_text = match.group(1)
            header_obj = {"구분": header_text, "내용": []}

            # 가장 가까운 상위 요소에 추가
            if current["detail"]:
                current["detail"]["세부"].append(header_obj)
            elif current["subitem"]:
                current["subitem"]["세부"].append(header_obj)
            elif current["item"]:
                current["item"]["내용"].append(header_obj)
            elif current["subsection"]:
                current["subsection"]["내용"].append(header_obj)
            continue

        # 6-1. ㅇ 기호 항목 (ㅇ 소비자가 광고지를 보고...)
        match = re.match(patterns["circle_o"], text)
        if match:
            current["subdetail"] = {
                "기호": "ㅇ",
                "내용": match.group(1),
                "세부": []
            }
            if current["detail"]:
                current["detail"]["세부"].append(current["subdetail"])
            elif current["subitem"]:
                current["subitem"]["세부"].append(current["subdetail"])
            elif current["item"]:
                current["item"]["내용"].append(current["subdetail"])
            continue

        # 7. 하이픈 항목 (- 가이드 경비를 현지에서...)
        match = re.match(patterns["dash"], text)
        if match:
            dash_content = match.group(1)
            dash_obj = {"항목": dash_content}

            if current["subdetail"]:
                current["subdetail"]["세부"].append(dash_obj)
            elif current["detail"]:
                current["detail"]["세부"].append(dash_obj)
            elif current["subitem"]:
                current["subitem"]["세부"].append(dash_obj)
            elif current["item"]:
                current["item"]["내용"].append(dash_obj)
            elif current["subsection"]:
                current["subsection"]["내용"].append(dash_obj)
            continue

        # 8. 화살표 항목 (⇒ 결과 설명...)
        match = re.match(patterns["arrow"], text)
        if match:
            arrow_content = match.group(1)
            arrow_obj = {"설명": arrow_content}

            if current["subdetail"]:
                current["subdetail"]["세부"].append(arrow_obj)
            elif current["detail"]:
                current["detail"]["세부"].append(arrow_obj)
            elif current["subitem"]:
                current["subitem"]["세부"].append(arrow_obj)
            elif current["item"]:
                current["item"]["내용"].append(arrow_obj)
            elif current["subsection"]:
                current["subsection"]["내용"].append(arrow_obj)
            continue

        # 8-1. 참고 항목 (※ 인도에 간이판매장...)
        match = re.match(patterns["note"], text)
        if match:
            note_content = match.group(1)
            note_obj = {"참고": note_content}

            if current["subdetail"]:
                current["subdetail"]["세부"].append(note_obj)
            elif current["detail"]:
                current["detail"]["세부"].append(note_obj)
            elif current["subitem"]:
                current["subitem"]["세부"].append(note_obj)
            elif current["item"]:
                current["item"]["내용"].append(note_obj)
            elif current["subsection"]:
                current["subsection"]["내용"].append(note_obj)
            continue

        # 9. 일반 본문 텍스트 - 가장 가까운 상위 요소에 추가
        text_obj = {"본문": text}

        if current["subdetail"]:
            current["subdetail"]["세부"].append(text_obj)
        elif current["detail"]:
            current["detail"]["세부"].append(text_obj)
        elif current["subitem"]:
            current["subitem"]["세부"].append(text_obj)
        elif current["item"]:
            current["item"]["내용"].append(text_obj)
        elif current["subsection"]:
            current["subsection"]["내용"].append(text_obj)
        elif current["section"]:
            current["section"]["내용"].append(text_obj)
        else:
            result.append(text_obj)

    return result


def crawl_guide(name, url, output_dir="raw/02_Guide"):
    """단일 행정규칙 크롤링"""
    print(f"\n{'='*50}")
    print(f"크롤링 시작: {name}")
    print(f"{'='*50}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("페이지 접속 중...")
        page.goto(url, timeout=60000)

        print("본문 로딩 대기 중...")
        page.wait_for_timeout(7000)

        # 법령 정보 추출
        law_info = extract_law_info(page)
        print(f"법령명: {law_info['법령명']}")

        # 별표 메타데이터 추출
        byulpyo_info = extract_byulpyo_info(page)
        if byulpyo_info:
            print(f"별표 {len(byulpyo_info)}개 발견")

        # 법령 스타일 여부 확인 (제N조 패턴)
        # 법령 스타일의 경우 여러 CSS 클래스에서 요소 추출 필요
        test_elements = page.query_selector_all("p.pty1_p4")
        is_law_style = any(
            re.match(r'^제\d+조', clean_text(el.inner_text()))
            for el in test_elements[:10]
        )

        # 본문 텍스트 추출
        paragraphs = []

        if is_law_style:
            # 법령 스타일: 여러 CSS 클래스에서 계층적으로 추출
            # pty1_p4: 조 헤더, pty1_de2_1: 항(①), pty1_de2h: 호(1.), pty1_de3: 목(가.)
            all_p = page.query_selector_all("p.pty1_p4, p.pty1_de2_1, p.pty1_de2h, p.pty1_de3")
            for p_elem in all_p:
                text = clean_text(p_elem.inner_text())
                cls = p_elem.get_attribute("class") or ""
                if text:
                    # CSS 클래스 정보를 포함하여 저장 (파싱에서 사용)
                    paragraphs.append({"text": text, "class": cls})
            print(f"총 {len(paragraphs)}개 문단 발견 (법령 스타일)")
        else:
            # 일반 행정규칙: 기존 방식
            p_elements = page.query_selector_all("p.pty1_p4")
            for p_elem in p_elements:
                text = clean_text(p_elem.inner_text())
                if text:
                    paragraphs.append(text)
            print(f"총 {len(paragraphs)}개 문단 발견")

        # 구조화된 본문 파싱 (부칙 제외)
        structured_content = parse_content_structure(paragraphs)

        # 결과 구성
        result = {
            "법령명": law_info["법령명"],
            "시행일": law_info["시행일"],
            "법령번호": law_info["법령번호"],
            "소관부처": law_info["소관부처"],
            "본문": structured_content
        }

        # 별표 정보 추가 (있는 경우)
        if byulpyo_info:
            result["별표"] = byulpyo_info

        # 파일명 생성 (법령명에서 특수문자 제거)
        filename = re.sub(r'[\\/:*?"<>|]', '', law_info["법령명"])
        if not filename:
            filename = re.sub(r'[\\/:*?"<>|]', '', name)

        # output_dir 생성
        os.makedirs(output_dir, exist_ok=True)

        output_path = os.path.join(output_dir, f"{filename}.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"저장 완료: {output_path}")

        browser.close()
        return {"법령명": law_info["법령명"], "문단수": len(paragraphs), "상태": "성공"}


def main():
    """메인 함수: 모든 행정규칙 크롤링"""
    url_file = "raw/02_Guide/행정규칙_URL.txt"
    output_dir = "raw/02_Guide"

    guides = load_guide_urls(url_file)
    print(f"총 {len(guides)}개 행정규칙 크롤링 예정")

    results = []

    for i, guide in enumerate(guides, 1):
        print(f"\n[{i}/{len(guides)}] {guide['name']}")
        try:
            result = crawl_guide(guide["name"], guide["url"], output_dir)
            results.append(result)
        except Exception as e:
            print(f"오류 발생: {e}")
            results.append({"법령명": guide["name"], "문단수": 0, "상태": f"실패: {e}"})

    print("\n" + "="*60)
    print("크롤링 완료 요약")
    print("="*60)
    for r in results:
        status = "[O]" if r["상태"] == "성공" else "[X]"
        print(f"{status} {r['법령명']}: {r.get('문단수', 0)}개 문단")


if __name__ == "__main__":
    main()
