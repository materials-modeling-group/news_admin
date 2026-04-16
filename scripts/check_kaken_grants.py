#!/usr/bin/env python3
"""
KAKENから各研究者の科研費採択情報を検出し、
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
KNOWN_GRANTS_PATH = DATA_DIR / "known_grant_ids.json"

KAKEN_BASE = "https://kaken.nii.ac.jp"

DEFAULT_GAS_URL = (
    "https://script.google.com/macros/s/"
    "AKfycbx_u67JnXKn5Fb3tcD6fQyn1as28Im6gcgdK7Mb9UAD6V3jCS2-Qn7tJYK14P9UN6qB/exec"
)
GAS_URL = os.environ.get("GAS_URL", DEFAULT_GAS_URL)

POST_DELAY = 10


def load_json(path):
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _strip_html(s):
    text = re.sub(r"<[^>]+>", "", s).strip()
    return html_mod.unescape(text)


def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": "GroupHomepage/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


# ── KAKEN 検索 ──

def search_grants(researcher_name):
    """KAKENで研究者名で検索し、研究課題IDのリストを返す"""
    encoded = urllib.request.quote(researcher_name)
    url = f"{KAKEN_BASE}/ja/search/?kw={encoded}"
    html = fetch_html(url)

    # grant IDとタイトルを抽出
    pattern = (
        r'<input[^>]*value="KAKENHI-PROJECT-(\w+)"[^>]*/>\s*'
        r'(?:<[^>]*>)*\s*\d+\.\s*(?:<[^>]*>)*\s*'
        r'<a[^>]*href="/ja/grant/[^"]+?"[^>]*>(.*?)</a>'
    )
    matches = re.findall(pattern, html, re.DOTALL)
    results = []
    for gid, title_raw in matches:
        title = _strip_html(title_raw)
        results.append({"id": gid, "title": title})
    return results


def fetch_grant_details(grant_id):
    """個別の研究課題ページから詳細情報を取得する"""
    url = f"{KAKEN_BASE}/ja/grant/KAKENHI-PROJECT-{grant_id}/"
    html = fetch_html(url)

    # テキスト抽出
    clean = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    clean = re.sub(r"<style[^>]*>.*?</style>", "", clean, flags=re.DOTALL)
    clean_text = html_mod.unescape(re.sub(r"<[^>]+>", "\n", clean))
    lines = [l.strip() for l in clean_text.split("\n") if l.strip()]

    info = {
        "grant_id": grant_id,
        "title": "",
        "category": "",
        "pi": "",
        "pi_affiliation": "",
        "period": "",
        "status": "",
        "amount": "",
    }

    # タイトル（ページのtitleから）
    title_match = re.search(r"<title>(.*?)</title>", html)
    if title_match:
        t = _strip_html(title_match.group(1))
        # "KAKEN — 研究課題をさがす | タイトル (ID)" パターン
        t = re.sub(r"KAKEN.*?\|", "", t).strip()
        t = re.sub(r"\s*\(KAKENHI-PROJECT-.*?\)", "", t).strip()
        info["title"] = t

    for i, line in enumerate(lines):
        next_lines = lines[i + 1 : i + 4]

        if line == "研究種目" and next_lines:
            info["category"] = next_lines[0]

        if line == "研究代表者" and next_lines:
            pi_line = next_lines[0]
            # "渡邊 育夢  国立研究..., 主幹研究員 (20535992)" のパターン
            info["pi"] = pi_line

        if line == "研究期間 (年度)" and next_lines:
            info["period"] = next_lines[0]

        if line == "研究課題ステータス":
            # 次の行が "採択 (2026年度)" など
            for nl in next_lines:
                if "採択" in nl or "交付" in nl or "完了" in nl or "中断" in nl:
                    info["status"] = nl
                    break

        if line == "配分額":
            # 次の数行に金額
            for nl in next_lines:
                if "千円" in nl:
                    info["amount"] = nl
                    break

    return info


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
        GAS_URL,
        data=data,
        headers={"Content-Type": "text/plain"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if result.get("status") != "ok":
        raise RuntimeError(f"GAS error: {result.get('message', 'unknown')}")
    return result


# ── ニュースエントリ生成 ──

def build_news_entry(researcher, grant_info):
    """科研費情報からニュースエントリを生成する"""
    grant_id = grant_info["grant_id"]
    title = grant_info["title"]
    category = grant_info["category"]
    period = grant_info["period"]
    amount = grant_info["amount"]
    status = grant_info["status"]
    kaken_url = f"{KAKEN_BASE}/ja/grant/KAKENHI-PROJECT-{grant_id}/"

    # 日付: 研究期間の開始年度
    year_match = re.search(r"(\d{4})", period)
    start_year = year_match.group(1) if year_match else str(datetime.now().year)
    date_iso = f"{start_year}-04-01"

    # タイトル
    news_title = (
        f"{researcher['name_ja']}{researcher['position_ja']}が"
        f"{category}に採択されました"
    )

    # 本文
    body_lines = []
    body_lines.append(f"研究課題：{title}")
    if category:
        body_lines.append(f"研究種目：{category}")
    body_lines.append(f"課題番号：{grant_id}")
    if period:
        body_lines.append(f"研究期間：{period}")
    if amount:
        body_lines.append(f"配分額：{amount}")

    return {
        "date": date_iso,
        "category": "お知らせ",
        "category_en": "Announcement",
        "title": news_title,
        "title_en": "",
        "url": kaken_url,
        "paper_title": "",
        "doi": "",
        "body": "\n".join(body_lines),
        "body_en": "",
    }


def is_recent_grant(grant_info, current_year):
    """今年度または来年度に開始される研究課題かどうかを判定する"""
    period = grant_info.get("period", "")
    year_match = re.search(r"(\d{4})", period)
    if not year_match:
        return False
    start_year = int(year_match.group(1))
    return start_year >= current_year


LOOKBACK_YEARS = 1  # 今年度に加えて過去何年度分までさかのぼるか


def main():
    researchers = load_json(RESEARCHERS_PATH)
    known_ids = set(load_json(KNOWN_GRANTS_PATH))

    current_year = datetime.now().year
    # 4月以前は前年度の採択もチェック
    if datetime.now().month < 4:
        current_year -= 1
    threshold_year = current_year - LOOKBACK_YEARS

    print(f"Checking KAKEN grants (start year >= {threshold_year})")

    new_grants = []

    for researcher in researchers:
        name_ja = researcher.get("name_ja", "")
        if not name_ja:
            continue

        print(f"\n{researcher['name_en']} (検索: {name_ja})")

        try:
            grants = search_grants(name_ja)
        except Exception as e:
            print(f"  ERROR searching: {e}")
            continue

        print(f"  Found {len(grants)} grants total")

        for grant in grants:
            gid = grant["id"]
            if gid in known_ids:
                continue

            # 個別ページから詳細取得
            try:
                details = fetch_grant_details(gid)
            except Exception as e:
                print(f"  ERROR fetching {gid}: {e}")
                continue

            time.sleep(1)

            # 閾値年度以降の課題のみ
            if not is_recent_grant(details, threshold_year):
                known_ids.add(gid)  # 古い課題もスキップ記録
                continue

            # 研究代表者が本人か確認（スペースを除去して比較）
            pi = details.get("pi", "").replace(" ", "").replace("\u3000", "")
            name_ja_norm = name_ja.replace(" ", "").replace("\u3000", "")
            name_en = researcher.get("name_en", "").replace(" ", "")
            pi_norm = pi
            if name_ja_norm not in pi_norm and name_en.lower() not in pi_norm.lower():
                known_ids.add(gid)  # 分担者の場合もスキップ記録
                continue

            new_grants.append((researcher, details, gid))
            known_ids.add(gid)

            print(f"  NEW: [{details['category']}] {details['title'][:50]}...")

        time.sleep(2)

    if not new_grants:
        print("\nNo new grants found.")
        # IDリストは更新して保存
        save_json(KNOWN_GRANTS_PATH, sorted(known_ids))
        return

    # GAS経由で投稿
    posted_ids = []
    for i, (researcher, details, gid) in enumerate(new_grants):
        entry = build_news_entry(researcher, details)
        try:
            print(f"\nPosting [{i+1}/{len(new_grants)}]: {details['title'][:50]}...")
            post_to_gas(entry)
            posted_ids.append(gid)
            print(f"  OK")
        except Exception as e:
            print(f"  ERROR posting: {e}")

        if i < len(new_grants) - 1:
            time.sleep(POST_DELAY)

    save_json(KNOWN_GRANTS_PATH, sorted(known_ids))
    print(f"\nPosted {len(posted_ids)}/{len(new_grants)} grant(s) via Admin")


if __name__ == "__main__":
    main()
