#!/usr/bin/env python3
"""
CrossRef APIで各研究者の新規論文を検出し、data/news.jsonに追加するスクリプト
GitHub Actionsのcronで定期実行される
"""

import json
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
RESEARCHERS_PATH = DATA_DIR / "researchers.json"
NEWS_PATH = DATA_DIR / "news.json"

CROSSREF_API = "https://api.crossref.org/works"
MAILTO = "DEMURA.Masahiko@nims.go.jp"
LOOKBACK_DAYS = 90


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fetch_crossref(orcid, from_date):
    """CrossRef APIでORCIDに紐づく論文を取得する"""
    params = urllib.parse.urlencode({
        "filter": f"from-pub-date:{from_date},orcid:{orcid}",
        "sort": "published",
        "order": "desc",
        "rows": 50,
        "mailto": MAILTO,
    })
    url = f"{CROSSREF_API}?{params}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"GroupHomepage/1.0 (mailto:{MAILTO})"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("message", {}).get("items", [])


def get_existing_dois(news):
    """news.jsonから既存のDOIを収集する"""
    dois = set()
    for entry in news:
        doi = entry.get("doi", "").strip()
        if doi:
            dois.add(doi.lower())
        # body内の「DOI：xxx」行からも抽出（doi フィールド未設定の古いエントリ対策）
        for line in entry.get("body", "").split("<br>"):
            line = line.strip()
            if line.startswith("DOI：") or line.startswith("DOI:"):
                d = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                if d:
                    dois.add(d.lower())
    return dois


# ── 日付ユーティリティ ──

def extract_date_parts(item):
    """CrossRefアイテムからオンライン公開日を優先して日付パーツを取得する"""
    for key in ("published-online", "published-print", "published", "issued"):
        parts = item.get(key, {}).get("date-parts")
        if parts and parts[0]:
            return parts[0]
    return None


def date_parts_to_iso(parts):
    """日付パーツをISO形式（YYYY-MM-DD）に変換する"""
    if not parts:
        return ""
    if len(parts) >= 3:
        return f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}"
    if len(parts) >= 2:
        return f"{parts[0]:04d}-{parts[1]:02d}-01"
    return f"{parts[0]:04d}-01-01"


def date_parts_to_ja(parts):
    """日付パーツを日本語表記に変換する"""
    if not parts:
        return ""
    if len(parts) >= 3:
        return f"{parts[0]}年{parts[1]}月{parts[2]}日"
    if len(parts) >= 2:
        return f"{parts[0]}年{parts[1]}月"
    return f"{parts[0]}年"


# ── 論文メタデータの整形 ──

def get_authors(item):
    """著者リストを「Given Family」形式の文字列に変換する"""
    names = []
    for a in item.get("author", []):
        given = a.get("given", "")
        family = a.get("family", "")
        if given and family:
            names.append(f"{given} {family}")
        elif family:
            names.append(family)
    return ", ".join(names)


def get_journal(item):
    """ジャーナル名を取得する"""
    titles = item.get("container-title", [])
    return titles[0] if titles else ""


def get_volume_issue(item):
    """巻号を整形する"""
    volume = item.get("volume", "")
    issue = item.get("issue", "")
    if volume and issue:
        return f"Vol. {volume}, Issue {issue}"
    if volume:
        return f"Vol. {volume}"
    return ""


def is_open_access(item):
    """Open Accessかどうかを判定する"""
    for lic in item.get("license", []):
        url = lic.get("URL", "") or ""
        if "creativecommons.org" in url:
            return True
    return False


# ── ニュースエントリの生成 ──

def build_news_entry(researcher, paper):
    """論文情報からニュースエントリを生成する"""
    doi = paper.get("DOI", "")
    title_list = paper.get("title", [])
    paper_title = title_list[0] if title_list else ""
    journal = get_journal(paper)
    date_parts = extract_date_parts(paper)

    # タイトル: {氏名}{職位}の論文が{ジャーナル}に掲載されました
    news_title = (
        f"{researcher['name_ja']}{researcher['position_ja']}の論文が"
        f"{journal}に掲載されました"
    )

    # 本文
    body_lines = []
    authors = get_authors(paper)
    if authors:
        body_lines.append(f"著者：{authors}")
    if journal:
        body_lines.append(f"ジャーナル：{journal}")
    vol_issue = get_volume_issue(paper)
    if vol_issue:
        body_lines.append(f"巻号：{vol_issue}")
    article_number = paper.get("article-number", "")
    page = paper.get("page", "")
    if article_number:
        body_lines.append(f"論文番号：{article_number}")
    elif page:
        body_lines.append(f"ページ：{page}")
    date_ja = date_parts_to_ja(date_parts)
    if date_ja:
        body_lines.append(f"オンライン公開：{date_ja}")
    if doi:
        body_lines.append(f"DOI：{doi}")
    if is_open_access(paper):
        body_lines.append("備考：Open Access")

    return {
        "date": date_parts_to_iso(date_parts),
        "category": "お知らせ",
        "category_en": "Announcement",
        "title": news_title,
        "title_en": "",
        "paper_title": paper_title,
        "doi": doi,
        "body": "<br>".join(body_lines),
        "body_en": "",
    }


def main():
    researchers = load_json(RESEARCHERS_PATH)
    news = load_json(NEWS_PATH)
    existing_dois = get_existing_dois(news)

    from_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    print(f"Checking papers published since {from_date}")

    new_entries = []

    for researcher in researchers:
        orcid = researcher.get("orcid", "")
        if not orcid:
            continue

        print(f"\n{researcher['name_en']} ({orcid})")

        try:
            papers = fetch_crossref(orcid, from_date)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        for paper in papers:
            doi = paper.get("DOI", "")
            if not doi:
                continue
            if doi.lower() in existing_dois:
                title = paper.get("title", [""])[0][:50]
                print(f"  Skip (existing): {title}...")
                continue

            entry = build_news_entry(researcher, paper)
            new_entries.append(entry)
            existing_dois.add(doi.lower())

            print(f"  NEW: {entry['paper_title'][:60]}...")

        # CrossRef APIのレートリミット対策
        time.sleep(1)

    if not new_entries:
        print("\nNo new papers found.")
        return

    news.extend(new_entries)
    news.sort(key=lambda x: x.get("date", ""), reverse=True)
    save_json(NEWS_PATH, news)

    print(f"\nAdded {len(new_entries)} new paper(s) to news.json:")
    for e in new_entries:
        print(f"  - {e['paper_title'][:70]}")


if __name__ == "__main__":
    main()
