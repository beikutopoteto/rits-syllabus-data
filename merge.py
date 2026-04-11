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


def main():
    # SCRAPE_YEAR が設定されていれば年度付きファイルを対象にする
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

    # --- 修正前 ---
# for fpath in files:
#     with open(fpath, "r", encoding="utf-8") as f:
#         data = json.load(f)

# --- 修正後 ---
    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except UnicodeDecodeError:
        # UTF-8でダメなら、日本のシステムでよく使われる cp932 で試す
            with open(fpath, "r", encoding="cp932") as f:
                data = json.load(f)

        faculty = data.get("faculty", "unknown")
        courses = data.get("courses", [])
        faculties_found.append(faculty)

        for c in courses:
            key = f"{c['code']}_{c['dayPeriod']}_{c['term']}"
            if key not in seen_keys:
                seen_keys.add(key)
                all_courses.append(c)

        print(f"  {faculty}: {len(courses)}件")

    # 統合ファイルを出力
    year = datetime.now().year
    # 最初のファイルから年度を取得
    # --- 修正前 ---
# if files:
#     with open(files[0], "r", encoding="utf-8") as f:
#         first = json.load(f)
#         year = first.get("year", year)

# --- 修正後 ---
    if files:
        try:
            with open(files[0], "r", encoding="utf-8") as f:
                 first = json.load(f)
        except UnicodeDecodeError:
            with open(files[0], "r", encoding="cp932") as f:
                 first = json.load(f)
        year = first.get("year", year)

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

    # index.json も生成（メタデータのみ、軽量）
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
    print(f"学部数: {len(faculties_found)}")
    print(f"出力: {output_path}, {index_path}")


if __name__ == "__main__":
    main()
