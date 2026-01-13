#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ISM 청킹 결과의 실제 토큰 수를 KURE-v1 tokenizer로 측정하여 검증

KURE-v1 모델 스펙:
- 최대 시퀀스 길이: 8192 토큰
- 모델명: nlpai-lab/KURE-v1
"""
import json
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple

try:
    from transformers import AutoTokenizer
except ImportError:
    print("Error: transformers 라이브러리가 필요합니다.")
    print("설치: conda activate crawling && pip install transformers")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parents[3]  # -> ism/

# 입력 파일
CHUNK_FILE = BASE_DIR / "data" / "preprocess" / "ism_all_chunks.jsonl"

# KURE-v1 모델 정보
KURE_MODEL = "nlpai-lab/KURE-v1"
MAX_TOKENS = 8192  # KURE-v1 최대 시퀀스 길이

# 현재 청킹 설정 (문자수 기준)
TARGET_CHARS_MIN = 1500
TARGET_CHARS_MAX = 2500
MIN_CHARS = 800
HARD_MAX = 6000


def load_tokenizer():
    """KURE-v1 tokenizer 로드"""
    print(f"Loading tokenizer: {KURE_MODEL}")
    try:
        tokenizer = AutoTokenizer.from_pretrained(KURE_MODEL)
        print("✓ Tokenizer loaded successfully")
        return tokenizer
    except Exception as e:
        print(f"Error loading tokenizer: {e}")
        print("\n대안: 다른 한국어 tokenizer 사용")
        alternatives = [
            "BAAI/bge-m3",  # KURE-v1의 기반 모델
            "klue/bert-base",
        ]
        for alt in alternatives:
            try:
                print(f"Trying {alt}...")
                tokenizer = AutoTokenizer.from_pretrained(alt)
                print(f"✓ Using {alt} as proxy")
                return tokenizer
            except:
                continue
        raise Exception("Could not load any tokenizer")


def count_tokens(tokenizer, text: str) -> int:
    """텍스트의 실제 토큰 수 계산"""
    tokens = tokenizer.encode(text, add_special_tokens=False)
    return len(tokens)


def analyze_chunks(chunk_file: Path, tokenizer) -> Dict:
    """청크 파일 분석"""
    if not chunk_file.exists():
        raise FileNotFoundError(f"File not found: {chunk_file}")
    
    stats = {
        "total_chunks": 0,
        "max_tokens": 0,
        "min_tokens": float("inf"),
        "total_tokens": 0,
        "over_limit": 0,  # 8192 토큰 초과
        "over_hard_max": 0,  # 3000 토큰 초과 (HARD_MAX/2 추정)
        "by_dataset": defaultdict(lambda: {"count": 0, "max": 0, "total": 0}),
        "by_chunk_type": defaultdict(lambda: {"count": 0, "max": 0, "total": 0}),
        "token_distribution": defaultdict(int),  # 토큰 범위별 분포
    }
    
    print(f"\nAnalyzing chunks from {chunk_file}...")
    
    with chunk_file.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"Warning: JSON decode error at line {line_num}: {e}")
                continue
            
            text = chunk.get("text", "")
            if not text:
                continue
            
            # 토큰 수 계산
            token_count = count_tokens(tokenizer, text)
            char_count = len(text)
            
            # 통계 업데이트
            stats["total_chunks"] += 1
            stats["total_tokens"] += token_count
            stats["max_tokens"] = max(stats["max_tokens"], token_count)
            stats["min_tokens"] = min(stats["min_tokens"], token_count)
            
            if token_count > MAX_TOKENS:
                stats["over_limit"] += 1
                print(f"⚠️  Line {line_num}: {token_count} tokens (OVER LIMIT!)")
                print(f"   doc_id: {chunk.get('doc_id')}, chunk_type: {chunk.get('chunk_type')}")
                print(f"   chars: {char_count}, tokens: {token_count}")
            
            # HARD_MAX 추정 (6000자 ≈ 3000 토큰)
            if token_count > 3000:
                stats["over_hard_max"] += 1
            
            # 데이터셋별 통계
            dataset = chunk.get("dataset", "unknown")
            stats["by_dataset"][dataset]["count"] += 1
            stats["by_dataset"][dataset]["max"] = max(
                stats["by_dataset"][dataset]["max"], token_count
            )
            stats["by_dataset"][dataset]["total"] += token_count
            
            # 청크 타입별 통계
            chunk_type = chunk.get("chunk_type", "unknown")
            stats["by_chunk_type"][chunk_type]["count"] += 1
            stats["by_chunk_type"][chunk_type]["max"] = max(
                stats["by_chunk_type"][chunk_type]["max"], token_count
            )
            stats["by_chunk_type"][chunk_type]["total"] += token_count
            
            # 토큰 분포 (100 토큰 단위)
            bucket = (token_count // 100) * 100
            stats["token_distribution"][bucket] += 1
            
            if line_num % 10000 == 0:
                print(f"  Processed {line_num} chunks...")
    
    return stats


def print_report(stats: Dict):
    """분석 결과 리포트 출력"""
    print("\n" + "=" * 80)
    print("ISM 청킹 결과 토큰 수 분석 리포트")
    print("=" * 80)
    
    # 전체 통계
    print("\n[전체 통계]")
    print(f"  총 청크 수: {stats['total_chunks']:,}")
    print(f"  최대 토큰 수: {stats['max_tokens']:,} (한계: {MAX_TOKENS:,})")
    print(f"  최소 토큰 수: {stats['min_tokens']:,}")
    print(f"  평균 토큰 수: {stats['total_tokens'] / stats['total_chunks']:.1f}")
    print(f"  총 토큰 수: {stats['total_tokens']:,}")
    
    # 한계 초과 여부
    print("\n[한계 검증]")
    if stats["over_limit"] > 0:
        print(f"  ⚠️  {MAX_TOKENS} 토큰 초과: {stats['over_limit']}개 청크")
        print(f"     → KURE-v1 모델 한계 초과! 재청킹 필요")
    else:
        print(f"  ✓ {MAX_TOKENS} 토큰 초과: 0개 (안전)")
    
    if stats["over_hard_max"] > 0:
        print(f"  ⚠️  3000 토큰 초과: {stats['over_hard_max']}개 청크")
        print(f"     → 권장 최대 크기(2500 토큰) 초과")
    else:
        print(f"  ✓ 3000 토큰 초과: 0개")
    
    # 데이터셋별 통계
    print("\n[데이터셋별 통계]")
    for dataset, data in sorted(stats["by_dataset"].items()):
        avg = data["total"] / data["count"]
        print(f"  {dataset:15s}: {data['count']:6,} 청크, "
              f"최대 {data['max']:5,} 토큰, 평균 {avg:6.1f} 토큰")
    
    # 청크 타입별 통계
    print("\n[청크 타입별 통계]")
    for chunk_type, data in sorted(stats["by_chunk_type"].items()):
        avg = data["total"] / data["count"]
        print(f"  {chunk_type:15s}: {data['count']:6,} 청크, "
              f"최대 {data['max']:5,} 토큰, 평균 {avg:6.1f} 토큰")
    
    # 토큰 분포
    print("\n[토큰 분포]")
    print("  범위        | 청크 수")
    print("  " + "-" * 30)
    for bucket in sorted(stats["token_distribution"].keys())[:20]:  # 상위 20개만
        count = stats["token_distribution"][bucket]
        bar = "█" * min(50, count // 100)
        print(f"  {bucket:4d}-{bucket+99:4d} 토큰 | {count:6,} {bar}")
    
    # 권장사항
    print("\n[권장사항]")
    avg_tokens = stats["total_tokens"] / stats["total_chunks"]
    chars_per_token = TARGET_CHARS_MAX / (avg_tokens if avg_tokens > 0 else 1)
    
    print(f"  현재 평균: {avg_tokens:.1f} 토큰/청크")
    print(f"  문자/토큰 비율: 약 {chars_per_token:.2f}자/토큰")
    
    if stats["max_tokens"] > MAX_TOKENS:
        print(f"  ⚠️  최대 토큰 수가 한계를 초과했습니다. 재청킹이 필요합니다.")
    elif stats["max_tokens"] > 3000:
        print(f"  ⚠️  일부 청크가 권장 최대 크기(2500 토큰)를 초과합니다.")
        print(f"     → 최대 크기를 줄이거나 더 세밀한 분할을 고려하세요.")
    elif stats["max_tokens"] < 2000:
        print(f"  ℹ️  최대 토큰 수가 {stats['max_tokens']}로, 모델 용량의 약 "
              f"{stats['max_tokens']/MAX_TOKENS*100:.1f}%만 사용 중입니다.")
        print(f"     → 더 긴 청크로 모델 성능을 더 활용할 수 있습니다.")
    else:
        print(f"  ✓ 토큰 수가 적절한 범위에 있습니다.")
    
    print("\n" + "=" * 80)


def main():
    print("=" * 80)
    print("ISM 청킹 결과 토큰 수 검증")
    print("=" * 80)
    
    # Tokenizer 로드
    tokenizer = load_tokenizer()
    
    # 청크 분석
    stats = analyze_chunks(CHUNK_FILE, tokenizer)
    
    # 리포트 출력
    print_report(stats)


if __name__ == "__main__":
    main()
