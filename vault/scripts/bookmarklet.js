// ============================================================
// Obsidian Vault ブックマークレット
// ============================================================
// ブラウザのブックマークに登録して、任意のWebページからコンテンツを取り込む
//
// 2つのバージョンがあります:
//
// ============================================================
// VERSION 1: ダウンロード方式（推奨・確実）
// ============================================================
// .mdファイルをダウンロードし、Obsidian Vault の 00_Inbox に手動で移動
//
// ブックマークのURL欄に以下の1行をコピー:
//
// javascript:(function(){const t=document.title||'Untitled',u=window.location.href,s=window.location.hostname.replace('www.',''),d=new Date().toISOString().slice(0,10),dc=d.replace(/-/g,'');function g(){const sel=window.getSelection().toString().trim();if(sel)return sel;for(const q of['article','main','[role="main"]','.content','#content','.spark-page','.sparkpage-content','.post-content','.entry-content']){const el=document.querySelector(q);if(el)return el.innerText.trim()}return document.body.innerText.substring(0,15000)}const c=g(),st=t.replace(/[\/\\:*?"<>|]/g,'_').substring(0,80),md=`---\ntype: research\ndate: "${d}"\nsource: "${s}"\nurl: "${u}"\ntags: [research, web-clip]\nstatus: draft\nimported_at: "${new Date().toISOString()}"\n---\n\n# ${t}\n\n> Source: [${s}](${u})\n\n${c}\n`,b=new Blob([md],{type:'text/markdown'}),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=`${dc}_${st}.md`;a.click();URL.revokeObjectURL(a.href)})();
//
//
// ============================================================
// VERSION 2: Obsidian URI 直接取り込み方式
// ============================================================
// Obsidianが起動していれば、直接Vaultにノートを作成する
// 事前設定: Obsidian > 設定 > コアプラグイン > 「URIスキームの登録」をON
//
// ブックマークのURL欄に以下の1行をコピー:
// ※ YOUR_VAULT_NAME を実際のVault名に置き換えてください
//
// javascript:(function(){const v='YOUR_VAULT_NAME',t=document.title||'Untitled',u=window.location.href,s=window.location.hostname.replace('www.',''),d=new Date().toISOString().slice(0,10),dc=d.replace(/-/g,'');function g(){const sel=window.getSelection().toString().trim();if(sel)return sel;for(const q of['article','main','[role="main"]','.content','#content','.spark-page','.sparkpage-content']){const el=document.querySelector(q);if(el)return el.innerText.trim()}return document.body.innerText.substring(0,10000)}const c=g(),st=t.replace(/[\/\\:*?"<>|]/g,'_').substring(0,80),md=`---\ntype: research\ndate: "${d}"\nsource: "${s}"\nurl: "${u}"\ntags: [research, web-clip]\nstatus: draft\nimported_at: "${new Date().toISOString()}"\n---\n\n# ${t}\n\n> Source: [${s}](${u})\n\n${c}`,fp=`00_Inbox/${dc}_${st}.md`,uri=`obsidian://new?vault=${encodeURIComponent(v)}&file=${encodeURIComponent(fp)}&content=${encodeURIComponent(md)}&overwrite`;window.location.href=uri})();
//
//
// ============================================================
// VERSION 3: コピー方式（最もシンプル）
// ============================================================
// Markdownをクリップボードにコピーするだけ。Obsidian上でペーストする。
//
// javascript:(function(){const t=document.title||'Untitled',u=window.location.href,s=window.location.hostname.replace('www.',''),d=new Date().toISOString().slice(0,10);function g(){const sel=window.getSelection().toString().trim();if(sel)return sel;for(const q of['article','main','[role="main"]','.content','#content']){const el=document.querySelector(q);if(el)return el.innerText.trim()}return document.body.innerText.substring(0,10000)}const c=g(),md=`---\ntype: research\ndate: "${d}"\nsource: "${s}"\nurl: "${u}"\ntags: [research, web-clip]\nstatus: draft\n---\n\n# ${t}\n\n> Source: [${s}](${u})\n\n${c}`;navigator.clipboard.writeText(md).then(()=>alert('Copied to clipboard! Paste into Obsidian.')).catch(()=>{const ta=document.createElement('textarea');ta.value=md;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();alert('Copied to clipboard!')})})();
