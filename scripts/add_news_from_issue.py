#!/usr/bin/env python3
"""
GitHub Issue（フォーム形式）の本文をパースして data/news.json に追加するスクリプト
GitHub Actions から呼び出される
"""

import json
import os
import re
import sys
from pathlib import Path

CATEGORY_MAP = {
    "お知らせ / Announcement": ("お知らせ", "Announcement"),
    "プレスリリース / Press Release": ("プレスリリース", "Press Release"),
    "受賞 / Award": ("受賞", "Award"),
    "メディア / Media": ("メディア", "Media"),
    "イベント / Event": ("イベント", "Event"),
}


def parse_issue_body(body):
    """GitHub Issue フォームの本文をパースする"""
    fields = {}
    current_key = None
    current_lines = []

    for line in body.split("\n"):
        line_stripped = line.strip()

        # フォームのヘッダー行を検出: ### ラベル名
        header_match = re.match(r"^###\s+(.+)$", line_stripped)
        if header_match:
            # 前のフィールドを保存
            if current_key is not None:
                fields[current_key] = "\n".join(current_lines).strip()
            current_key = header_match.group(1).strip()
            current_lines = []
        elif current_key is not None:
            # _No response_ はスキップ
            if line_stripped == "_No response_":
                continue
            current_lines.append(line)

    # 最後のフィールドを保存
    if current_key is not None:
        fields[current_key] = "\n".join(current_lines).strip()

    return fields


def main():
    body = os.environ.get("ISSUE_BODY", "")
    if not body:
        print("ERROR: ISSUE_BODY is empty")
        sys.exit(1)

    fields = parse_issue_body(body)

    # フィールド名のマッピング
    date = fields.get("日付", "")
    category_raw = fields.get("カテゴリ", "")
    title_ja = fields.get("タイトル（日本語）", "")
    title_en = fields.get("タイトル（英語）", "")
    url = fields.get("関連URL", "").strip()
    paper_title = fields.get("論文/講演タイトル", fields.get("論文タイトル", "")).strip()
    doi = fields.get("DOI", "").strip()
    event_name = fields.get("学会名", "").strip()
    presenters = fields.get("発表者", "").strip()
    body_ja = fields.get("本文（日本語）", "")
    body_en = fields.get("本文（英語）", "")

    if not date or not title_ja:
        print("ERROR: date or title_ja is missing")
        print(f"Parsed fields: {fields}")
        sys.exit(1)

    # カテゴリ変換
    cat_ja, cat_en = CATEGORY_MAP.get(category_raw, (category_raw, category_raw))

    # 日付フォーマット検証
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        print(f"ERROR: Invalid date format: {date}")
        sys.exit(1)

    # 学会名が入力されていれば招待講演の本文を自動生成
    if event_name:
        lines = []
        lines.append(f"学会名：{event_name}")
        if date:
            parts = date.split("-")
            date_ja = f"{int(parts[0])}年{int(parts[1])}月{int(parts[2])}日"
            lines.append(f"日時：{date_ja}")
        if presenters:
            lines.append(f"発表者：{presenters}")
        if body_ja:
            lines.append(body_ja)
        body_ja = "\n".join(lines)

    new_entry = {
        "date": date,
        "category": cat_ja,
        "category_en": cat_en,
        "title": title_ja,
        "title_en": title_en,
        "url": url,
        "paper_title": paper_title,
        "doi": doi,
        "body": body_ja.replace("\n", "<br>"),
        "body_en": body_en.replace("\n", "<br>"),
    }

    # news.json を読み込んで先頭に追加
    news_path = Path(__file__).parent.parent / "data" / "news.json"
    existing = json.loads(news_path.read_text(encoding="utf-8"))
    existing.insert(0, new_entry)

    # 日付順にソート（降順）
    existing.sort(key=lambda x: x["date"], reverse=True)

    news_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Added news: {date} - {title_ja}")


if __name__ == "__main__":
    main()
