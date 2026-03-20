// Obsidian Vault ブックマークレット
// ブラウザのブックマークに登録して、任意のWebページからコンテンツを取り込む
//
// 使い方:
// 1. 以下のコードを新しいブックマークのURL欄に貼り付ける
// 2. GensparkのSparkpageや任意のWebページで実行
// 3. タイトル・タグを確認してダウンロード
// 4. ダウンロードされた.mdファイルをObsidian Vaultの00_Inboxに移動

javascript:(function(){
  const title = document.title || 'Untitled';
  const url = window.location.href;
  const source = window.location.hostname.replace('www.', '');
  const date = new Date().toISOString().slice(0, 10);
  const dateCompact = date.replace(/-/g, '');

  /* ページの主要コンテンツを取得 */
  function getContent() {
    /* 選択テキストがあればそれを使う */
    const sel = window.getSelection().toString().trim();
    if (sel) return sel;

    /* メインコンテンツを探す */
    const selectors = ['article', 'main', '[role="main"]', '.content', '#content'];
    for (const s of selectors) {
      const el = document.querySelector(s);
      if (el) return el.innerText.trim();
    }
    return document.body.innerText.substring(0, 10000);
  }

  const content = getContent();
  const safeTitle = title.replace(/[\/\\:*?"<>|]/g, '_').substring(0, 80);

  const md = `---
type: research
date: "${date}"
source: "${source}"
url: "${url}"
tags: [research, web-clip]
status: draft
imported_at: "${new Date().toISOString()}"
---

# ${title}

> Source: [${source}](${url})

${content}
`;

  /* ダウンロード */
  const blob = new Blob([md], {type: 'text/markdown'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${dateCompact}_${safeTitle}.md`;
  a.click();
  URL.revokeObjectURL(a.href);

  alert('Obsidian Vault用にダウンロードしました: ' + a.download);
})();
