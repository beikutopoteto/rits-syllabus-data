#!/usr/bin/env python3
"""
学部別JSONファイルを統合して syllabus.json を生成する。
GitHub Actions の merge ジョブで使用する。
"""

import json
import os
import sys
import glob
from datetime import datetime, timezone

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "data")

def load_json_with_fallback(fpath):
    """
    文字コードエラーを回避しながらJSONを読み込むヘルパー関数
    """
    try:
        # 1. まずは標準の UTF-8 で試す
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (UnicodeDecodeError, json.JSONDecodeError):
        try:
            # 2. ダメなら 日本語Windowsで多い cp932 で試す
            with open(fpath, "r", encoding="cp932") as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            try:
                # 3. それでもダメなら UTF-8 で不明な文字を置換して強引に読む
                # これで文字コード起因の停止は100%防げます
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    return json.load(f)
            except Exception as e:
                print(f"WARNING: Skip file {fpath} due to error: {e}")
                return None

def main():
    year_str = os.environ.get("SCRAPE_YEAR", "").strip()
    year_suffix = f"_{year_str}" if year_str else ""
    pattern = os.path.join(OUTPUT_DIR, f"syllabus_*{year_suffix}.json")
    files = sorted(glob.glob(pattern))

    if not files:
        print("ERROR: No faculty JSON files found", file=sys.stderr)
        sys.exit(1)

    all_courses = []
    seen_keys = set()
    faculties_found = []

    for fpath in files:
        data = load_json_with_fallback(fpath)
        if data is None:
            continue

        faculty = data.get("faculty", "unknown")
        courses = data.get("courses", [])
        
        # 2025年新設学部などでデータが空（0件）の場合はスキップ
        if not courses:
            print(f"  {faculty}: 0件 (Skip)")
            continue

        faculties_found.append(faculty)

        for c in courses:
            key = f"{c['code']}_{c['dayPeriod']}_{c['term']}"
            if key not in seen_keys:
                seen_keys.add(key)
                all_courses.append(c)

        print(f"  {faculty}: {len(courses)}件")

    # 統合ファイルを出力
    year = datetime.now().year
    if files:
        first_data = load_json_with_fallback(files[0])
        if first_data:
            year = first_data.get("year", year)

    output = {
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "year": year,
        "totalCourses": len(all_courses),
        "faculties": faculties_found,
        "courses": all_courses,
    }

    output_filename = f"syllabus_{year}.json" if year_str else "syllabus.json"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # index.json も生成
    def fac_filename(fac: str) -> str:
        safe = fac.replace('・', '_').replace('（', '(').replace('）', ')')
        return f"syllabus_{safe}_{year}.json" if year_str else f"syllabus_{safe}.json"

    index = {
        "lastUpdated": output["lastUpdated"],
        "year": year,
        "totalCourses": len(all_courses),
        "faculties": faculties_found,
        "files": {
            "all": output_filename,
            "byFaculty": {fac: fac_filename(fac) for fac in faculties_found},
        },
    }

    index_path = os.path.join(OUTPUT_DIR, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"\n=== 統合完了 ===")
    print(f"総件数: {len(all_courses)}件")
    print(f"出力: {output_path}")

if __name__ == "__main__":
    main()
