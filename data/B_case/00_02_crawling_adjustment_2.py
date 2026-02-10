"""
분쟁조정 사례 크롤러 (멀티스레딩 버전)
https://www.consumer.go.kr/user/ftc/consumer/trublmdatcase/116/selectTrublMdatCaseList.do
총 2,466건의 게시글을 크롤링하여 하나의 JSON 파일로 저장
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import sys
import io
from datetime import datetime
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Windows 인코딩 문제 해결
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except AttributeError:
    pass  # 이미 래핑된 경우

# 설정
BASE_URL = "https://www.consumer.go.kr/user/ftc/consumer/trublmdatcase/116"
LIST_URL = f"{BASE_URL}/selectTrublMdatCaseList.do"
DETAIL_URL = f"{BASE_URL}/selectTrublMdatCaseView.do"
ITEMS_PER_PAGE = 25
TOTAL_ITEMS = 2466  # 총 게시글 수
TOTAL_PAGES = (TOTAL_ITEMS + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE  # 99 페이지
MAX_RETRIES = 3
MAX_WORKERS = 5  # 동시 실행 스레드 수

# 저장 경로 (상대 경로)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "01_B_parsed", "02_02_AdjustmentCase")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "adjustment_case_2.json")
CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "checkpoint_adj2.json")

# 스레드 안전을 위한 락
print_lock = threading.Lock()
data_lock = threading.Lock()


def get_list_page_data(page_num):
    """목록 페이지에서 게시글 정보 추출 (number + case_id)"""
    params = {
        'page': str(page_num),
        'row': str(ITEMS_PER_PAGE)
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(LIST_URL, params=params, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            table = soup.find('table')

            if not table:
                return []

            tbody = table.find('tbody')
            rows = tbody.find_all('tr') if tbody else table.find_all('tr')[1:]

            posts_info = []

            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    number = cols[0].get_text(strip=True)
                    link = row.find('a')

                    if link and 'trublMdatCaseSn=' in link.get('href', ''):
                        case_id = link.get('href').split('trublMdatCaseSn=')[1].split('&')[0]

                        posts_info.append({
                            'number': number,
                            'case_id': case_id
                        })

            return posts_info

        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)
            else:
                with print_lock:
                    print(f"  ERROR Failed to get page {page_num} after {MAX_RETRIES} attempts: {e}")
                return []


def clean_ambiguous_unicode(text):
    """ambiguous unicode 문자를 일반 문자로 변환"""
    if not isinstance(text, str):
        return text

    # 전각 괄호 → 반각 괄호
    text = text.replace('「', '"').replace('」', '"')
    text = text.replace('『', '"').replace('』', '"')

    # Curly quotes → Straight quotes
    text = text.replace('\u2018', "'").replace('\u2019', "'")  # ' '
    text = text.replace('\u201C', '"').replace('\u201D', '"')  # " "

    # Bullet → Asterisk
    text = text.replace('\u2022', '*')  # •

    # Full-width forms → ASCII
    text = text.replace('\uff08', '(').replace('\uff09', ')')  # （ ）
    text = text.replace('\uff1a', ':')  # ：
    text = text.replace('\u3000', ' ')  # Full-width space

    # Special dashes → Hyphen
    text = text.replace('\u2013', '-').replace('\u2014', '-')  # – —

    return text


def extract_detail_data(case_id, number):
    """상세 페이지에서 전체 데이터 추출"""
    params = {
        'trublMdatCaseSn': case_id,
        'page': '1',
        'row': '25'
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(DETAIL_URL, params=params, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            data = {
                'number': number,
                'case_id': case_id,
                'url': response.url
            }

            # 테이블에서 정보 추출
            table = soup.find('table')
            if table:
                rows = table.find_all('tr')

                for row in rows:
                    th = row.find('th')
                    td = row.find('td')

                    if th and td:
                        key = th.get_text(strip=True)
                        value = clean_ambiguous_unicode(td.get_text(strip=True))

                        if key == '제목':
                            data['title'] = value
                        elif key == '출처':
                            data['source'] = value
                        elif key == '분류':
                            data['category'] = value
                        elif key == '조회수':
                            data['views'] = value
                        elif key == '사건개요':
                            data['case_summary'] = value
                        elif key == '당사자 주장':  # 띄어쓰기 있음
                            data['party_claims'] = value
                        elif key == '당사자주장':  # 띄어쓰기 없음 (예비)
                            data['party_claims'] = value
                        elif key == '판단':
                            data['judgment'] = value
                        elif key == '결정사항':
                            data['decision'] = value
                        elif key == '관련법률':
                            data['related_laws'] = value

            return data

        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)
            else:
                return None


def process_post(post, total_processed, total_items):
    """개별 게시글 처리 (스레드에서 실행)"""
    detail_data = extract_detail_data(post['case_id'], post['number'])

    with data_lock:
        current = total_processed[0]
        total_processed[0] += 1
        progress = (current / total_items) * 100

    status = "OK" if detail_data else "ERROR"

    with print_lock:
        print(f"  [{current}/{total_items}] ({progress:.1f}%) "
              f"Number: {post['number']}, Case ID: {post['case_id']} {status}")

    return detail_data


def save_checkpoint(data, current_page):
    """체크포인트 저장 (중단 시 재개용)"""
    checkpoint = {
        'timestamp': datetime.now().isoformat(),
        'current_page': current_page,
        'total_collected': len(data),
        'data': data
    }

    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
            json.dump(checkpoint, f, ensure_ascii=False, indent=2)
    except Exception as e:
        with print_lock:
            print(f"  WARNING Failed to save checkpoint: {e}")


def load_checkpoint():
    """체크포인트 로드"""
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
                checkpoint = json.load(f)
                print(f"\nOK Checkpoint found: {checkpoint['total_collected']} items collected")
                print(f"  Last update: {checkpoint['timestamp']}")
                return checkpoint
        except Exception as e:
            print(f"WARNING Failed to load checkpoint: {e}")

    return None


def crawl_all():
    """전체 크롤링 실행 (멀티스레딩)"""
    print("=" * 80)
    print("분쟁조정 사례 크롤러 (멀티스레딩 버전)")
    print("=" * 80)
    print(f"총 게시글: {TOTAL_ITEMS:,}개")
    print(f"총 페이지: {TOTAL_PAGES:,}페이지")
    print(f"동시 스레드: {MAX_WORKERS}개")
    print(f"저장 위치: {OUTPUT_FILE}")
    print("=" * 80)

    # 체크포인트 확인
    checkpoint = load_checkpoint()

    if checkpoint:
        # 자동으로 재개하지 않고 처음부터 시작
        all_data = []
        start_page = 1
        print("\nOK 처음부터 새로 시작")
    else:
        all_data = []
        start_page = 1

    start_time = datetime.now()
    total_processed = [len(all_data)]  # 리스트로 감싸서 mutable하게 만듦

    print(f"\n크롤링 시작: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    try:
        # Phase 1: 모든 페이지에서 게시글 목록 수집
        print("\n[Phase 1] 게시글 목록 수집 중...")
        all_posts = []

        for page_num in range(start_page, TOTAL_PAGES + 1):
            posts_info = get_list_page_data(page_num)
            if posts_info:
                all_posts.extend(posts_info)

            if page_num % 10 == 0:
                print(f"  Page {page_num}/{TOTAL_PAGES} 완료... ({len(all_posts)}개 수집)")

        print(f"\nOK 총 {len(all_posts)}개 게시글 목록 수집 완료")
        print("\n[Phase 2] 상세 데이터 수집 중 (멀티스레딩)...")
        print("=" * 80)

        # Phase 2: 멀티스레딩으로 상세 데이터 수집
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # 모든 작업 제출
            futures = {
                executor.submit(process_post, post, total_processed, TOTAL_ITEMS): post
                for post in all_posts
            }

            # 완료된 작업 처리
            for future in as_completed(futures):
                try:
                    detail_data = future.result()
                    if detail_data:
                        with data_lock:
                            all_data.append(detail_data)

                        # 100개마다 체크포인트 저장
                        if len(all_data) % 100 == 0:
                            save_checkpoint(all_data, TOTAL_PAGES)

                except Exception as e:
                    with print_lock:
                        print(f"  ERROR Error processing: {e}")

    except KeyboardInterrupt:
        print("\n\nWARNING 사용자에 의해 중단됨")
        print(f"현재까지 수집된 데이터: {len(all_data)}개")
        save_checkpoint(all_data, TOTAL_PAGES)
        print("OK 체크포인트 저장됨. 나중에 이어서 실행 가능합니다.")
        return

    except Exception as e:
        print(f"\n\nERROR 오류 발생: {e}")
        save_checkpoint(all_data, TOTAL_PAGES)
        print("OK 체크포인트 저장됨")
        return

    # number를 정수로 변환하여 내림차순 정렬 (큰 값 -> 작은 값)
    print("\n데이터 정렬 중...")
    all_data_sorted = sorted(all_data, key=lambda x: int(x['number']), reverse=True)
    print(f"OK 정렬 완료 (number: {all_data_sorted[0]['number']} → {all_data_sorted[-1]['number']})")

    # 최종 저장
    print("\n" + "=" * 80)
    print("최종 데이터 저장 중...")

    try:
        # 디렉토리 생성 (없으면)
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # JSON 파일 저장
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_data_sorted, f, ensure_ascii=False, indent=2)

        print(f"OK 저장 완료: {OUTPUT_FILE}")
        print(f"OK 총 수집 데이터: {len(all_data_sorted):,}개")

        # 체크포인트 파일 삭제
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
            print("OK 체크포인트 파일 삭제됨")

    except Exception as e:
        print(f"ERROR 저장 실패: {e}")
        return

    # 완료 정보
    end_time = datetime.now()
    elapsed = end_time - start_time

    print("=" * 80)
    print("크롤링 완료!")
    print(f"시작 시간: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"종료 시간: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"소요 시간: {elapsed}")
    print(f"수집 데이터: {len(all_data_sorted):,}개 / {TOTAL_ITEMS:,}개")
    print(f"성공률: {(len(all_data_sorted) / TOTAL_ITEMS * 100):.1f}%")
    print("=" * 80)


if __name__ == "__main__":
    crawl_all()
