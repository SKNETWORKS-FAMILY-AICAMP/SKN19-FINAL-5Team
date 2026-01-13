#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Re-chunk parties_claim and judgment in kca_final_chunks.jsonl.
Uses case_no as id and splits by headings first, then size fallback.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable, List, Dict, Any


HEADING_RE = re.compile(
    r"^\s*(?:"
    r"(?:[가나다라마바사아자차카타파하])\s*[.)](?=\s*[^\d\s])"
    r"|(?:[1-9][0-9]?)\s*[.)](?=\s*[^\d\s])"
    r"|(?:[IVX]{1,4})\s*[.)](?=\s*[^\d\s])"
    r"|(?:[A-Z])\s*[.)](?=\s*[^\d\s])"
    r"|○(?=\s*[^\d\s])"
    r")\s+"
)
MM_DOT_RE = re.compile(r"(?:0?[1-9]|1[0-2])\.\s*$")
DD_START_RE = re.compile(r"^\s*(?:0?[1-9]|[12]\d|3[01])\.(?=\s|$)")


def _is_split_mmdd(prev_line: str, cur_line: str) -> bool:
    return bool(MM_DOT_RE.search(prev_line.strip()) and DD_START_RE.match(cur_line))


def split_by_headings(text: str) -> List[str]:
    lines = text.splitlines()
    blocks: List[List[str]] = []
    current: List[str] = []
    prev_line = ""
    for line in lines:
        is_heading = bool(HEADING_RE.match(line))
        if is_heading and re.search(r"\d{4}\.\s*\d{1,2}\.$", prev_line.strip()):
            is_heading = False
        if is_heading and _is_split_mmdd(prev_line, line):
            is_heading = False
        if is_heading:
            if current:
                blocks.append(current)
            current = [line]
        else:
            current.append(line)
        prev_line = line
    if current:
        blocks.append(current)
    return ["\n".join(block).strip() for block in blocks if "\n".join(block).strip()]


def split_by_paragraphs(text: str) -> List[str]:
    paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paras:
        return [text.strip()] if text.strip() else []
    merged: List[str] = []
    i = 0
    while i < len(paras):
        cur = paras[i]
        if i + 1 < len(paras):
            if re.search(r"\d{4}\.\s*\d{1,2}\.$", cur) and re.match(r"^\d{1,2}\.", paras[i + 1]):
                cur = f"{cur} {paras[i + 1].lstrip()}"
                i += 1
            elif MM_DOT_RE.search(cur) and DD_START_RE.match(paras[i + 1]):
                cur = f"{cur} {paras[i + 1].lstrip()}"
                i += 1
        merged.append(cur)
        i += 1
    return merged


def split_by_sentences(text: str) -> List[str]:
    parts: List[str] = []
    buf: List[str] = []
    n = len(text)
    for i, ch in enumerate(text):
        buf.append(ch)
        if ch in ".!?":
            prev = text[i - 1] if i > 0 else ""
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            next_nonspace = text[j] if j < n else ""
            if ch == "." and prev.isdigit() and next_nonspace.isdigit():
                continue
            if ch == ".":
                tail = "".join(buf).strip()
                if re.search(r"\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.$", tail):
                    continue
                if re.search(r"\d{4}\.\s*\d{1,2}\.$", tail):
                    continue
            if j == i + 1 or (j < n and text[j - 1].isspace()):
                parts.append("".join(buf).strip())
                buf = []
    if buf:
        tail = "".join(buf).strip()
        if tail:
            parts.append(tail)
    merged: List[str] = []
    i = 0
    date_only_re = re.compile(r"^\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.$|^\d{4}\.\s*\d{1,2}\.$")
    while i < len(parts):
        part = parts[i]
        if date_only_re.match(part) and i + 1 < len(parts):
            merged.append(f"{part} {parts[i + 1]}".strip())
            i += 2
            continue
        merged.append(part)
        i += 1
    return merged


def group_sentences(sentences: List[str], target_chars: int) -> List[str]:
    if not sentences:
        return []
    groups: List[str] = []
    buf: List[str] = []
    total = 0
    for sent in sentences:
        if not sent:
            continue
        add_len = len(sent) + (1 if buf else 0)
        if buf and total + add_len > target_chars:
            groups.append(" ".join(buf).strip())
            buf = [sent]
            total = len(sent)
        else:
            buf.append(sent)
            total += add_len
    if buf:
        groups.append(" ".join(buf).strip())
    return groups


def merge_date_fragments(units: List[str]) -> List[str]:
    merged: List[str] = []
    for unit in units:
        if not merged:
            merged.append(unit)
            continue
        prev = merged[-1].rstrip()
        cur = unit.lstrip()
        if re.search(r"\d{4}\.\s*\d{1,2}\.$", prev) and re.match(r"^\d{1,2}\.", cur):
            merged[-1] = f"{prev} {cur}"
        elif MM_DOT_RE.search(prev) and DD_START_RE.match(cur):
            merged[-1] = f"{prev} {cur}"
        else:
            merged.append(unit)
    return merged


def _overlap_units(units: List[str], max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    total = 0
    kept: List[str] = []
    for unit in reversed(units):
        unit_len = len(unit)
        if total + unit_len > max_chars:
            break
        kept.append(unit)
        total += unit_len
    kept.reverse()
    return "\n\n".join(kept).strip()


def chunk_by_size(texts: Iterable[str], max_chars: int, overlap_chars: int) -> List[str]:
    chunks: List[str] = []
    buf_units: List[str] = []
    for part in texts:
        if not part:
            continue
        if not buf_units:
            buf_units = [part]
            continue
        current_len = sum(len(u) for u in buf_units) + 2 * (len(buf_units) - 1)
        if current_len + 2 + len(part) <= max_chars:
            buf_units.append(part)
            continue
        chunks.append("\n\n".join(buf_units).strip())
        if overlap_chars > 0:
            overlap = _overlap_units(buf_units, overlap_chars)
            buf_units = [overlap, part] if overlap else [part]
        else:
            buf_units = [part]
    if buf_units:
        tail = "\n\n".join(buf_units).strip()
        if tail:
            chunks.append(tail)
    return chunks


def rechunk_text(text: str, max_chars: int, overlap_chars: int) -> List[str]:
    blocks = split_by_headings(text)
    if not blocks:
        return []
    sized: List[str] = []
    for block in blocks:
        if len(block) <= max_chars:
            sized.append(block)
        else:
            units: List[str] = []
            for para in split_by_paragraphs(block):
                if len(para) <= max_chars:
                    units.append(para)
                else:
                    sentences = split_by_sentences(para)
                    units.extend(group_sentences(sentences, target_chars=min(800, max_chars)))
            units = merge_date_fragments(units)
            sized.extend(chunk_by_size(units, max_chars, overlap_chars))
    return sized


def process_file(
    in_path: Path,
    out_path: Path,
    max_chars: int,
    overlap_chars: int,
    target_types: Iterable[str],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    target_set = set(target_types)

    with in_path.open("r", encoding="utf-8") as f_in, out_path.open("w", encoding="utf-8") as f_out:
        for line in f_in:
            if not line.strip():
                continue
            obj = json.loads(line)
            chunk_type = obj.get("chunk_type")
            if chunk_type not in target_set:
                f_out.write(json.dumps(obj, ensure_ascii=False) + "\n")
                continue

            text = (obj.get("text") or "").strip()
            if not text:
                continue

            chunks = rechunk_text(text, max_chars=max_chars, overlap_chars=overlap_chars)
            if not chunks:
                continue

            for idx, chunk in enumerate(chunks, start=1):
                record: Dict[str, Any] = dict(obj)
                record["id"] = obj.get("case_no")
                record["chunk_index"] = idx
                record["text"] = chunk
                f_out.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Rechunk KCA chunks by headings and size.")
    ap.add_argument(
        "--input",
        default="kjw/data/preprocess/kca_final_chunks.jsonl",
        help="Input chunks.jsonl path",
    )
    ap.add_argument(
        "--output",
        default="kjw/data/preprocess/kca_final_chunks_rechunked.jsonl",
        help="Output rechunked jsonl path",
    )
    ap.add_argument("--max-chars", type=int, default=2000, help="Max chars per chunk")
    ap.add_argument("--overlap-chars", type=int, default=200, help="Overlap chars between chunks")
    ap.add_argument(
        "--types",
        default="parties_claim,judgment",
        help="Comma-separated chunk types to rechunk",
    )
    args = ap.parse_args()

    process_file(
        Path(args.input),
        Path(args.output),
        max_chars=args.max_chars,
        overlap_chars=args.overlap_chars,
        target_types=[t.strip() for t in args.types.split(",") if t.strip()],
    )


if __name__ == "__main__":
    main()
