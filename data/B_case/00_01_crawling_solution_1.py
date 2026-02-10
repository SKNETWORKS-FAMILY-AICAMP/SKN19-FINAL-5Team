"""
KCA 품목별 피해구제사례 크롤러 (POST 방식, 상세 내용 포함)
https://www.kca.go.kr/odr/cm/in/exmplPgItem.do
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import requests
import json
import time
import sys
import io
from datetime import datetime
import os
import re

# Windows 인코딩 문제 해결
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 설정
BASE_URL = "https://www.kca.go.kr/odr/cm/in/exmplPgItem.do"
DETAIL_URL = "https://www.kca.go.kr/odr/cm/cm/boardsDtl.do"
ITEMS_PER_PAGE = 10
TOTAL_ITEMS = 705  # 전체 데이터
TOTAL_PAGES = (TOTAL_ITEMS + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
MAX_RETRIES = 3

# 저장 경로 (상대 경로)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "01_B_parsed", "02_01_SolutionCase")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "solution_case_1.json")


def create_driver():
    """Selenium WebDriver 생성"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')

    driver = webdriver.Chrome(options=chrome_options)
    return driver


def get_list_page_data(driver, page_num):
    """목록 페이지에서 게시글 정보 추출"""
    for attempt in range(MAX_RETRIES):
        try:
            if page_num == 1:
                url = BASE_URL
            else:
                url = f"{BASE_URL}?pageIndex={page_num}"

            driver.get(url)

            wait = WebDriverWait(driver, 10)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody")))
            time.sleep(2)

            soup = BeautifulSoup(driver.page_source, 'html.parser')
            table = soup.find('table')

            if not table:
                return []

            tbody = table.find('tbody')
            rows = tbody.find_all('tr') if tbody else []

            posts_info = []

            for idx, row in enumerate(rows):
                cols = row.find_all('td')
                if len(cols) >= 4:
                    number = cols[0].get_text(strip=True)
                    title = cols[1].get_text(strip=True)
                    source = cols[2].get_text(strip=True)
                    views = cols[3].get_text(strip=True).replace(',', '')

                    link = row.find('a')
                    if link:
                        onclick = link.get('onclick', '')

                        seq = ''
                        brd_id = ''

                        match1 = re.search(r'fn_view_bbd\("([^"]+)",\s*"([^"]+)"\)', onclick)
                        if match1:
                            seq = match1.group(1)
                            brd_id = match1.group(2)
                        else:
                            match2 = re.search(r"fn_view_bbd\('([^']+)',\s*'([^']+)'\)", onclick)
                            if match2:
                                seq = match2.group(1)
                                brd_id = match2.group(2)

                        if seq and brd_id:
                            posts_info.append({
                                'number': number,
                                'seq': seq,
                                'brd_id': brd_id,
                                'title': title,
                                'source': source,
                                'views': views
                            })

            return posts_info

        except Exception as e:
            print(f"  ⚠ Attempt {attempt + 1}/{MAX_RETRIES} failed for page {page_num}: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(2)
            else:
                return []


def get_detail_data(seq, brd_id):
    """POST 방식으로 상세 페이지 데이터 추출"""
    for attempt in range(MAX_RETRIES):
        try:
            post_data = {
                'seq': seq,
                'brdId': brd_id,
                'pageIndex': '1',
                'searchCondition': '',
                'searchKeyword': '',
                'dataStts': '',
                'multiItmSeq': ''
            }

            response = requests.post(DETAIL_URL, data=post_data, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            detail_data = {}

            # 테이블에서 상세 정보 추출
            table = soup.find('table')
            if table:
                rows = table.find_all('tr')
                for row in rows:
                    th = row.find('th')
                    td = row.find('td')

                    if th and td:
                        key = th.get_text(strip=True)
                        value = td.get_text(strip=True)

                        if key == '수정일':
                            detail_data['update_date'] = value
                        elif key == '조회수':
                            detail_data['views_detail'] = value
                        elif key == '파일첨부':
                            detail_data['file_attachment'] = value

                # 질문/답변은 별도 클래스로 추출
                qna_q = soup.find('tr', class_='qna_q')
                if qna_q:
                    question_td = qna_q.find('td')
                    if question_td:
                        question_span = question_td.find_all('span')
                        if len(question_span) >= 2:
                            detail_data['question'] = question_span[1].get_text(strip=True)

                qna_a = soup.find('tr', class_='qna_a')
                if qna_a:
                    answer_td = qna_a.find('td')
                    if answer_td:
                        answer_span = answer_td.find_all('span')
                        if len(answer_span) >= 2:
                            # <br /> 태그를 유지하면서 텍스트 추출
                            answer_text = answer_span[1].get_text(separator='\n', strip=True)
                            detail_data['answer'] = answer_text

            return detail_data

        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)
            else:
                print(f"    ✗ 상세 데이터 가져오기 실패 (seq: {seq}): {e}")
                return {}


def crawl_all():
    """전체 크롤링"""
    print("=" * 80)
    print("KCA 품목별 피해구제사례 크롤러 - 전체 크롤링")
    print("=" * 80)
    print(f"총 게시글: {TOTAL_ITEMS}개")
    print(f"저장 위치: {OUTPUT_FILE}")
    print("=" * 80)

    start_time = datetime.now()
    print(f"\n크롤링 시작: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    driver = None
    all_data = []

    try:
        print("\nSelenium WebDriver 초기화 중...")
        driver = create_driver()
        print("✓ WebDriver 준비 완료")

        for page_num in range(1, TOTAL_PAGES + 1):
            print(f"\n[Page {page_num}/{TOTAL_PAGES}] 크롤링 중...")

            posts_info = get_list_page_data(driver, page_num)

            if not posts_info:
                print(f"  ⚠ Page {page_num}: 데이터 없음")
                continue

            print(f"  ✓ {len(posts_info)}개 게시글 발견")

            for idx, post in enumerate(posts_info):
                print(f"    [{idx+1}/{len(posts_info)}] Number: {post['number']}, Title: {post['title'][:40]}...")

                # 상세 데이터 가져오기
                detail_data = get_detail_data(post['seq'], post['brd_id'])

                # 합치기
                combined_data = {
                    'number': post['number'],
                    'seq': post['seq'],
                    'brd_id': post['brd_id'],
                    'url': f"{DETAIL_URL}?seq={post['seq']}&brdId={post['brd_id']}",
                    'title': post['title'],
                    'source': post['source'],
                    'views': post['views'],
                    **detail_data
                }

                all_data.append(combined_data)
                time.sleep(0.5)  # 서버 부하 방지

    except KeyboardInterrupt:
        print("\n\n⚠ 사용자에 의해 중단됨")

    except Exception as e:
        print(f"\n\n✗ 오류 발생: {e}")
        import traceback
        traceback.print_exc()

    finally:
        if driver:
            driver.quit()
            print("\n✓ WebDriver 종료됨")

    # 정렬
    print("\n데이터 정렬 중...")
    all_data_sorted = sorted(all_data, key=lambda x: int(x['number']), reverse=True)
    print(f"✓ 정렬 완료 (총 {len(all_data_sorted)}개)")

    # 저장
    print("\n" + "=" * 80)
    print("데이터 저장 중...")

    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_data_sorted, f, ensure_ascii=False, indent=2)

        print(f"✓ 저장 완료: {OUTPUT_FILE}")
        print(f"✓ 총 수집 데이터: {len(all_data_sorted)}개")

    except Exception as e:
        print(f"✗ 저장 실패: {e}")
        return

    # 완료 정보
    end_time = datetime.now()
    elapsed = end_time - start_time

    print("=" * 80)
    print("크롤링 완료!")
    print(f"시작 시간: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"종료 시간: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"소요 시간: {elapsed}")
    print(f"수집 데이터: {len(all_data_sorted)}개")
    print("=" * 80)


if __name__ == "__main__":
    crawl_all()
