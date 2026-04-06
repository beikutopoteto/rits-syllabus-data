#!/usr/bin/env python3
"""
立命館大学シラバス スクレイピングスクリプト
Playwright を使用してシラバスサイトからデータを取得し、JSON形式で保存する。
GitHub Actions で定期実行し、GitHub Pages で公開する想定。
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone

from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

BASE_URL = "https://syllabus.ritsumei.ac.jp/syllabus/s/?language=ja"

# 学部一覧（学部のみ、研究科は除外）
FACULTIES = [
    "法学部",
    "経済学部",
    "経営学部",
    "産業社会学部",
    "国際関係学部",
    "政策科学部",
    "文学部",
    "デザイン・アート学部",
    "映像学部",
    "総合心理学部",
    "理工学部",
    "グローバル教養学部",
    "食マネジメント学部",
    "情報理工学部",
    "生命科学部",
    "薬学部",
    "スポーツ健康科学部",
]

DAYS = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日"]
PERIODS = ["1", "2", "3", "4", "5", "6", "7"]

SEMESTERS = [
    "春セメスター",
    "秋セメスター",
]

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "data")


async def select_combobox(page: Page, button_id: str, value: str):
    """Salesforce Lightning コンボボックスの値を選択する"""
    btn = page.locator(f"#{button_id}")
    await btn.click()
    await page.wait_for_timeout(300)
    # ドロップダウン内のオプションをテキストで検索
    dropdown_id = button_id.replace("combobox-button-", "dropdown-element-")
    dropdown = page.locator(f"#{dropdown_id}")
    option = dropdown.get_by_text(value, exact=True)
    await option.click()
    await page.wait_for_timeout(200)


async def check_checkbox(page: Page, label_text: str):
    """チェックボックスをラベルテキストで選択する"""
    label = page.get_by_label(label_text, exact=True)
    if not await label.is_checked():
        await label.check()
    await page.wait_for_timeout(100)


async def uncheck_all_checkboxes(page: Page, labels: list[str]):
    """指定したラベルのチェックボックスをすべて解除する"""
    for label_text in labels:
        label = page.get_by_label(label_text, exact=True)
        if await label.is_checked():
            await label.uncheck()
        await page.wait_for_timeout(50)


async def extract_table_rows(page: Page) -> list[dict]:
    """検索結果テーブルからデータを抽出する"""
    rows = []
    table = page.locator("lightning-datatable table tbody tr")
    count = await table.count()

    for i in range(count):
        row = table.nth(i)
        cells = row.locator("td")
        cell_count = await cells.count()

        if cell_count < 8:
            continue

        # 最初のセルはチェックボックス列なのでスキップ
        # セル構造: [checkbox, 授業科目名, 学部, 学期, 曜日時限, キャンパス, 教員, 言語, 単位]
        try:
            name_cell = cells.nth(1)
            link = name_cell.locator("a")
            link_count = await link.count()

            course_name_full = await name_cell.inner_text()
            syllabus_path = ""
            if link_count > 0:
                syllabus_path = await link.first.get_attribute("href") or ""

            faculty_text = await cells.nth(2).inner_text()
            term_text = await cells.nth(3).inner_text()
            day_period_text = await cells.nth(4).inner_text()
            campus_text = await cells.nth(5).inner_text()
            instructor_text = await cells.nth(6).inner_text()
            language_text = await cells.nth(7).inner_text()
            credits_text = await cells.nth(8).inner_text() if cell_count > 8 else ""

            # 授業コードと科目名を分離 (例: "92770:ファイナンス（MP） (U1)")
            code = ""
            name = course_name_full.strip()
            if ":" in name:
                parts = name.split(":", 1)
                code = parts[0].strip()
                name = parts[1].strip()

            # シラバスURLを構築
            syllabus_url = ""
            if syllabus_path:
                syllabus_url = f"https://syllabus.ritsumei.ac.jp{syllabus_path}"

            # 教室情報を取得（キャンパスから推測）
            campus = campus_text.strip()

            rows.append({
                "code": code,
                "name": name,
                "faculty": faculty_text.strip(),
                "term": term_text.strip(),
                "dayPeriod": day_period_text.strip(),
                "campus": campus,
                "instructor": instructor_text.strip(),
                "language": language_text.strip(),
                "credits": credits_text.strip(),
                "syllabusUrl": syllabus_url,
            })
        except Exception as e:
            print(f"  [WARN] Row {i} extraction error: {e}", file=sys.stderr)
            continue

    return rows


async def get_total_count(page: Page) -> int:
    """検索結果の総件数を取得する"""
    try:
        count_text = await page.locator("text=/全 \\d+ 件/").first.inner_text()
        # "全 123 件 (1/13ページ)" -> 123
        import re
        match = re.search(r"全\s*(\d+)\s*件", count_text)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return 0


async def scrape_faculty_day_period(
    page: Page,
    faculty: str,
    semester: str,
    day: str,
    period: str,
    year: str,
) -> list[dict]:
    """特定の学部・曜日・時限の授業一覧を取得する"""
    all_courses = []

    try:
        # クリアボタンを押す
        clear_btn = page.get_by_role("button", name="クリア")
        await clear_btn.click()
        await page.wait_for_timeout(500)

        # 学部を選択
        await select_combobox(page, "combobox-button-14", faculty)

        # 年度を選択
        await select_combobox(page, "combobox-button-18", year)

        # 学期を選択
        await select_combobox(page, "combobox-button-22", semester)

        # 曜日チェックボックスを設定
        await uncheck_all_checkboxes(page, DAYS)
        await check_checkbox(page, day)

        # 時限チェックボックスを設定
        await uncheck_all_checkboxes(page, PERIODS)
        await check_checkbox(page, period)

        # 表示件数を50に変更
        select = page.locator("#select-10")
        await select.select_option("50")
        await page.wait_for_timeout(200)

        # 検索実行
        search_btn = page.get_by_role("button", name="検索")
        await search_btn.click()
        await page.wait_for_timeout(2000)

        # 結果を取得
        total = await get_total_count(page)
        if total == 0:
            return []

        print(f"  {faculty} / {semester} / {day} {period}限: {total}件", flush=True)

        # 最初のページを取得
        courses = await extract_table_rows(page)
        all_courses.extend(courses)

        # ページネーション
        while len(all_courses) < total:
            try:
                next_btn = page.get_by_role("button", name="次へ")
                await next_btn.click()
                await page.wait_for_timeout(2000)
                courses = await extract_table_rows(page)
                if not courses:
                    break
                all_courses.extend(courses)
            except Exception:
                break

    except PlaywrightTimeout:
        print(f"  [TIMEOUT] {faculty} / {semester} / {day} {period}限", file=sys.stderr)
    except Exception as e:
        print(f"  [ERROR] {faculty} / {semester} / {day} {period}限: {e}", file=sys.stderr)

    return all_courses


async def main():
    year = os.environ.get("SCRAPE_YEAR", str(datetime.now().year))
    target_faculties = os.environ.get("SCRAPE_FACULTIES", "").split(",") if os.environ.get("SCRAPE_FACULTIES") else FACULTIES
    target_faculties = [f.strip() for f in target_faculties if f.strip()]

    print(f"=== 立命館大学シラバス スクレイピング開始 ===")
    print(f"年度: {year}")
    print(f"対象学部: {len(target_faculties)}学部")
    print(f"出力先: {OUTPUT_DIR}/")
    print()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_courses = []
    seen_keys = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="ja-JP",
        )
        page = await context.new_page()

        # シラバスサイトにアクセス
        await page.goto(BASE_URL, wait_until="networkidle")
        await page.wait_for_timeout(2000)

        for faculty in target_faculties:
            print(f"\n--- {faculty} ---")
            for semester in SEMESTERS:
                for day in DAYS:
                    for period in PERIODS:
                        courses = await scrape_faculty_day_period(
                            page, faculty, semester, day, period, year
                        )
                        for c in courses:
                            # 重複排除キー
                            key = f"{c['code']}_{c['dayPeriod']}_{c['term']}"
                            if key not in seen_keys:
                                seen_keys.add(key)
                                all_courses.append(c)

                        # レート制限対策
                        await page.wait_for_timeout(500)

        await browser.close()

    # 結果を保存
    output = {
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "year": int(year),
        "totalCourses": len(all_courses),
        "courses": all_courses,
    }

    output_path = os.path.join(OUTPUT_DIR, "syllabus.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n=== 完了 ===")
    print(f"取得件数: {len(all_courses)}件")
    print(f"出力ファイル: {output_path}")

    # 学部別にも分割保存
    faculty_data = {}
    for c in all_courses:
        fac = c["faculty"]
        if fac not in faculty_data:
            faculty_data[fac] = []
        faculty_data[fac].append(c)

    for fac, courses in faculty_data.items():
        safe_name = fac.replace("・", "_").replace("（", "(").replace("）", ")")
        fac_path = os.path.join(OUTPUT_DIR, f"syllabus_{safe_name}.json")
        fac_output = {
            "lastUpdated": output["lastUpdated"],
            "year": int(year),
            "faculty": fac,
            "totalCourses": len(courses),
            "courses": courses,
        }
        with open(fac_path, "w", encoding="utf-8") as f:
            json.dump(fac_output, f, ensure_ascii=False, indent=2)

    print(f"学部別ファイル: {len(faculty_data)}ファイル")


if __name__ == "__main__":
    asyncio.run(main())
