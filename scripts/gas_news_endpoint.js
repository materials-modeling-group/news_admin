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
    } else if (action === "translate") {
      var translated = LanguageApp.translate(data.text || "", "ja", "en");
      return ContentService.createTextOutput(JSON.stringify({ status: "ok", text: translated }))
        .setMimeType(ContentService.MimeType.JSON);
    } else if (action === "research_get") {
      result = getResearchFromGitHub();
      return ContentService.createTextOutput(JSON.stringify({ status: "ok", data: result }))
        .setMimeType(ContentService.MimeType.JSON);
    } else if (action === "research_save") {
      result = saveResearch(data.body_ja || "", data.body_en || "", data.new_images || []);
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

// ── 重複検出 ヘルパー ──
// 同じDOI、または 同じ日付+同じ正規化タイトル の既存エントリを探す。
// 見つかった場合は index、なければ -1 を返す。
function _normTitle(s) {
  if (!s) return "";
  return s.toString().toLowerCase()
    .replace(/[\s　]+/g, "")
    .replace(/[「」『』【】（）\(\)・,，、。．\.]/g, "");
}
function _normDoi(doi) {
  if (!doi) return "";
  return doi.toString().toLowerCase()
    .replace(/^https?:\/\/(dx\.)?doi\.org\//, "")
    .trim();
}
function findDuplicateIndex(list, entry) {
  var newTitle = _normTitle(entry.title);
  var newDate = entry.date || "";
  var newDoi = _normDoi(entry.doi);
  for (var i = 0; i < list.length; i++) {
    if (newDoi && _normDoi(list[i].doi) === newDoi) {
      return i;
    }
    if (newTitle && (list[i].date || "") === newDate && _normTitle(list[i].title) === newTitle) {
      return i;
    }
  }
  return -1;
}

// 情報量スコア（高いほど完全）
function completenessScore(entry) {
  var s = 0;
  if (entry.title_en) s += 2;
  if (entry.url) s += 1;
  if (entry.paper_title) s += 2;
  if (entry.doi) s += 2;
  s += Math.min(10, Math.floor(((entry.body || "").length) / 50));
  s += Math.min(5, Math.floor(((entry.body_en || "").length) / 50));
  if (entry.images && entry.images.length) s += entry.images.length * 2;
  return s;
}

// ── 追加 ──
// 重複検出: 既存と同じDOIまたは(日付,タイトル)の記事がある場合、
//   - 新規記事の方が情報量が多ければ既存を置換
//   - 既存以下なら投稿をスキップ
function addNews(newsItem) {
  var list = getNewsFromGitHub();
  var newImages = prepareNewImages(newsItem.date, newsItem.new_images);
  var imagePaths = (newsItem.images || []).concat(newImages.map(function (i) { return i.path; }));
  var entry = normalizeEntry(newsItem, imagePaths);

  var dupIndex = findDuplicateIndex(list, entry);
  if (dupIndex >= 0) {
    var newScore = completenessScore(entry);
    var oldScore = completenessScore(list[dupIndex]);
    if (newScore > oldScore) {
      // 既存より情報量が多い → 置換（既存の画像は不要なら削除）
      var oldImages = list[dupIndex].images || [];
      var newImagePathSet = {};
      imagePaths.forEach(function (p) { newImagePathSet[p] = true; });
      var deletedImages = oldImages.filter(function (p) { return !newImagePathSet[p]; });
      list[dupIndex] = entry;
      list.sort(function (a, b) { return (b.date || "").localeCompare(a.date || ""); });
      var sha = commitChanges(list, newImages, deletedImages,
        "ニュースを置換（重複検出）: " + (entry.title || "no title"));
      return { action: "replaced", index: dupIndex, sha: sha };
    } else {
      // 既存以下 → スキップ（commitしない＝新規画像もアップロードされない）
      return { action: "skipped", reason: "duplicate", index: dupIndex };
    }
  }

  // 重複なし: 通常通り先頭に追加
  list.unshift(entry);
  list.sort(function (a, b) { return (b.date || "").localeCompare(a.date || ""); });
  var sha = commitChanges(list, newImages, [], "ニュースを追加: " + (entry.title || "no title"));
  return { action: "added", sha: sha };
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

// ── Research: Markdown取得 ──
// data/research.md と data/research-en.md を読み、両方を返す。
// ファイルが未作成の場合は空文字を返す。
function getResearchFromGitHub() {
  return {
    body_ja: _getFileContentOrEmpty("data/research.md"),
    body_en: _getFileContentOrEmpty("data/research-en.md")
  };
}

function _getFileContentOrEmpty(path) {
  var props = PropertiesService.getScriptProperties();
  var token = props.getProperty("GITHUB_TOKEN");
  var repo = props.getProperty("GITHUB_REPO");
  var url = "https://api.github.com/repos/" + repo + "/contents/" + path + "?ref=main";
  var resp = UrlFetchApp.fetch(url, {
    method: "GET",
    headers: { Authorization: "Bearer " + token, Accept: "application/vnd.github.v3+json" },
    muteHttpExceptions: true
  });
  var code = resp.getResponseCode();
  if (code === 404) return "";
  if (code < 200 || code >= 300) {
    throw new Error("GitHub API GET " + path + " " + code + ": " + resp.getContentText());
  }
  var info = JSON.parse(resp.getContentText());
  return Utilities.newBlob(Utilities.base64Decode(info.content)).getDataAsString();
}

// ── Research: Markdown保存 ──
// 日本語・英語のMarkdownと、新規アップロード画像を1コミットにまとめて反映する。
// new_images: [{ base64, filename }] — filename拡張子で保存パスを決定
function saveResearch(bodyJa, bodyEn, newImages) {
  var ref = ghApi("GET", "git/ref/heads/main");
  var parentSha = ref.object.sha;
  var parentCommit = ghApi("GET", "git/commits/" + parentSha);
  var baseTree = parentCommit.tree.sha;

  var jaBlob = ghApi("POST", "git/blobs", { content: bodyJa, encoding: "utf-8" });
  var enBlob = ghApi("POST", "git/blobs", { content: bodyEn, encoding: "utf-8" });

  var treeItems = [
    { path: "data/research.md", mode: "100644", type: "blob", sha: jaBlob.sha },
    { path: "data/research-en.md", mode: "100644", type: "blob", sha: enBlob.sha }
  ];

  (newImages || []).forEach(function (img) {
    var b = ghApi("POST", "git/blobs", { content: img.base64, encoding: "base64" });
    treeItems.push({ path: img.path, mode: "100644", type: "blob", sha: b.sha });
  });

  var newTree = ghApi("POST", "git/trees", { base_tree: baseTree, tree: treeItems });
  var commit = ghApi("POST", "git/commits", {
    message: "Research ページを更新",
    tree: newTree.sha,
    parents: [parentSha]
  });
  ghApi("PATCH", "git/refs/heads/main", { sha: commit.sha });
  return { action: "saved", sha: commit.sha };
}

// ── 削除 ──
function deleteNews(index) {
  var list = getNewsFromGitHub();
  if (index < 0 || index >= list.length) throw new Error("Invalid index: " + index);
  var removed = list.splice(index, 1)[0];
  var deletedImages = removed.images || [];
  return commitChanges(list, [], deletedImages, "ニュースを削除: " + (removed.title || "no title"));
}