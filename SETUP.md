# Obsidian Knowledge Base - セットアップガイド

## 1. 初期設定

```bash
# 依存パッケージのインストール
pip install -r vault/scripts/requirements.txt
```

## 2. tl;dv 連携セットアップ

### Step 1: APIキーの取得
1. https://tldv.io/app/settings/personal-settings/api-keys にアクセス
2. 「Generate New API Key」でキーを生成
3. キーを安全な場所に保存

### Step 2: 環境変数の設定
```bash
# .bashrc / .zshrc に追加
export TLDV_API_KEY="your_api_key_here"

# 反映
source ~/.bashrc  # or source ~/.zshrc
```

### Step 3: 接続テスト
```bash
python vault/scripts/tldv_sync.py --test
```
成功すると以下のように表示されます:
```
=== tl;dv API Connection Test ===

  API Key:    VALID
  Meetings:   accessible
  Total:      42 meeting(s) found
  ...
  Connection test PASSED. Ready to sync.
```

### Step 4: 過去の全ミーティングを一括同期
```bash
# まずドライランで確認
python vault/scripts/tldv_sync.py --all --dry-run

# 問題なければ実行
python vault/scripts/tldv_sync.py --all
```

### Step 5: 自動同期の設定（2つの方法）

#### 方法A: cron（定期同期）
```bash
crontab -e
# 以下を追加（毎日9時に前日分を同期）
0 9 * * * TLDV_API_KEY=your_key python /path/to/vault/scripts/tldv_sync.py --days 1 >> /var/log/tldv_sync.log 2>&1
```

#### 方法B: Webhookサーバー（リアルタイム同期）
```bash
# サーバー起動
python vault/scripts/tldv_webhook_server.py

# 別ターミナルでngrokを起動（外部URLが必要な場合）
ngrok http 5050

# tl;dv設定で以下を登録:
#   Settings > Webhooks > Configure new Webhook
#   Event: TranscriptReady
#   Endpoint URL: https://<your-ngrok-url>/webhook/tldv
```

### Step 6: MCP Server（Claude直接連携）
```bash
# tl;dv MCP Serverをクローン
git clone https://github.com/tldv-public/tldv-mcp-server.git
cd tldv-mcp-server
npm install && npm run build

# Claude Codeに登録
claude mcp add-json "tldv" '{"command":"node","args":["'$(pwd)'/dist/index.js"],"env":{"TLDV_API_KEY":"your_key"}}'
```

## 3. ブックマークレット設定

`vault/scripts/bookmarklet.js` に3つのバージョンがあります:

| Version | 方法 | 特徴 |
|---------|------|------|
| V1 | .mdファイルをダウンロード | 確実。00_Inboxに手動移動 |
| V2 | Obsidian URIで直接作成 | Obsidian起動中に自動取り込み |
| V3 | クリップボードにコピー | 最もシンプル |

### 登録手順（V1の場合）
1. ブラウザのブックマークバーを右クリック → 「ブックマークを追加」
2. 名前: `Save to Vault`
3. URL: `bookmarklet.js` 内の VERSION 1 の javascript:... 行をコピペ
4. Genspark等のページで実行 → .mdファイルがダウンロードされる

### V2（Obsidian直接取り込み）を使う場合
- javascript:... 内の `YOUR_VAULT_NAME` を実際のVault名に置換してから登録

## 4. Genspark連携

```bash
# GensparkからMarkdownでエクスポートしたファイルを取り込み
python vault/scripts/genspark_import.py -t "AI動向調査" -s "Genspark" -f exported.md

# URLも記録する場合
python vault/scripts/genspark_import.py -t "市場調査" -s "Genspark" -u "https://..." -f report.md

# macOS: クリップボードから直接
pbpaste | python vault/scripts/genspark_import.py -t "メモ"
```

## 5. 日常の使い方

### 議事録・商談内容にすぐアクセス
```bash
# ダッシュボード（概要 + 直近の会議 + 未完了アクション）
python vault/scripts/vault_analyzer.py --dashboard

# キーワード検索（例: 「価格」と「提案」の両方が含まれるノート）
python vault/scripts/vault_analyzer.py --search "価格" --search "提案"

# 特定の相手との全ミーティング
python vault/scripts/vault_analyzer.py --attendee "田中"
python vault/scripts/vault_analyzer.py --attendee "A社"

# 未完了アクションアイテムの一覧
python vault/scripts/vault_analyzer.py --action-items
```

### Claude活用
```bash
# 最近のノートをClaudeに要約してもらう
python vault/scripts/vault_analyzer.py --recent 7 --format summary

# 週次レポート生成
python vault/scripts/vault_analyzer.py --weekly-report
```

## 6. YouTube コメントモデレーション

YouTubeコメントの自動モデレーション（ハート付与・不適切コメント削除・返信案生成→Slack承認）。

### Step 1: Google Cloud プロジェクトの準備
1. Google Cloud Console でプロジェクトを作成
2. YouTube Data API v3 を有効化
3. OAuth 2.0 クライアントID を作成（デスクトップアプリケーション）
4. `client_secret.json` をダウンロード

### Step 2: OAuth クライアントシークレットを配置
```bash
mkdir -p vault/scripts/youtube_config
cp ~/Downloads/client_secret_*.json vault/scripts/youtube_config/client_secret.json
```

### Step 3: 環境変数の設定
```bash
# .bashrc / .zshrc に追加
export ANTHROPIC_API_KEY="your_anthropic_api_key"
export SLACK_BOT_TOKEN="xoxb-your-slack-bot-token"
export SLACK_CHANNEL_ID="C0XXXXXXXXX"
```

Slack Bot に必要な権限（OAuth Scopes）:
- `chat:write` - メッセージ送信
- Interactivity を有効化し、Request URL に Webhook サーバーのURLを設定

### Step 4: OAuth認証（初回のみ）
```bash
python vault/scripts/youtube_comment_mod.py --auth
```
ブラウザが開くので、YouTubeチャンネルのGoogleアカウントでログインして許可。

### Step 5: 動作テスト
```bash
# ドライラン（実際の操作なし）
python vault/scripts/youtube_comment_mod.py --dry-run

# 特定の動画でテスト
python vault/scripts/youtube_comment_mod.py --video-id VIDEO_ID --dry-run
```

### Step 6: 運用
```bash
# 日次チェック（過去24時間のコメント）
python vault/scripts/youtube_comment_mod.py

# Slack承認ワークフロー用サーバー起動
python vault/scripts/youtube_comment_mod.py --slack-server

# cron設定（毎日朝9時に実行）
0 9 * * * cd /path/to/repo && python vault/scripts/youtube_comment_mod.py --days 1 >> /var/log/youtube_mod.log 2>&1
```

### ペルソナ設定のカスタマイズ
`vault/scripts/youtube_persona.json` を編集して、返信トーンや削除ルールを調整できます。

## 7. 推奨Obsidianプラグイン

- **Dataview**: ノートをデータベースのようにクエリ・表示
- **Templater**: テンプレートの自動適用
- **Calendar**: DailyNotesとカレンダー連携
- **Tasks**: タスク管理の強化
- **Full Text Search**: 高速な全文検索
