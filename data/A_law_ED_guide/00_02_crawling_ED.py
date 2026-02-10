"""
시행령 크롤링 스크립트
법제처 국가법령정보센터에서 시행령 조문을 크롤링하여 JSON으로 저장
"""
from playwright.sync_api import sync_playwright
import json
import re
import os


def load_law_urls(file_path):
    """URL 파일에서 법령명과 URL 목록 로드"""
    laws = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue
            parts = line.split(" : ", 1)
            if len(parts) == 2:
                law_name = parts[0].strip()
                if law_name and law_name[0].isdigit():
                    law_name = re.sub(r'^\d+\s*', '', law_name)
                url = parts[1].strip()
                laws.append({"name": law_name, "url": url})
    return laws


def parse_article_content(text):
    """조문 내용을 항 계층 구조로 파싱 (기존 방식 - CSS 클래스 없는 경우)"""
    hang_pattern = r'([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])'

    result = {}
    parts = re.split(hang_pattern, text.strip())

    if len(parts) == 1:
        content = clean_text(parts[0])
        if content:
            result["내용"] = content
        return result

    idx = 0
    if parts[0] and not re.match(hang_pattern, parts[0]):
        content = clean_text(parts[0])
        if content:
            result["내용"] = content
        idx = 1

    hang_list = []
    while idx < len(parts):
        if re.match(hang_pattern, parts[idx]):
            hang_num = parts[idx]
            hang_content = parts[idx + 1] if idx + 1 < len(parts) else ""

            content = clean_text(hang_content)
            if content:
                hang_list.append({
                    "항번호": hang_num,
                    "내용": content
                })
            idx += 2
        else:
            idx += 1

    if hang_list:
        result["항"] = hang_list

    return result


def parse_law_elements(elements):
    """
    CSS 클래스 정보를 포함한 요소들을 계층적으로 파싱
    조 -> 항(①) -> 호(1.) -> 목(가.)
    """
    result = []
    current = {
        "article": None,  # 현재 조문
        "hang": None,     # 현재 항
        "ho": None,       # 현재 호
    }

    for elem in elements:
        text = elem.get("text", "")
        css_class = elem.get("class", "")

        if not text:
            continue

        # pty1_p4: 조문 헤더
        if "pty1_p4" in css_class:
            # 조문 번호와 제목 추출
            match = re.match(r'(제\d+조(?:의\d+)?)\s*(?:\(([^)]+)\))?\s*(.*)', text)
            if match:
                article_num = match.group(1)
                article_title = match.group(2) or ""
                article_content = match.group(3).strip() if match.group(3) else ""

                current["article"] = {
                    "조문번호": article_num,
                    "조문제목": article_title,
                    "내용": []
                }

                # 조문 헤더에 본문이 있으면 추가
                if article_content:
                    current["article"]["내용"].append({"본문": article_content})

                result.append(current["article"])
                current["hang"] = None
                current["ho"] = None

        # pty1_de2_1: 항 (①②③...)
        elif "pty1_de2_1" in css_class:
            hang_pattern = r'^([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])\s*(.*)'
            match = re.match(hang_pattern, text)
            if match:
                current["hang"] = {
                    "항번호": match.group(1),
                    "내용": match.group(2),
                    "세부": []
                }
            else:
                current["hang"] = {
                    "항번호": "",
                    "내용": text,
                    "세부": []
                }

            if current["article"]:
                current["article"]["내용"].append(current["hang"])
            current["ho"] = None

        # pty1_de2h: 호 (1. 2. 3...)
        elif "pty1_de2h" in css_class:
            ho_pattern = r'^(\d+)\.\s*(.*)'
            match = re.match(ho_pattern, text)
            if match:
                current["ho"] = {
                    "호": match.group(1),
                    "내용": match.group(2),
                    "세부": []
                }
            else:
                current["ho"] = {
                    "호": "",
                    "내용": text,
                    "세부": []
                }

            # 호는 항 아래 또는 조 바로 아래에 붙을 수 있음
            if current["hang"]:
                current["hang"]["세부"].append(current["ho"])
            elif current["article"]:
                current["article"]["내용"].append(current["ho"])

        # pty1_de3: 목 (가. 나. 다...)
        elif "pty1_de3" in css_class:
            mok_pattern = r'^([가나다라마바사아자차카타파하])\.\s*(.*)'
            match = re.match(mok_pattern, text)
            if match:
                mok_item = {
                    "목": match.group(1),
                    "내용": match.group(2)
                }
            else:
                mok_item = {
                    "목": "",
                    "내용": text
                }

            # 목은 호 아래에 붙음
            if current["ho"]:
                current["ho"]["세부"].append(mok_item)
            elif current["hang"]:
                current["hang"]["세부"].append(mok_item)
            elif current["article"]:
                current["article"]["내용"].append(mok_item)

    # 빈 세부 배열 정리
    for article in result:
        if "내용" in article:
            for item in article["내용"]:
                if "세부" in item and not item["세부"]:
                    del item["세부"]
                elif "세부" in item:
                    for sub in item.get("세부", []):
                        if "세부" in sub and not sub["세부"]:
                            del sub["세부"]

    return result


def clean_text(text):
    """텍스트 정리"""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    text = text.replace('\xa0', ' ')
    return text.strip()


def extract_article_info(label_text):
    """조문 번호와 제목 추출"""
    match = re.match(r'(제\d+조(?:의\d+)?)\s*(?:\(([^)]+)\))?', label_text.strip())
    if match:
        return match.group(1), match.group(2) or ""
    return label_text.strip(), ""


def extract_law_info(page):
    """페이지에서 법령 정보(시행일, 법령번호) 추출"""
    info = {"시행일": "", "법령번호": ""}

    try:
        info_elem = page.query_selector(".tx2, .lsInfo")
        if info_elem:
            info_text = clean_text(info_elem.inner_text())

            # 시행일 추출
            date_match = re.search(r'\[시행\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\]', info_text)
            if date_match:
                info["시행일"] = f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"

            # 법령번호 추출 (대통령령)
            law_num_match = re.search(r'\[대통령령\s*제(\d+)호', info_text)
            if law_num_match:
                info["법령번호"] = f"대통령령 제{law_num_match.group(1)}호"
    except:
        pass

    return info


def crawl_law(law_name, url, output_dir="raw/01_law_ED"):
    """단일 시행령 크롤링 - CSS 클래스 기반 계층 구조 추출"""
    print(f"\n{'='*50}")
    print(f"크롤링 시작: {law_name}")
    print(f"{'='*50}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("페이지 접속 중...")
        page.goto(url, timeout=60000)

        print("조문 로딩 대기 중...")
        page.wait_for_timeout(7000)

        law_info = extract_law_info(page)

        result = {
            "법령명": law_name,
            "시행일": law_info["시행일"],
            "법령번호": law_info["법령번호"],
            "조문": []
        }

        # 구조 정보 (편/장/절/관이 있는 법령용)
        structure = {
            "편": None,
            "장": None,
            "절": None,
            "관": None
        }
        has_structure = False

        # 편/장/절/관 구조 먼저 확인
        gtit_elements = page.query_selector_all("p.gtit")
        for gtit in gtit_elements:
            title_text = clean_text(gtit.inner_text())
            if ("편" in title_text or "장" in title_text or "절" in title_text or "관" in title_text) and "제" in title_text:
                has_structure = True
                break

        # 모든 관련 요소 추출 (CSS 클래스 기반)
        all_elements = page.query_selector_all("p.gtit, p.pty1_p4, p.pty1_de2_1, p.pty1_de2h, p.pty1_de3")

        elements_with_class = []
        in_appendix = False  # 부칙 여부

        for elem in all_elements:
            text = clean_text(elem.inner_text())
            css_class = elem.get_attribute("class") or ""

            # 부칙 시작 확인
            if "부" in text and "칙" in text and "gtit" in css_class:
                in_appendix = True
                continue

            if in_appendix:
                continue

            if text:
                elements_with_class.append({"text": text, "class": css_class})

        print(f"총 {len(elements_with_class)}개 요소 발견")

        # 구조가 있는 법령 처리
        if has_structure:
            for elem in elements_with_class:
                text = elem["text"]
                css_class = elem["class"]

                # 편/장/절/관 처리
                if "gtit" in css_class:
                    if "편" in text and "제" in text:
                        structure["편"] = {"제목": text, "장": [], "조문": []}
                        structure["장"] = None
                        structure["절"] = None
                        structure["관"] = None
                        if "구조" not in result:
                            result["구조"] = []
                        result["구조"].append(structure["편"])

                    elif "장" in text and "제" in text:
                        structure["장"] = {"제목": text, "절": [], "조문": []}
                        structure["절"] = None
                        structure["관"] = None
                        if structure["편"]:
                            structure["편"]["장"].append(structure["장"])
                        else:
                            if "구조" not in result:
                                result["구조"] = []
                            result["구조"].append(structure["장"])

                    elif "절" in text and "제" in text:
                        structure["절"] = {"제목": text, "관": [], "조문": []}
                        structure["관"] = None
                        if structure["장"]:
                            structure["장"]["절"].append(structure["절"])

                    elif "관" in text and "제" in text:
                        structure["관"] = {"제목": text, "조문": []}
                        if structure["절"]:
                            structure["절"]["관"].append(structure["관"])
                    continue

                # 조문 처리
                if "pty1_p4" in css_class:
                    match = re.match(r'(제\d+조(?:의\d+)?)\s*(?:\(([^)]+)\))?\s*(.*)', text)
                    if match:
                        article_obj = {
                            "조문번호": match.group(1),
                            "조문제목": match.group(2) or "",
                            "내용": []
                        }
                        if match.group(3) and match.group(3).strip():
                            article_obj["내용"].append({"본문": match.group(3).strip()})

                        # 적절한 위치에 추가
                        if structure["관"]:
                            structure["관"]["조문"].append(article_obj)
                        elif structure["절"]:
                            structure["절"]["조문"].append(article_obj)
                        elif structure["장"]:
                            structure["장"]["조문"].append(article_obj)
                        elif structure["편"]:
                            structure["편"]["조문"].append(article_obj)
                        else:
                            result["조문"].append(article_obj)

                        # 현재 조문 추적
                        structure["current_article"] = article_obj
                        structure["current_hang"] = None
                        structure["current_ho"] = None

                # 항 처리
                elif "pty1_de2_1" in css_class:
                    hang_match = re.match(r'^([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])\s*(.*)', text)
                    if hang_match:
                        hang_obj = {"항번호": hang_match.group(1), "내용": hang_match.group(2), "세부": []}
                    else:
                        hang_obj = {"항번호": "", "내용": text, "세부": []}

                    if structure.get("current_article"):
                        structure["current_article"]["내용"].append(hang_obj)
                    structure["current_hang"] = hang_obj
                    structure["current_ho"] = None

                # 호 처리
                elif "pty1_de2h" in css_class:
                    ho_match = re.match(r'^(\d+)\.\s*(.*)', text)
                    if ho_match:
                        ho_obj = {"호": ho_match.group(1), "내용": ho_match.group(2), "세부": []}
                    else:
                        ho_obj = {"호": "", "내용": text, "세부": []}

                    if structure.get("current_hang"):
                        structure["current_hang"]["세부"].append(ho_obj)
                    elif structure.get("current_article"):
                        structure["current_article"]["내용"].append(ho_obj)
                    structure["current_ho"] = ho_obj

                # 목 처리
                elif "pty1_de3" in css_class:
                    mok_match = re.match(r'^([가나다라마바사아자차카타파하])\.\s*(.*)', text)
                    if mok_match:
                        mok_obj = {"목": mok_match.group(1), "내용": mok_match.group(2)}
                    else:
                        mok_obj = {"목": "", "내용": text}

                    if structure.get("current_ho"):
                        structure["current_ho"]["세부"].append(mok_obj)
                    elif structure.get("current_hang"):
                        structure["current_hang"]["세부"].append(mok_obj)
                    elif structure.get("current_article"):
                        structure["current_article"]["내용"].append(mok_obj)

            # 조문 키 제거 (구조에 포함됨)
            if "구조" in result and not result["조문"]:
                del result["조문"]

        else:
            # 구조 없는 법령: CSS 클래스 기반 파싱
            parsed_articles = parse_law_elements(elements_with_class)
            result["조문"] = parsed_articles

        # 빈 세부 배열 정리
        def clean_empty_arrays(obj):
            if isinstance(obj, dict):
                keys_to_delete = []
                for k, v in obj.items():
                    if isinstance(v, list):
                        if not v:
                            keys_to_delete.append(k)
                        else:
                            for item in v:
                                clean_empty_arrays(item)
                    elif isinstance(v, dict):
                        clean_empty_arrays(v)
                for k in keys_to_delete:
                    if k in ["세부", "장", "절", "관"]:
                        del obj[k]
            elif isinstance(obj, list):
                for item in obj:
                    clean_empty_arrays(item)

        clean_empty_arrays(result)

        # 조문 수 계산
        article_count = len(elements_with_class)

        print(f"크롤링 완료")

        # 출력 디렉토리 생성
        os.makedirs(output_dir, exist_ok=True)

        # JSON 저장
        output_path = os.path.join(output_dir, f"{law_name}.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"저장 완료: {output_path}")

        browser.close()
        return article_count


def main():
    """메인 함수: 모든 시행령 크롤링"""
    url_file = "raw/01_law_ED/02_시행령_URL.txt"
    output_dir = "raw/01_law_ED"

    laws = load_law_urls(url_file)
    print(f"총 {len(laws)}개 시행령 크롤링 예정")

    results = []

    for i, law in enumerate(laws, 1):
        print(f"\n[{i}/{len(laws)}] {law['name']}")
        try:
            count = crawl_law(law["name"], law["url"], output_dir)
            results.append({"법령명": law["name"], "조문수": count, "상태": "성공"})
        except Exception as e:
            print(f"오류 발생: {e}")
            results.append({"법령명": law["name"], "조문수": 0, "상태": f"실패: {e}"})

    print("\n" + "="*60)
    print("크롤링 완료 요약")
    print("="*60)
    for r in results:
        status = "[O]" if r["상태"] == "성공" else "[X]"
        print(f"{status} {r['법령명']}: {r['조문수']}개 조문")


if __name__ == "__main__":
    main()
