# Materials Modeling Group — News Admin

[Materials Modeling Group homepage](https://github.com/materials-modeling-group/homepage) のニュース管理画面と、論文・招待講演・科研費の自動検出システム。

🔐 **Admin URL**: https://materials-modeling-group.github.io/news_admin/admin/

## 概要

- News Admin: Web UI でニュースを投稿・編集・削除
- 自動検出: 週1回、各外部サービスから新着情報を取得してAdmin経由でNewsに投稿

すべての投稿は **Google Apps Script (GAS) → GitHub API** を経由して [materials-modeling-group/homepage](https://github.com/materials-modeling-group/homepage) の `data/news.json` を更新します。

## ディレクトリ構成

```
news_admin/
├── admin/
│   └── index.html                      Admin UI（ログイン + 投稿・編集・削除）
├── scripts/
│   ├── gas_news_endpoint.js            GAS バックエンドコード（参考コピー）
│   ├── check_new_papers.py             CrossRef API で論文を検出
│   ├── check_invited_talks.py          SAMURAI で招待講演を検出
│   ├── check_kaken_grants.py           KAKEN で科研費採択を検出
│   └── add_news_from_issue.py          GitHub Issue からNewsを投稿
├── data/
│   ├── researchers.json                研究者マスタ（ORCID, SAMURAI ID, researchmap ID）
│   ├── known_talk_ids.json             投稿済み招待講演の追跡（SAMURAI UUID）
│   └── known_grant_ids.json            投稿済み科研費の追跡（KAKEN ID）
└── .github/
    ├── ISSUE_TEMPLATE/news-post.yml    GitHub Issue による投稿テンプレート
    └── workflows/
        ├── add-news.yml                Issue経由の投稿処理
        ├── check-papers.yml            毎週月曜 09:00 JST
        ├── check-invited-talks.yml     毎週月曜 10:00 JST
        └── check-kaken.yml             毎週月曜 11:00 JST
```

## Admin画面の使い方

### ログイン
`admin/index.html` を開いてID/パスワードを入力。認証はクライアント側のSHA-256ハッシュで照合。

### 新規投稿フィールド

| フィールド | 用途 |
|-----------|------|
| 日付 | `YYYY-MM-DD` |
| カテゴリ | お知らせ / プレスリリース / 受賞 / メディア / イベント |
| タイトル（日本語・英語） | ニュース見出し |
| 関連URL | 受賞・プレスリリース等のリンク先。指定するとタイトルがリンクになる |
| 論文/講演タイトル | 論文の正式タイトルまたは講演タイトル。本文の先頭に太字で表示 |
| DOI | 論文DOI。指定すると論文タイトルがDOIリンクになる |
| 学会名 | 招待講演の学会名。指定すると本文が自動構成 |
| 発表者 | 招待講演の発表者 |
| 本文（日本語・英語） | HTMLリンク可 |

### 一覧機能
- 年別・カテゴリ別のドロップダウンフィルタ
- 各エントリの編集・削除ボタン

## 自動検出システム

### 1. 論文検出（CrossRef）
**ファイル**: `scripts/check_new_papers.py`
**トリガー**: 毎週月曜 09:00 JST

- 各研究者のORCIDでCrossRef APIを検索
- 過去90日間に出版された論文を対象
- 既存のDOIと比較して未投稿のものだけ取得

### 2. 招待講演検出（SAMURAI）
**ファイル**: `scripts/check_invited_talks.py`
**トリガー**: 毎週月曜 10:00 JST

- NIMS SAMURAI の研究業績ページを取得
- `invited_presentation` クラスのマーカーで招待講演を判定
- 個別ページから正確な開催日を取得
- `known_talk_ids.json` のSAMURAI UUIDで重複防止

### 3. 科研費検出（KAKEN）
**ファイル**: `scripts/check_kaken_grants.py`
**トリガー**: 毎週月曜 11:00 JST

- 各研究者名でKAKEN検索
- 今年度・前年度に開始される研究課題を対象
- 研究代表者が本人の課題のみ検出
- `known_grant_ids.json` で重複防止

## 研究者マスタ

`data/researchers.json` に7名分の情報を登録：

```json
{
  "name_ja": "渡邊育夢",
  "name_en": "Ikumu Watanabe",
  "position_ja": "主幹研究員",
  "position_en": "Principal Researcher",
  "orcid": "0000-0002-7693-1675",
  "researchmap_id": "ikumu",
  "samurai_id": "watanabe_ikumu"
}
```

新規研究者を追加する場合はこのファイルを編集してください。

## Google Apps Script（GAS）

バックエンドは Google Apps Script で実装されています。Admin画面と自動検出スクリプトはこのエンドポイントにPOSTリクエストを送信し、GASがGitHub API経由で `materials-modeling-group/homepage` の `news.json` を更新します。

### セットアップ

詳細は `scripts/gas_news_endpoint.js` のコメント参照。

1. [script.google.com](https://script.google.com/) で新規プロジェクト作成
2. `scripts/gas_news_endpoint.js` の内容を貼り付け
3. **スクリプトプロパティ**を設定：
   - `GITHUB_TOKEN`: GitHub Personal Access Token（`repo` スコープ）
   - `GITHUB_REPO`: `materials-modeling-group/homepage`
4. **デプロイ → ウェブアプリ**（実行ユーザー: 自分 / アクセス: 全員）
5. 発行されたURLを `admin/index.html` の `GAS_URL` 変数に設定

### 更新時

`scripts/gas_news_endpoint.js` を変更したら、GAS上のコードも更新し「**デプロイを管理 → 新しいバージョン**」で再デプロイが必要です。

## GitHub Issue による投稿

[New Issue](https://github.com/materials-modeling-group/news_admin/issues/new?template=news-post.yml) のフォームから投稿すると、`add-news.yml` ワークフローがパースして自動的に `materials-modeling-group/homepage` の news.json にコミットします。

## 関連リポジトリ

- **[materials-modeling-group/homepage](https://github.com/materials-modeling-group/homepage)** — 公開サイト本体。news.json はここに格納

## システム全体図

```
┌─────────────────────────────────────────────────────┐
│                 Data Sources                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ CrossRef │  │ SAMURAI  │  │  KAKEN   │           │
│  │   API    │  │  (HTML)  │  │  (HTML)  │           │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘           │
│       │             │             │                  │
│       └─────────────┼─────────────┘                  │
│                     │ cron (weekly)                  │
│  ┌──────────────────┴─────────────────┐              │
│  │   GitHub Actions (news_admin)      │              │
│  │   - check_new_papers.py            │              │
│  │   - check_invited_talks.py         │              │
│  │   - check_kaken_grants.py          │              │
│  └──────────────────┬─────────────────┘              │
└─────────────────────┼────────────────────────────────┘
                      │ POST
                      ▼
              ┌───────────────┐      ┌─────────────────┐
              │  Admin UI     ├─────►│  GAS Endpoint   │
              │  (Web)        │ POST │                 │
              └───────────────┘      └────────┬────────┘
                                              │ GitHub API
                                              ▼
                                     ┌──────────────────┐
                                     │ homepage         │
                                     │ /data/news.json  │
                                     └────────┬─────────┘
                                              │ fetch
                                              ▼
                                     ┌──────────────────┐
                                     │ homepage         │
                                     │ /news.html       │
                                     └──────────────────┘
```

## ライセンス

© Materials Modeling Group, NIMS. All rights reserved.
