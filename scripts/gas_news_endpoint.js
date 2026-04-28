/**
 * Google Apps Script: ニュースの取得・追加・編集・削除を行い、GitHubのnews.jsonを更新する
 *
 * === セットアップ手順 ===
 *
 * 1. https://script.google.com/ で新しいプロジェクトを作成
 * 2. このファイルの内容をコピーして貼り付け
 * 3. スクリプトプロパティに以下を設定（歯車アイコン → スクリプトプロパティ）:
 *    - GITHUB_TOKEN     : GitHubのPersonal Access Token（repoスコープ）
 *    - GITHUB_REPO      : materials-modeling-group/homepage
 *    - ADMIN_AUTH_HASH  : SHA-256("id:pw") の16進文字列（Admin画面ログインの認証情報）
 * 4. デプロイ → 新しいデプロイ → ウェブアプリ
 *    - 実行するユーザー: 自分
 *    - アクセスできるユーザー: 全員
 * 5. 表示されたURLを admin/index.html の GAS_URL に設定
 *
 * ※ コードを更新したら「デプロイを管理」→「新しいバージョン」で再デプロイ
 */

// ── 認証 ──
// 受信したハッシュをスクリプトプロパティ ADMIN_AUTH_HASH と一致するか検証する。
// 一致しなければ Unauthorized 例外を投げる。
function verifyAuth(authHash) {
  var props = PropertiesService.getScriptProperties();
  var expected = props.getProperty("ADMIN_AUTH_HASH");
  if (!expected) {
    throw new Error("Server is not configured: ADMIN_AUTH_HASH is missing");
  }
  if (!authHash || authHash !== expected) {
    throw new Error("Unauthorized");
  }
}

// ── GET: ニュース一覧を返す ──
function doGet(e) {
  try {
    var auth = (e && e.parameter && e.parameter.auth) || "";
    verifyAuth(auth);
    var result = getNewsFromGitHub();
    return ContentService.createTextOutput(JSON.stringify({ status: "ok", data: result }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ status: "error", message: err.message }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

// ── POST: 一覧取得・追加・編集・削除 ──
// ※ ブラウザのクロスオリジンfetchではGETがGAS側のCookieリダイレクトで弾かれるため、
//    一覧取得（list）もPOSTで受ける。
function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    verifyAuth(data.auth || "");
    var action = data.action || "add";
    var result;

    if (action === "list") {
      result = getNewsFromGitHub();
      return ContentService.createTextOutput(JSON.stringify({ status: "ok", data: result }))
        .setMimeType(ContentService.MimeType.JSON);
    } else if (action === "add") {
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

// ── GitHub API 共通呼び出し ──
function ghApi(method, path, payload) {
  var props = PropertiesService.getScriptProperties();
  var token = props.getProperty("GITHUB_TOKEN");
  var repo = props.getProperty("GITHUB_REPO");
  var url = "https://api.github.com/repos/" + repo + "/" + path;
  var options = {
    method: method,
    headers: { Authorization: "Bearer " + token, Accept: "application/vnd.github.v3+json" },
    muteHttpExceptions: true
  };
  if (payload !== undefined) {
    options.contentType = "application/json";
    options.payload = JSON.stringify(payload);
  }
  var resp = UrlFetchApp.fetch(url, options);
  var code = resp.getResponseCode();
  if (code < 200 || code >= 300) {
    throw new Error("GitHub API " + method + " " + path + " " + code + ": " + resp.getContentText());
  }
  return JSON.parse(resp.getContentText());
}

// ── 一覧取得 ──
function getNewsFromGitHub() {
  var info = ghApi("GET", "contents/data/news.json?ref=main");
  var content = Utilities.newBlob(Utilities.base64Decode(info.content)).getDataAsString();
  return JSON.parse(content);
}

// ── ニュース更新と画像追加・削除を Git Data API で1コミットにまとめる ──
// addedImages:        [{ path, base64 }]
// deletedImagePaths:  [path, ...]
function commitChanges(newsList, addedImages, deletedImagePaths, message) {
  // 1. 現在の main の commit と tree を取得
  var ref = ghApi("GET", "git/ref/heads/main");
  var parentSha = ref.object.sha;
  var parentCommit = ghApi("GET", "git/commits/" + parentSha);
  var baseTree = parentCommit.tree.sha;

  // 2. news.json の blob 作成
  var newsContent = JSON.stringify(newsList, null, 2) + "\n";
  var newsBlob = ghApi("POST", "git/blobs", { content: newsContent, encoding: "utf-8" });

  // 3. 新規画像の blob 作成
  var imageBlobs = (addedImages || []).map(function (img) {
    var b = ghApi("POST", "git/blobs", { content: img.base64, encoding: "base64" });
    return { path: img.path, sha: b.sha };
  });

  // 4. tree を組み立て
  var treeItems = [
    { path: "data/news.json", mode: "100644", type: "blob", sha: newsBlob.sha }
  ];
  imageBlobs.forEach(function (b) {
    treeItems.push({ path: b.path, mode: "100644", type: "blob", sha: b.sha });
  });
  (deletedImagePaths || []).forEach(function (p) {
    treeItems.push({ path: p, mode: "100644", type: "blob", sha: null });
  });
  var newTree = ghApi("POST", "git/trees", { base_tree: baseTree, tree: treeItems });

  // 5. commit を作成して main を更新
  var commit = ghApi("POST", "git/commits", { message: message, tree: newTree.sha, parents: [parentSha] });
  ghApi("PATCH", "git/refs/heads/main", { sha: commit.sha });
  return commit.sha;
}

// 新規画像のbase64配列から { path, base64 } 配列を生成（パスは date + 8桁UUID）
function prepareNewImages(date, base64Array) {
  return (base64Array || []).map(function (b64) {
    var uuid = Utilities.getUuid().substring(0, 8);
    var path = "images/news/" + (date || "undated") + "-" + uuid + ".jpg";
    return { path: path, base64: b64 };
  });
}

// ニュースエントリの正規化
function normalizeEntry(data, finalImages) {
  return {
    date: data.date || "",
    category: data.category || "",
    category_en: data.category_en || "",
    title: data.title || "",
    title_en: data.title_en || "",
    url: data.url || "",
    paper_title: data.paper_title || "",
    doi: data.doi || "",
    body: (data.body || "").replace(/\n/g, "<br>"),
    body_en: (data.body_en || "").replace(/\n/g, "<br>"),
    images: finalImages || []
  };
}

// ── 追加 ──
function addNews(newsItem) {
  var list = getNewsFromGitHub();
  var newImages = prepareNewImages(newsItem.date, newsItem.new_images);
  var imagePaths = (newsItem.images || []).concat(newImages.map(function (i) { return i.path; }));
  var entry = normalizeEntry(newsItem, imagePaths);
  list.unshift(entry);
  list.sort(function (a, b) { return (b.date || "").localeCompare(a.date || ""); });
  return commitChanges(list, newImages, [], "ニュースを追加: " + (entry.title || "no title"));
}

// ── 編集 ──
function editNews(index, updatedEntry) {
  var list = getNewsFromGitHub();
  if (index < 0 || index >= list.length) throw new Error("Invalid index: " + index);
  var oldImages = list[index].images || [];
  var keptImages = updatedEntry.images || [];
  var deletedImages = oldImages.filter(function (p) { return keptImages.indexOf(p) < 0; });
  var newImages = prepareNewImages(updatedEntry.date, updatedEntry.new_images);
  var finalImages = keptImages.concat(newImages.map(function (i) { return i.path; }));
  list[index] = normalizeEntry(updatedEntry, finalImages);
  list.sort(function (a, b) { return (b.date || "").localeCompare(a.date || ""); });
  return commitChanges(list, newImages, deletedImages, "ニュースを編集: " + (updatedEntry.title || "no title"));
}

// ── 削除 ──
function deleteNews(index) {
  var list = getNewsFromGitHub();
  if (index < 0 || index >= list.length) throw new Error("Invalid index: " + index);
  var removed = list.splice(index, 1)[0];
  var deletedImages = removed.images || [];
  return commitChanges(list, [], deletedImages, "ニュースを削除: " + (removed.title || "no title"));
}