#!/usr/bin/env python3
"""
NIMS SAMURAIの各研究者のプレゼンテーション一覧から招待講演を検出し、
News Admin（GASエンドポイント）経由でnews.jsonに追加するスクリプト。
GitHub Actionsのcronで定期実行される。
"""

import html as html_mod
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
RESEARCHERS_PATH = DATA_DIR / "researchers.json"
KNOWN_TALKS_PATH = DATA_DIR / "known_talk_ids.json"

SAMURAI_BASE = "https://samurai.nims.go.jp"

DEFAULT_GAS_URL = (
    "https://script.google.com/macros/s/"
    "AKfycbx_u67JnXKn5Fb3tcD6fQyn1as28Im6gcgdK7Mb9UAD6V3jCS2-Qn7tJYK14P9UN6qB/exec"
)
GAS_URL = os.environ.get("GAS_URL", DEFAULT_GAS_URL)

LOOKBACK_YEARS = 1
POST_DELAY = 10

MONTH_MAP = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _strip_html(s):
    text = re.sub(r"<[^>]+>", "", s).strip()
    return html_mod.unescape(text)


# ── SAMURAI HTML パース（一覧ページ） ──

def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": "GroupHomepage/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def parse_invited_presentations(html, min_year):
    """研究業績ページのHTMLから招待講演を抽出する"""
    anchor = html.find('<a name="presentation">')
    if anchor < 0:
        return []

    section = html[anchor:]
    next_anchor = section.find('<a name="', 10)
    if next_anchor > 0:
        section = section[:next_anchor]

    results = []
    year_blocks = re.split(r'<h5 class="small_subject">(\d{4})</h5>', section)

    for i in range(1, len(year_blocks) - 1, 2):
        year = int(year_blocks[i])
        if year < min_year:
            continue
        block = year_blocks[i + 1]

        items = re.findall(r"<li[^>]*>(.*?)</li>", block, re.DOTALL)
        for item in items:
            if "invited_presentation" not in item:
                continue

            uuid_match = re.search(r"/presentations/([0-9a-f-]{36})", item)
            talk_id = uuid_match.group(1) if uuid_match else ""

            title_match = re.search(r'/presentations/[^"]*"[^>]*>(.*?)</a>', item)
            title = _strip_html(title_match.group(1)) if title_match else ""

            event_match = re.search(r"</a>\.\s*(.*?)\.\s*\d{4}", item, re.DOTALL)
            event = _strip_html(event_match.group(1)).strip() if event_match else ""

            authors_match = re.search(r"^(.*?)<a href=\"/presentations/", item, re.DOTALL)
            authors = ""
            if authors_match:
                authors = _strip_html(authors_match.group(1)).strip().rstrip(".")

            results.append({
                "id": talk_id,
                "title": title,
                "event": event,
                "year": year,
                "authors": authors,
            })

    return results


# ── SAMURAI 個別ページから日付取得 ──

def fetch_presentation_date(talk_id):
    """個別プレゼンテーションページから開催日を取得する。
    返り値: (date_iso, date_display_ja)
    """
    url = f"{SAMURAI_BASE}/presentations/{talk_id}?locale=en"
    try:
        html = fetch_html(url)
    except Exception:
        return None, None

    # パターン1: "September 02, 2025-September 05, 2025"
    month_names = "|".join(MONTH_MAP.keys())
    pattern_en = (
        rf"({month_names})\s+(\d{{1,2}}),\s+(\d{{4}})"
        rf"(?:\s*-\s*({month_names})\s+(\d{{1,2}}),\s+(\d{{4}}))?"
    )
    match = re.search(pattern_en, html)
    if match:
        m1, d1, y1 = MONTH_MAP[match.group(1)], int(match.group(2)), int(match.group(3))
        date_iso = f"{y1:04d}-{m1:02d}-{d1:02d}"
        date_ja = f"{y1}年{m1}月{d1}日"
        if match.group(4):
            m2, d2, y2 = MONTH_MAP[match.group(4)], int(match.group(5)), int(match.group(6))
            date_ja += f" - {y2}年{m2}月{d2}日"
        return date_iso, date_ja

    # パターン2: "2025-07-18" (YYYY-MM-DD)
    match_iso = re.search(
        r"(\d{4})-(\d{2})-(\d{2})(?:\s*-\s*(\d{4})-(\d{2})-(\d{2}))?\.?\s+.*?Invited",
        html,
    )
    if match_iso:
        y1, m1, d1 = int(match_iso.group(1)), int(match_iso.group(2)), int(match_iso.group(3))
        date_iso = f"{y1:04d}-{m1:02d}-{d1:02d}"
        date_ja = f"{y1}年{m1}月{d1}日"
        if match_iso.group(4):
            y2, m2, d2 = int(match_iso.group(4)), int(match_iso.group(5)), int(match_iso.group(6))
            date_ja += f" - {y2}年{m2}月{d2}日"
        return date_iso, date_ja

    # パターン3: "2025-07-18" (Invitedと無関係でも本文中のISO日付)
    match_simple = re.search(r'\.?\s+(\d{4})-(\d{2})-(\d{2})\.?\s', html)
    if match_simple:
        y1, m1, d1 = int(match_simple.group(1)), int(match_simple.group(2)), int(match_simple.group(3))
        date_iso = f"{y1:04d}-{m1:02d}-{d1:02d}"
        date_ja = f"{y1}年{m1}月{d1}日"
        return date_iso, date_ja

    return None, None


# ── GASへの投稿 ──

def post_to_gas(entry):
    payload = {
        "action": "add",
        "date": entry["date"],
        "category": entry["category"],
        "category_en": entry["category_en"],
        "title": entry["title"],
        "title_en": entry["title_en"],
        "url": entry.get("url", ""),
        "paper_title": entry.get("paper_title", ""),
        "doi": entry.get("doi", ""),
        "body": entry["body"],
        "body_en": entry["body_en"],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        GAS_URL, data=data,
        headers={"Content-Type": "text/plain"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if result.get("status") != "ok":
        raise RuntimeError(f"GAS error: {result.get('message', 'unknown')}")
    return result


# ── ニュースエントリ生成 ──

def build_news_entry(researcher, talk, date_iso, date_ja):
    """招待講演情報からニュースエントリを生成する"""
    event = talk["event"]
    title = talk["title"]
    authors = talk["authors"]

    if not date_iso:
        date_iso = f"{talk['year']}-01-01"
    if not date_ja:
        date_ja = f"{talk['year']}年"

    today = datetime.now().strftime("%Y-%m-%d")
    verb = "行います" if date_iso > today else "行いました"
    news_title = (
        f"{researcher['name_ja']}{researcher['position_ja']}が"
        f"{event}で招待講演を{verb}"
    )

    # 本文：講演タイトルを先頭に
    body_lines = []
    if title:
        body_lines.append(f"講演タイトル：{title}")
    if event:
        body_lines.append(f"学会名：{event}")
    if date_ja:
        body_lines.append(f"日時：{date_ja}")
    if authors:
        body_lines.append(f"発表者：{authors}")

    return {
        "date": date_iso,
        "category": "お知らせ",
        "category_en": "Announcement",
        "title": news_title,
        "title_en": "",
        "url": "",
        "paper_title": "",
        "doi": "",
        "body": "\n".join(body_lines),
        "body_en": "",
    }


def main():
    researchers = load_json(RESEARCHERS_PATH)
    known_ids = set(load_json(KNOWN_TALKS_PATH))

    min_year = datetime.now().year - LOOKBACK_YEARS
    print(f"Checking invited talks from SAMURAI (year >= {min_year})")

    new_talks = []

    for researcher in researchers:
        samurai_id = researcher.get("samurai_id", "")
        if not samurai_id:
            continue

        print(f"\n{researcher['name_en']} ({samurai_id})")

        try:
            html = fetch_html(
                f"{SAMURAI_BASE}/profiles/{samurai_id}/publications?locale=en"
            )
        except Exception as e:
            print(f"  ERROR fetching: {e}")
            continue

        talks = parse_invited_presentations(html, min_year)

        for talk in talks:
            talk_id = talk["id"]
            if not talk_id or talk_id in known_ids:
                if talk_id in known_ids:
                    print(f"  Skip (known): {talk['title'][:50]}...")
                continue

            # 個別ページから日付を取得
            date_iso, date_ja = fetch_presentation_date(talk_id)
            if date_iso:
                print(f"  NEW: {talk['title'][:50]}... ({date_ja})")
            else:
                print(f"  NEW: {talk['title'][:50]}... (date unknown)")

            new_talks.append((researcher, talk, date_iso, date_ja, talk_id))
            known_ids.add(talk_id)
            time.sleep(1)

        time.sleep(1)

    if not new_talks:
        print("\nNo new invited talks found.")
        return

    # GAS経由で投稿
    posted_ids = []
    for i, (researcher, talk, date_iso, date_ja, talk_id) in enumerate(new_talks):
        entry = build_news_entry(researcher, talk, date_iso, date_ja)
        try:
            print(f"\nPosting [{i+1}/{len(new_talks)}]: {talk['title'][:50]}...")
            post_to_gas(entry)
            posted_ids.append(talk_id)
            print(f"  OK")
        except Exception as e:
            print(f"  ERROR posting: {e}")

        if i < len(new_talks) - 1:
            time.sleep(POST_DELAY)

    all_ids = sorted(set(load_json(KNOWN_TALKS_PATH)) | set(posted_ids))
    save_json(KNOWN_TALKS_PATH, all_ids)

    print(f"\nPosted {len(posted_ids)}/{len(new_talks)} invited talk(s) via Admin")


if __name__ == "__main__":
    main()
