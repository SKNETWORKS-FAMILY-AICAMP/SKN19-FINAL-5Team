import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]  # → ism/

IN_PATH = BASE_DIR / "data" / "cnslt" / "processed" / "cnslt_cases_114_full.processed.jsonl"
OUT_PATH = BASE_DIR / "data" / "cnslt" / "processed" / "cnslt_cases_114_full.processed.nodate.jsonl"

# 제거할 날짜/시간 관련(추출/파생) 필드들
DROP_TOP_LEVEL = {
    "event_year",
    "time_note",
    "raw_date_text",
    "case_dates",
    "reference_dates",
    "events",
}

# metadata 안에도 혹시 event_year 넣는 경우가 있으면 제거
DROP_METADATA_KEYS = {
    "event_year",
    "event_year_confidence",
    "event_year_source",
}

def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    kept = 0
    with IN_PATH.open("r", encoding="utf-8") as fin, OUT_PATH.open("w", encoding="utf-8") as fout:
        for line in fin:
            if not line.strip():
                continue
            obj = json.loads(line)

            # 1) top-level 날짜 관련 필드 제거
            for k in list(DROP_TOP_LEVEL):
                if k in obj:
                    obj.pop(k, None)

            # 2) metadata 내부 날짜 관련 키 제거(있을 때만)
            md = obj.get("metadata")
            if isinstance(md, dict):
                for k in list(DROP_METADATA_KEYS):
                    if k in md:
                        md.pop(k, None)

            fout.write(json.dumps(obj, ensure_ascii=False) + "\n")
            kept += 1

    print("Wrote:", OUT_PATH)
    print("Lines:", kept)

if __name__ == "__main__":
    main()
