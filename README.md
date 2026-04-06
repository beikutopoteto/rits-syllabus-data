# 立命館大学シラバス データ自動生成

GitHub Actions を使用して立命館大学のシラバスデータを自動取得し、GitHub Pages で JSON として公開するリポジトリです。

## 仕組み

1. **Playwright** でシラバスサイト（https://syllabus.ritsumei.ac.jp/syllabus/s/）を巡回
2. 全学部 × 全曜日 × 全時限の組み合わせで授業情報を取得
3. JSON ファイルとして `data/` ディレクトリに出力
4. GitHub Pages の `gh-pages` ブランチに自動デプロイ

## 出力ファイル

| ファイル | 内容 |
|---------|------|
| `syllabus.json` | 全学部の授業データ |
| `syllabus_{学部名}.json` | 学部別の授業データ |

## データ構造

```json
{
  "lastUpdated": "2026-04-06T00:00:00+00:00",
  "year": 2026,
  "totalCourses": 12345,
  "courses": [
    {
      "code": "12345",
      "name": "英語P3(YF)",
      "faculty": "薬学部",
      "term": "春セメスター",
      "dayPeriod": "火4",
      "campus": "BKC",
      "instructor": "山田 太郎",
      "language": "日本語",
      "credits": "2",
      "syllabusUrl": "https://syllabus.ritsumei.ac.jp/syllabus/s/r-syllabus/..."
    }
  ]
}
```

## 自動実行スケジュール

- 毎週日曜日 深夜3時（JST）に自動実行
- GitHub Actions の「Run workflow」ボタンで手動実行も可能

## セットアップ

1. このリポジトリをフォーク
2. Settings → Pages → Source を `gh-pages` ブランチに設定
3. Actions タブから手動実行、または日曜日の自動実行を待つ
4. `https://{ユーザー名}.github.io/{リポジトリ名}/syllabus.json` でアクセス可能

## ローカル実行

```bash
pip install playwright
playwright install chromium
python scrape.py
```

## 環境変数

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `SCRAPE_YEAR` | 取得する年度 | 現在の年 |
| `SCRAPE_FACULTIES` | 対象学部（カンマ区切り） | 全学部 |
| `OUTPUT_DIR` | 出力ディレクトリ | `data` |
