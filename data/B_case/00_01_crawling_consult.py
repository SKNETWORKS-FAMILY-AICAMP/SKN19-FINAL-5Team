"""
소비자 상담사례 크롤러 (멀티스레딩 버전)
https://www.consumer.go.kr/user/ftc/consumer/cnsltcase/114/selectCnsltCaseList.do
총 11,342건의 게시글을 크롤링하여 하나의 JSON 파일로 저장
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
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 설정
BASE_URL = "https://www.consumer.go.kr/user/ftc/consumer/cnsltcase/114"
LIST_URL = f"{BASE_URL}/selectCnsltCaseList.do"
DETAIL_URL = f"{BASE_URL}/selectCnsltCaseView.do"
ITEMS_PER_PAGE = 25
TOTAL_ITEMS = 11342
TOTAL_PAGES = (TOTAL_ITEMS + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE  # 454 페이지
MAX_RETRIES = 3
MAX_WORKERS = 5  # 동시 실행 스레드 수

# 저장 경로 (상대 경로)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "01_B_parsed", "01_ConsultCase")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "consult_case.json")
CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "checkpoint.json")

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
                if len(cols) >= 6:
                    number = cols[0].get_text(strip=True)
                    link = row.find('a')

                    if link and 'prgnCnsltCaseSn=' in link.get('href', ''):
                        case_id = link.get('href').split('prgnCnsltCaseSn=')[1].split('&')[0]

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
                    print(f"  ✗ Failed to get page {page_num} after {MAX_RETRIES} attempts: {e}")
                return []


def extract_detail_data(case_id, number):
    """상세 페이지에서 전체 데이터 추출"""
    params = {
        'prgnCnsltCaseSn': case_id,
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
                        value = td.get_text(strip=True)

                        if key == '제목':
                            data['title'] = value
                        elif key == '출처':
                            data['source'] = value
                        elif key == '분류':
                            data['category'] = value
                        elif key == '질문':
                            data['question'] = value
                        elif key == '답변':
                            data['answer'] = value

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

    status = "✓" if detail_data else "✗"

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
            print(f"  ⚠ Failed to save checkpoint: {e}")


def load_checkpoint():
    """체크포인트 로드"""
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
                checkpoint = json.load(f)
                print(f"\n✓ Checkpoint found: {checkpoint['total_collected']} items collected")
                print(f"  Last update: {checkpoint['timestamp']}")
                return checkpoint
        except Exception as e:
            print(f"⚠ Failed to load checkpoint: {e}")

    return None


def crawl_all():
    """전체 크롤링 실행 (멀티스레딩)"""
    print("=" * 80)
    print("소비자 상담사례 크롤러 (멀티스레딩 버전)")
    print("=" * 80)
    print(f"총 게시글: {TOTAL_ITEMS:,}개")
    print(f"총 페이지: {TOTAL_PAGES:,}페이지")
    print(f"동시 스레드: {MAX_WORKERS}개")
    print(f"저장 위치: {OUTPUT_FILE}")
    print("=" * 80)

    # 체크포인트 확인
    checkpoint = load_checkpoint()

    if checkpoint:
        response = input("\n이전 크롤링 데이터를 이어서 진행하시겠습니까? (y/n): ")
        if response.lower() == 'y':
            all_data = checkpoint['data']
            start_page = checkpoint['current_page']
            print(f"\n✓ 재개: Page {start_page}부터 시작")
        else:
            all_data = []
            start_page = 1
            print("\n✓ 처음부터 새로 시작")
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

            if page_num % 50 == 0:
                print(f"  Page {page_num}/{TOTAL_PAGES} 완료... ({len(all_posts)}개 수집)")

        print(f"\n✓ 총 {len(all_posts)}개 게시글 목록 수집 완료")
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
                        print(f"  ✗ Error processing: {e}")

    except KeyboardInterrupt:
        print("\n\n⚠ 사용자에 의해 중단됨")
        print(f"현재까지 수집된 데이터: {len(all_data)}개")
        save_checkpoint(all_data, TOTAL_PAGES)
        print("✓ 체크포인트 저장됨. 나중에 이어서 실행 가능합니다.")
        return

    except Exception as e:
        print(f"\n\n✗ 오류 발생: {e}")
        save_checkpoint(all_data, TOTAL_PAGES)
        print("✓ 체크포인트 저장됨")
        return

    # 최종 저장
    print("\n" + "=" * 80)
    print("최종 데이터 저장 중...")

    try:
        # 디렉토리 생성 (없으면)
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # JSON 파일 저장
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)

        print(f"✓ 저장 완료: {OUTPUT_FILE}")
        print(f"✓ 총 수집 데이터: {len(all_data):,}개")

        # 체크포인트 파일 삭제
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
            print("✓ 체크포인트 파일 삭제됨")

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
    print(f"수집 데이터: {len(all_data):,}개 / {TOTAL_ITEMS:,}개")
    print(f"성공률: {(len(all_data) / TOTAL_ITEMS * 100):.1f}%")
    print("=" * 80)


if __name__ == "__main__":
    crawl_all()
