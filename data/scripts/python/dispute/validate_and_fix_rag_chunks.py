#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Validate and normalize RAG chunk JSONL files per kjw/docs/embedding.md (3.1-3.3).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


MIN_CHARS_DEFAULT = 80
MAX_CHARS_DEFAULT = 6000
WINDOW_CHARS_DEFAULT = 2000
OVERLAP_CHARS_DEFAULT = 200

SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def normalize_text(text: str) -> str:
    if text is None:
        return ""
    text = text.replace("\n", " ").replace("\t", " ")
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def split_sentences(text: str) -> List[str]:
    if not text:
        return []
    parts = [p.strip() for p in SENT_SPLIT_RE.split(text) if p.strip()]
    return parts or [text.strip()]


def split_long_text(
    text: str, max_chars: int, window_chars: int, overlap_chars: int
) -> List[str]:
    if len(text) <= max_chars:
        return [text]
    window_chars = min(window_chars, max_chars)
    sentences = split_sentences(text)
    chunks: List[str] = []
    buf = ""
    for sent in sentences:
        if len(sent) > window_chars:
            if buf:
                chunks.append(buf.strip())
                buf = ""
            for i in range(0, len(sent), window_chars):
                part = sent[i : i + window_chars].strip()
                if part:
                    chunks.append(part)
            continue
        if not buf:
            buf = sent
            continue
        if len(buf) + 1 + len(sent) <= window_chars:
            buf = f"{buf} {sent}"
            continue
        chunks.append(buf.strip())
        if overlap_chars > 0:
            overlap = buf[-overlap_chars:]
            buf = f"{overlap} {sent}".strip()
        else:
            buf = sent
    if buf:
        chunks.append(buf.strip())
    return [c for c in chunks if c]


def _expected_case_uid(record: Dict) -> str:
    source = record.get("source", "")
    case_index = record.get("case_index", "")
    return f"{source}:{case_index}"


def _is_normalized(text: str) -> bool:
    if text is None:
        return True
    return (
        "\n" not in text
        and "\t" not in text
        and text == text.strip()
        and not re.search(r"\s{2,}", text)
    )


def _record_key(record: Dict) -> Tuple[str, str]:
    case_uid = record.get("case_uid") or _expected_case_uid(record)
    chunk_type = record.get("chunk_type", "")
    return case_uid, chunk_type


def _clone_with_text(record: Dict, text: str, drop: bool) -> Dict:
    new_record = dict(record)
    new_record["text"] = text
    new_record["text_len"] = len(text)
    new_record["drop"] = drop
    return new_record


def _expand_record(
    record: Dict, max_chars: int, window_chars: int, overlap_chars: int, min_chars: int
) -> List[Dict]:
    text = record.get("text", "")
    if len(text) < min_chars:
        return [_clone_with_text(record, text, True)]
    if len(text) <= max_chars:
        return [_clone_with_text(record, text, False)]
    parts = split_long_text(text, max_chars, window_chars, overlap_chars)
    return [_clone_with_text(record, part, False) for part in parts]


def _coerce_record(record: Dict) -> Dict:
    new_record = dict(record)
    new_record["case_uid"] = _expected_case_uid(new_record)
    return new_record


def process_records(
    records: Iterable[Dict],
    min_chars: int,
    max_chars: int,
    window_chars: int,
    overlap_chars: int,
) -> Iterable[Dict]:
    pending = None
    for record in records:
        record = _coerce_record(record)
        record["text"] = normalize_text(record.get("text", ""))
        record["text_len"] = len(record["text"])
        if pending is None:
            pending = record
            continue
        if (
            len(pending.get("text", "")) < min_chars
            and _record_key(pending) == _record_key(record)
        ):
            merged = f"{pending.get('text', '')} {record.get('text', '')}".strip()
            record["text"] = merged
            record["text_len"] = len(merged)
            pending = record
            continue
        yield from _expand_record(pending, max_chars, window_chars, overlap_chars, min_chars)
        pending = record
    if pending is not None:
        yield from _expand_record(pending, max_chars, window_chars, overlap_chars, min_chars)


def assign_ids(records: Iterable[Dict]) -> Iterable[Dict]:
    counters: Dict[Tuple[str, str], int] = {}
    for record in records:
        case_uid = record.get("case_uid") or _expected_case_uid(record)
        chunk_type = record.get("chunk_type", "")
        key = (case_uid, chunk_type)
        counters[key] = counters.get(key, 0) + 1
        seq = counters[key]
        record["case_uid"] = case_uid
        record["seq"] = seq
        record["chunk_uid"] = f"{case_uid}:{chunk_type}:{seq:04d}"
        yield record


def iter_jsonl(path: Path) -> Iterable[Dict]:
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no} invalid json: {exc}") from exc


def validate_file(path: Path, min_chars: int, max_chars: int) -> Dict[str, int]:
    stats = {
        "total": 0,
        "missing_case_uid": 0,
        "missing_chunk_uid": 0,
        "missing_seq": 0,
        "case_uid_mismatch": 0,
        "chunk_uid_mismatch": 0,
        "not_normalized": 0,
        "short_text": 0,
        "long_text": 0,
    }
    for record in iter_jsonl(path):
        stats["total"] += 1
        expected_case_uid = _expected_case_uid(record)
        case_uid = record.get("case_uid")
        chunk_uid = record.get("chunk_uid")
        seq = record.get("seq")
        if not case_uid:
            stats["missing_case_uid"] += 1
        elif case_uid != expected_case_uid:
            stats["case_uid_mismatch"] += 1
        if not chunk_uid:
            stats["missing_chunk_uid"] += 1
        else:
            chunk_type = record.get("chunk_type", "")
            expected_chunk_uid = (
                f"{expected_case_uid}:{chunk_type}:{int(seq):04d}"
                if isinstance(seq, int)
                else None
            )
            if expected_chunk_uid and chunk_uid != expected_chunk_uid:
                stats["chunk_uid_mismatch"] += 1
        if seq is None:
            stats["missing_seq"] += 1
        text = record.get("text", "")
        if not _is_normalized(text):
            stats["not_normalized"] += 1
        text_len = len(text or "")
        if text_len < min_chars:
            stats["short_text"] += 1
        if text_len > max_chars:
            stats["long_text"] += 1
    return stats


def write_jsonl(path: Path, records: Iterable[Dict]) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", nargs="+", required=True, help="Input JSONL files")
    ap.add_argument("--output-dir", help="Directory for normalized outputs")
    ap.add_argument("--report-only", action="store_true", help="Only report compliance")
    ap.add_argument("--min-chars", type=int, default=MIN_CHARS_DEFAULT)
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS_DEFAULT)
    ap.add_argument("--window-chars", type=int, default=WINDOW_CHARS_DEFAULT)
    ap.add_argument("--overlap-chars", type=int, default=OVERLAP_CHARS_DEFAULT)
    args = ap.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else None
    if output_dir and not args.report_only:
        output_dir.mkdir(parents=True, exist_ok=True)

    for input_path in args.input:
        path = Path(input_path)
        stats = validate_file(path, args.min_chars, args.max_chars)
        print(f"[REPORT] {path}")
        for key, value in stats.items():
            print(f"  {key}: {value}")
        if args.report_only:
            continue
        records = iter_jsonl(path)
        processed = process_records(
            records,
            min_chars=args.min_chars,
            max_chars=args.max_chars,
            window_chars=args.window_chars,
            overlap_chars=args.overlap_chars,
        )
        processed = assign_ids(processed)
        if output_dir:
            out_name = path.name.replace(".jsonl", "_normalized.jsonl")
            out_path = output_dir / out_name
        else:
            out_path = path.with_name(path.stem + "_normalized.jsonl")
        count = write_jsonl(out_path, processed)
        print(f"  -> wrote {count} records to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
