/**
 * Google Apps Script: ニュースの取得・追加・編集・削除を行い、GitHubのnews.jsonを更新する
 *
 * === セットアップ手順 ===
 *
 * 1. https://script.google.com/ で新しいプロジェクトを作成
 * 2. このファイルの内容をコピーして貼り付け
 * 3. スクリプトプロパティに以下を設定（歯車アイコン → スクリプトプロパティ）:
 *    - GITHUB_TOKEN : GitHubのPersonal Access Token（repoスコープ）
 *    - GITHUB_REPO  : materials-modeling-group/homepage
 * 4. デプロイ → 新しいデプロイ → ウェブアプリ
 *    - 実行するユーザー: 自分
 *    - アクセスできるユーザー: 全員
 * 5. 表示されたURLを admin/index.html の GAS_URL に設定
 *
 * ※ コードを更新したら「デプロイを管理」→「新しいバージョン」で再デプロイ
 */

// ── GET: ニュース一覧を返す ──
function doGet(e) {
  try {
    var result = getNewsFromGitHub();
    return ContentService.createTextOutput(JSON.stringify({ status: "ok", data: result }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ status: "error", message: err.message }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

// ── POST: 追加・編集・削除 ──
function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var action = data.action || "add";
    var result;

    if (action === "add") {
      result = addNews(data);
    } else if (action === "edit") {
      result = editNews(data.index, data.entry);
    } else if (action === "delete") {
      result = deleteNews(data.index);
    } else {
      throw new Error("Unknown action: " + action);
    }

    return ContentService.createTextOutput(JSON.stringify({ status: "ok", result: result }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ status: "error", message: err.message }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

// ── GitHub操作の共通関数 ──
function getGitHubFile() {
  var props = PropertiesService.getScriptProperties();
  var token = props.getProperty("GITHUB_TOKEN");
  var repo = props.getProperty("GITHUB_REPO");
  var path = "data/news.json";
  var url = "https://api.github.com/repos/" + repo + "/contents/" + path + "?ref=main";
  var resp = UrlFetchApp.fetch(url, {
    headers: { Authorization: "Bearer " + token, Accept: "application/vnd.github.v3+json" }
  });
  var info = JSON.parse(resp.getContentText());
  var content = Utilities.newBlob(Utilities.base64Decode(info.content)).getDataAsString();
  return { list: JSON.parse(content), sha: info.sha };
}

function commitNewsList(newsList, sha, message) {
  var props = PropertiesService.getScriptProperties();
  var token = props.getProperty("GITHUB_TOKEN");
  var repo = props.getProperty("GITHUB_REPO");
  var path = "data/news.json";
  var content = JSON.stringify(newsList, null, 2) + "\n";
  var encoded = Utilities.base64Encode(Utilities.newBlob(content).getBytes());
  var url = "https://api.github.com/repos/" + repo + "/contents/" + path;
  var resp = UrlFetchApp.fetch(url, {
    method: "put",
    headers: { Authorization: "Bearer " + token, Accept: "application/vnd.github.v3+json" },
    contentType: "application/json",
    payload: JSON.stringify({ message: message, content: encoded, sha: sha, branch: "main" })
  });
  return JSON.parse(resp.getContentText()).commit.sha;
}

// ── 一覧取得 ──
function getNewsFromGitHub() {
  return getGitHubFile().list;
}

// ── 追加 ──
function addNews(newsItem) {
  var file = getGitHubFile();
  var entry = {
    date: newsItem.date || "",
    category: newsItem.category || "",
    category_en: newsItem.category_en || "",
    title: newsItem.title || "",
    title_en: newsItem.title_en || "",
    url: newsItem.url || "",
    paper_title: newsItem.paper_title || "",
    doi: newsItem.doi || "",
    body: (newsItem.body || "").replace(/\n/g, "<br>"),
    body_en: (newsItem.body_en || "").replace(/\n/g, "<br>")
  };
  file.list.unshift(entry);
  file.list.sort(function (a, b) { return (b.date || "").localeCompare(a.date || ""); });
  return commitNewsList(file.list, file.sha, "ニュースを追加: " + (newsItem.title || "no title"));
}

// ── 編集 ──
function editNews(index, updatedEntry) {
  var file = getGitHubFile();
  if (index < 0 || index >= file.list.length) throw new Error("Invalid index: " + index);
  file.list[index] = {
    date: updatedEntry.date || "",
    category: updatedEntry.category || "",
    category_en: updatedEntry.category_en || "",
    title: updatedEntry.title || "",
    title_en: updatedEntry.title_en || "",
    url: updatedEntry.url || "",
    paper_title: updatedEntry.paper_title || "",
    doi: updatedEntry.doi || "",
    body: (updatedEntry.body || "").replace(/\n/g, "<br>"),
    body_en: (updatedEntry.body_en || "").replace(/\n/g, "<br>")
  };
  file.list.sort(function (a, b) { return (b.date || "").localeCompare(a.date || ""); });
  return commitNewsList(file.list, file.sha, "ニュースを編集: " + (updatedEntry.title || "no title"));
}

// ── 削除 ──
function deleteNews(index) {
  var file = getGitHubFile();
  if (index < 0 || index >= file.list.length) throw new Error("Invalid index: " + index);
  var removed = file.list.splice(index, 1)[0];
  return commitNewsList(file.list, file.sha, "ニュースを削除: " + (removed.title || "no title"));
}
