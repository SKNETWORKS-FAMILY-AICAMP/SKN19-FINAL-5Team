"""
검색 API 테스트 스크립트
"""
import requests
import json
import os
from pathlib import Path
from dotenv import load_dotenv

# .env 파일 로드
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# API URL (환경변수 우선, 없으면 로컬)
API_BASE_URL = os.getenv("SEARCH_API_URL", "http://localhost:8000")

def test_health():
    """헬스 체크"""
    print("=" * 80)
    print("1. Health Check")
    print("=" * 80)

    response = requests.get(f"{API_BASE_URL}/health")
    print(f"Status Code: {response.status_code}")
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    print()


def test_stats():
    """통계 조회"""
    print("=" * 80)
    print("2. Database Statistics")
    print("=" * 80)

    response = requests.get(f"{API_BASE_URL}/stats")
    print(f"Status Code: {response.status_code}")
    stats = response.json()

    print(f"\n총 {len(stats['statistics'])}개 그룹:")
    for stat in stats['statistics'][:10]:  # 처음 10개만 출력
        # None 값 처리
        category = stat.get('category') or 'N/A'
        chunk_type = stat.get('chunk_type') or 'N/A'
        print(f"  - {stat['dataset_type']:10} | {category:10} | "
              f"{chunk_type:15} | {stat['total_chunks']:5}개 청크")
    print()


def test_hybrid_search():
    """하이브리드 검색"""
    print("=" * 80)
    print("3. Hybrid Search (BM25 + Vector + RRF)")
    print("=" * 80)

    payload = {
        "query": "환불 거부 시 소비자 권리는?",
        "search_type": "hybrid",
        "top_k": 5
    }

    print(f"Query: {payload['query']}")
    print(f"Search Type: {payload['search_type']}")
    print(f"Top K: {payload['top_k']}\n")

    response = requests.post(f"{API_BASE_URL}/search", json=payload)
    result = response.json()

    print(f"Status Code: {response.status_code}")
    print(f"Total Results: {result['total_results']}")
    print(f"Search Time: {result['search_time_ms']}ms\n")

    for i, item in enumerate(result['results'], 1):
        print(f"[{i}] Score: {item['score']:.4f} | {item['dataset_type']} | {item['chunk_id']}")
        print(f"    Text: {item['text'][:100]}...")
        if item.get('law_name'):
            print(f"    Law: {item['law_name']}")
        if item.get('category'):
            print(f"    Category: {item['category']}")
        print()


def test_vector_search():
    """순수 벡터 검색"""
    print("=" * 80)
    print("4. Vector Search Only")
    print("=" * 80)

    payload = {
        "query": "청약철회권 행사 방법",
        "search_type": "vector",
        "top_k": 5
    }

    print(f"Query: {payload['query']}")
    print(f"Search Type: {payload['search_type']}\n")

    response = requests.post(f"{API_BASE_URL}/search", json=payload)
    print(f"Status Code: {response.status_code}")

    result = response.json()

    # 에러 체크
    if 'error' in result or 'detail' in result:
        print(f"[ERROR] {result.get('error') or result.get('detail')}")
        return

    if 'total_results' not in result:
        print(f"[ERROR] Unexpected response format: {result}")
        return

    print(f"Total Results: {result['total_results']}")
    print(f"Search Time: {result['search_time_ms']}ms\n")

    for i, item in enumerate(result['results'][:3], 1):  # 상위 3개만
        print(f"[{i}] Similarity: {item['score']:.4f}")
        print(f"    {item['text'][:150]}...\n")


def test_filtered_search():
    """필터링 검색"""
    print("=" * 80)
    print("5. Filtered Search (조정 사례만)")
    print("=" * 80)

    payload = {
        "query": "가구 배송 지연 분쟁",
        "search_type": "hybrid",
        "category_filter": "조정",
        "top_k": 5
    }

    print(f"Query: {payload['query']}")
    print(f"Filter: category={payload['category_filter']}\n")

    response = requests.post(f"{API_BASE_URL}/search", json=payload)
    print(f"Status Code: {response.status_code}")

    result = response.json()

    # 에러 체크
    if 'error' in result or 'detail' in result:
        print(f"[ERROR] {result.get('error') or result.get('detail')}")
        return

    print(f"Total Results: {result['total_results']}")
    print(f"Search Time: {result['search_time_ms']}ms\n")

    for i, item in enumerate(result['results'][:3], 1):
        print(f"[{i}] Score: {item['score']:.4f} | Category: {item['category']}")
        print(f"    {item['text'][:100]}...\n")


def test_law_search():
    """법령 검색"""
    print("=" * 80)
    print("6. Law Search (법령만)")
    print("=" * 80)

    payload = {
        "query": "소비자기본법 제16조",
        "search_type": "hybrid",
        "dataset_filter": "law_guide",
        "top_k": 5
    }

    print(f"Query: {payload['query']}")
    print(f"Filter: dataset_type={payload['dataset_filter']}\n")

    response = requests.post(f"{API_BASE_URL}/search", json=payload)
    result = response.json()

    print(f"Total Results: {result['total_results']}")
    print(f"Search Time: {result['search_time_ms']}ms\n")

    for i, item in enumerate(result['results'][:3], 1):
        print(f"[{i}] Score: {item['score']:.4f} | Law: {item.get('law_name', 'N/A')}")
        print(f"    {item['text'][:100]}...\n")


if __name__ == "__main__":
    print("\n")
    print("[TEST] DDoksori Search API Test")
    print("=" * 80)
    print()

    try:
        # 1. 헬스 체크
        test_health()

        # 2. 통계
        test_stats()

        # 3. 하이브리드 검색
        test_hybrid_search()

        # 4. 벡터 검색
        test_vector_search()

        # 5. 필터링 검색
        test_filtered_search()

        # 6. 법령 검색
        test_law_search()

        print("=" * 80)
        print("[SUCCESS] All tests completed!")
        print("=" * 80)

    except requests.exceptions.ConnectionError:
        print("[ERROR] Cannot connect to API server")
        print("   Make sure the API server is running: python 03_01_search_api.py")
    except Exception as e:
        print(f"[ERROR] {e}")
