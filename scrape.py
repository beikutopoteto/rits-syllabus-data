#!/usr/bin/env python3
"""
立命館大学シラバス スクレイピングスクリプト
Playwright を使用してシラバスサイトからデータを取得し、JSON形式で保存する。
GitHub Actions で定期実行し、GitHub Pages で公開する想定。

環境変数:
  SCRAPE_FACULTY  - 対象学部名（指定時は単一学部のみ処理）
  SCRAPE_YEAR     - 年度（デフォルト: 現在年度）
  OUTPUT_DIR      - 出力ディレクトリ（デフォルト: data）
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeout

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

# 正しい学期名（サイト上の実際の選択肢）
SEMESTERS = [
    "春学期",
    "秋学期",
]

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "data")

# 詳細ページ並列取得の同時実行数
DETAIL_CONCURRENCY = 15


async def select_combobox_by_label(page: Page, aria_label: str, value: str):
    """aria-labelを使ってコンボボックスを特定し、値を選択する。
    IDはページロードごとに変わるため、ラベルベースで検出する。"""
    btn = page.locator(f"button[role='combobox'][aria-label='{aria_label}']")
    await btn.click()
    await page.wait_for_timeout(500)
    # ドロップダウンのIDをボタンのaria-controlsから取得
    dropdown_id = await btn.get_attribute("aria-controls")
    if dropdown_id:
        dropdown = page.locator(f"#{dropdown_id}")
    else:
        # フォールバック: ボタンIDからドロップダウンIDを推測
        btn_id = await btn.get_attribute("id") or ""
        dropdown_id = btn_id.replace("combobox-button-", "dropdown-element-")
        dropdown = page.locator(f"#{dropdown_id}")
    option = dropdown.get_by_text(value, exact=True)
    await option.click()
    await page.wait_for_timeout(300)


async def check_checkbox(page: Page, label_text: str):
    """チェックボックスをラベルテキストで選択する。
    Salesforce LWCのカスタムチェックボックスはラベルをクリックする必要がある。"""
    cb = page.get_by_label(label_text, exact=True)
    if not await cb.is_checked():
        # ラベル要素をクリックして状態を変更する
        cb_id = await cb.get_attribute("id")
        if cb_id:
            label_el = page.locator(f"label[for='{cb_id}']")
            await label_el.click()
        else:
            await cb.click(force=True)
    await page.wait_for_timeout(100)


async def uncheck_all_checkboxes(page: Page, labels: list[str]):
    """指定したラベルのチェックボックスをすべて解除する"""
    for label_text in labels:
        cb = page.get_by_label(label_text, exact=True)
        if await cb.is_checked():
            cb_id = await cb.get_attribute("id")
            if cb_id:
                label_el = page.locator(f"label[for='{cb_id}']")
                await label_el.click()
            else:
                await cb.click(force=True)
        await page.wait_for_timeout(50)


async def fetch_room_from_detail(context: BrowserContext, syllabus_url: str) -> str:
    """シラバス詳細ページから「授業施設」を取得する。
    別ページを新規タブで開いて取得し、閉じる。"""
    if not syllabus_url:
        return ""
    detail_page = await context.new_page()
    try:
        await detail_page.goto(syllabus_url, wait_until="networkidle", timeout=20000)
        await detail_page.wait_for_timeout(1000)

        # 「授業施設」ラベルの次の要素を取得する
        # 構造: <dt>授業施設</dt><dd>コラーニングⅠ　２０６号教室</dd>
        # または lightning-formatted-text / div などの場合もある
        room = ""

        # 方法1: dl/dt/dd 構造
        try:
            dt_elements = detail_page.locator("dt")
            dt_count = await dt_elements.count()
            for i in range(dt_count):
                dt_text = (await dt_elements.nth(i).inner_text()).strip()
                if "授業施設" in dt_text:
                    # 対応するdd要素を取得
                    dd = detail_page.locator("dd").nth(i)
                    room = (await dd.inner_text()).strip()
                    break
        except Exception:
            pass

        # 方法2: ラベルテキストの隣接要素（Salesforce LWC形式）
        if not room:
            try:
                # "授業施設" テキストを含む要素の親/兄弟から値を取得
                label_el = detail_page.get_by_text("授業施設", exact=True).first
                parent = label_el.locator("xpath=..")
                # 親の次の兄弟要素
                sibling = parent.locator("xpath=following-sibling::*[1]")
                room = (await sibling.inner_text()).strip()
            except Exception:
                pass

        # 方法3: テキスト検索で「授業施設」の後ろのテキストを抽出
        if not room:
            try:
                full_text = await detail_page.inner_text("body")
                match = re.search(r"授業施設\s*\n?\s*(.+?)(?:\n|授業で利用する言語|$)", full_text)
                if match:
                    room = match.group(1).strip()
            except Exception:
                pass

        return room
    except PlaywrightTimeout:
        print(f"  [DETAIL TIMEOUT] {syllabus_url}", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"  [DETAIL ERROR] {syllabus_url}: {e}", file=sys.stderr)
        return ""
    finally:
        await detail_page.close()


async def fetch_rooms_parallel(context: BrowserContext, courses: list[dict]) -> list[dict]:
    """複数授業の詳細ページを並列取得して room フィールドを付与する。"""
    semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)

    async def fetch_one(course: dict) -> dict:
        async with semaphore:
            room = await fetch_room_from_detail(context, course.get("syllabusUrl", ""))
            return {**course, "room": room}

    tasks = [fetch_one(c) for c in courses]
    results = await asyncio.gather(*tasks)
    return list(results)


async def extract_table_rows(page: Page) -> list[dict]:
    """検索結果テーブルからデータを抽出する。
    テーブル構造（検索結果一覧）:
      [0] TD: チェックボックス（空）
      [1] TH: 授業科目名（リンク付き）
      [2] TD: 年度
      [3] TD: 学期
      [4] TD: 開講曜日・時限
      [5] TD: 学部・研究科
      [6] TD: 全担当教員
      [7] TD: 単位数
    ※ キャンパス列は一覧には存在しない（詳細ページのみ）
    """
    rows = []
    table = page.locator("lightning-datatable table tbody tr")
    count = await table.count()

    for i in range(count):
        row = table.nth(i)
        # TD と TH の両方を取得する（授業科目名は TH タグ）
        cells = row.locator("td, th")
        cell_count = await cells.count()

        if cell_count < 7:
            continue

        try:
            # [1] 授業科目名（TH タグ、リンク付き）
            name_cell = cells.nth(1)
            link = name_cell.locator("a")
            link_count = await link.count()

            course_name_full = await name_cell.inner_text()
            syllabus_path = ""
            if link_count > 0:
                syllabus_path = await link.first.get_attribute("href") or ""

            # [3] 学期
            term_text = await cells.nth(3).inner_text()
            # [4] 開講曜日・時限
            day_period_text = await cells.nth(4).inner_text()
            # [5] 学部・研究科
            faculty_text = await cells.nth(5).inner_text()
            # [6] 全担当教員
            instructor_text = await cells.nth(6).inner_text()
            # [7] 単位数（存在する場合）
            credits_text = ""
            if cell_count > 7:
                credits_text = await cells.nth(7).inner_text()

            # 授業コードと科目名を分離 (例: "52595:（留）日本語Ⅷ（アカデミック日本語a）(O1)")
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

            rows.append({
                "code": code,
                "name": name,
                "faculty": faculty_text.strip(),
                "term": term_text.strip(),
                "dayPeriod": day_period_text.strip(),
                "instructor": instructor_text.strip(),
                "credits": credits_text.strip(),
                "syllabusUrl": syllabus_url,
                "room": "",  # 詳細ページ取得後に埋める
            })
        except Exception as e:
            print(f"  [WARN] Row {i} extraction error: {e}", file=sys.stderr)
            continue

    return rows


async def get_total_count(page: Page) -> int:
    """検索結果の総件数を取得する"""
    try:
        count_text = await page.locator("text=/全 \\d+ 件/").first.inner_text()
        match = re.search(r"全\s*(\d+)\s*件", count_text)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return 0


async def scrape_faculty_day_period(
    page: Page,
    context: BrowserContext,
    faculty: str,
    semester: str,
    day: str,
    period: str,
    year: str,
) -> list[dict]:
    """特定の学部・曜日・時限の授業一覧を取得し、詳細ページから授業施設も取得する"""
    all_courses = []

    try:
        # クリアボタンを押す
        clear_btn = page.get_by_role("button", name="クリア")
        await clear_btn.click()
        await page.wait_for_timeout(500)

        # 学部を選択（aria-labelベース）
        await select_combobox_by_label(page, "学部・研究科", faculty)

        # 年度を選択
        await select_combobox_by_label(page, "年度", year)

        # 学期を選択
        await select_combobox_by_label(page, "学期", semester)

        # 曜日チェックボックスを設定
        await uncheck_all_checkboxes(page, DAYS)
        await check_checkbox(page, day)

        # 時限チェックボックスを設定
        await uncheck_all_checkboxes(page, PERIODS)
        await check_checkbox(page, period)

        # 表示件数を50に変更（selectのnameで特定）
        select = page.locator("select[name='results-per-page']")
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

        # 詳細ページから授業施設を並列取得
        if all_courses:
            print(f"    → 授業施設を取得中 ({len(all_courses)}件)...", flush=True)
            all_courses = await fetch_rooms_parallel(context, all_courses)

    except PlaywrightTimeout:
        print(f"  [TIMEOUT] {faculty} / {semester} / {day} {period}限", file=sys.stderr)
    except Exception as e:
        print(f"  [ERROR] {faculty} / {semester} / {day} {period}限: {e}", file=sys.stderr)

    return all_courses


async def main():
    year_str = os.environ.get("SCRAPE_YEAR", "").strip()
    year = year_str if year_str else str(datetime.now().year)

    # 単一学部モード: SCRAPE_FACULTY が指定されていればその学部のみ処理
    single_faculty = os.environ.get("SCRAPE_FACULTY", "").strip()
    if single_faculty:
        target_faculties = [single_faculty]
    else:
        target_faculties = FACULTIES

    # 単一セメスターモード: SCRAPE_SEMESTER が指定されていればそのセメスターのみ処理
    single_semester = os.environ.get("SCRAPE_SEMESTER", "").strip()
    if single_semester:
        target_semesters = [single_semester]
    else:
        target_semesters = SEMESTERS

    print(f"=== 立命館大学シラバス スクレイピング開始 ===")
    print(f"年度: {year}")
    print(f"対象学部: {', '.join(target_faculties)}")
    print(f"対象セメスター: {', '.join(target_semesters)}")
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
        await page.wait_for_timeout(3000)

        for faculty in target_faculties:
            print(f"\n--- {faculty} ---")
            for semester in target_semesters:
                for day in DAYS:
                    for period in PERIODS:
                        courses = await scrape_faculty_day_period(
                            page, context, faculty, semester, day, period, year
                        )
                        for c in courses:
                            key = f"{c['code']}_{c['dayPeriod']}_{c['term']}"
                            if key not in seen_keys:
                                seen_keys.add(key)
                                all_courses.append(c)

                        # レート制限対策
                        await page.wait_for_timeout(500)

        await browser.close()

    # 単一学部モードの場合: 学部別ファイルのみ出力
    if single_faculty:
        safe_name = single_faculty.replace("・", "_").replace("（", "(").replace("）", ")")
        fac_output = {
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "year": int(year),
            "faculty": single_faculty,
            "totalCourses": len(all_courses),
            "courses": all_courses,
        }
        fac_path = os.path.join(OUTPUT_DIR, f"syllabus_{safe_name}.json")
        with open(fac_path, "w", encoding="utf-8") as f:
            json.dump(fac_output, f, ensure_ascii=False, indent=2)

        print(f"\n=== 完了 ===")
        print(f"学部: {single_faculty}")
        print(f"取得件数: {len(all_courses)}件")
        print(f"出力ファイル: {fac_path}")
    else:
        # 全学部モード: 統合ファイルと学部別ファイルを出力
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
