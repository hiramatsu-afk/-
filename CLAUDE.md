# Obsidian Knowledge Base - 事業統合管理システム

## 事業構造
- **本部**: 人事、組織設計、原価管理
- **全国展開事業部**: 加盟開拓、加盟店対応（約90社の工務店）
- **住宅事業部**: 東京支店、静岡支店
- **2030年目標**: 売上107億円

## 構造 (PARAメソッド)
- `vault/00_Inbox/` - 未整理の取り込みノート
- `vault/01_Projects/` - 進行中のプロジェクト
  - `2030事業計画/` - 売上107億円ロードマップ
  - `中小企業加速化補助金/` - 補助金進捗管理
  - `YouTube/` - YouTube企画・実績管理
- `vault/02_Areas/` - 継続的な責任領域
  - `本部/` - 人事・組織設計・原価管理
  - `全国展開事業部/` - 加盟店90社の管理
  - `住宅事業部/` - 東京・静岡支店の顧客対応
  - `マーケティング/` - YouTube・Web・数字管理
  - `財務・管理会計/` - 資金調達・管理会計
- `vault/03_Resources/` - 参考資料
  - `加盟店データ/` - 加盟店マスターデータ
  - `顧客データ/` - 顧客情報
  - `競合分析/` - 競合リサーチ
- `vault/04_Archive/` - 完了・非アクティブ
- `vault/MeetingNotes/` - 議事録
- `vault/Research/` - リサーチノート
- `vault/DailyNotes/` - 日次ノート
- `vault/Templates/` - テンプレート

## スクリプト
- `vault/scripts/business_hub.py` - **事業データ統合ハブ**（概要/パイプライン/週次ブリーフィング）
- `vault/scripts/gdrive_sync.py` - **Google Drive同期**（ドキュメント・スプレッドシート→Vault）
- `vault/scripts/save_to_vault.py` - コンテンツ保存（meeting/research/inbox/daily）
- `vault/scripts/organize_inbox.py` - Inbox整理ヘルパー
- `vault/scripts/genspark_import.py` - Genspark等の外部リサーチ取り込み
- `vault/scripts/tldv_sync.py` - tl;dv議事録の自動同期（API経由）
- `vault/scripts/tldv_webhook_server.py` - tl;dv Webhook受信サーバー（リアルタイム自動保存）
- `vault/scripts/vault_analyzer.py` - Vault分析（統計/タスク抽出/週次レポート）
- `vault/scripts/generate_dashboard.py` - HTMLダッシュボード生成
- `vault/scripts/bookmarklet.js` - ブラウザからWebページをVaultに取り込むブックマークレット

## テンプレート
- `Templates/meeting-note.md` - 一般会議
- `Templates/customer-meeting.md` - **顧客面談（住宅事業部）** ※商談ステージ管理付き
- `Templates/franchise-meeting.md` - **加盟店MTG（全国展開事業部）**
- `Templates/youtube-plan.md` - **YouTube企画・実績管理**
- `Templates/weekly-kpi.md` - **週次KPIレポート**（マーケ・支店別数字）
- `Templates/research-note.md` - リサーチノート
- `Templates/daily-note.md` - 日次ノート
- `Templates/inbox-item.md` - Inbox取り込み

## Claudeへの指示
- ノートを保存する際は `save_to_vault.py` を使うか、直接Markdownファイルを作成する
- フロントマター（YAML）を必ず含める（type, date, tags）
- ファイル名は `YYYYMMDD_タイトル.md` 形式
- 新しいコンテンツはまず `00_Inbox` に入れ、後で適切なフォルダに移動する
- **事業全体の概要把握**: `business_hub.py --overview`
- **商談パイプライン確認**: `business_hub.py --pipeline`
- **加盟店状況確認**: `business_hub.py --franchise-summary`
- **週次ブリーフィング**: `business_hub.py --weekly-brief`
- **顧客履歴検索**: `business_hub.py --customer "顧客名"`
- `vault_analyzer.py --recent N --format summary` でノートを読み込み、要約・分析に活用する
- 議事録のアクションアイテムは `vault_analyzer.py --action-items` で集約して管理する
- 週次レポートは `vault_analyzer.py --weekly-report` の出力をもとに生成する

## Google Drive連携
- セットアップ: `python vault/scripts/gdrive_sync.py --setup`
- ファイル一覧: `python vault/scripts/gdrive_sync.py --list`
- フォルダ同期: `python vault/scripts/gdrive_sync.py --sync-folder FOLDER_ID`
- 個別同期: `python vault/scripts/gdrive_sync.py --sync-file FILE_ID`
- ドキュメント・スプレッドシートをMarkdownに変換してVaultに保存

## tl;dv連携
- APIキー: 環境変数 `TLDV_API_KEY` に設定
- 手動同期: `python vault/scripts/tldv_sync.py --days 7`
- 自動同期: `tldv_webhook_server.py` を起動 + tl;dv Webhookに登録
- MCP Server: `tldv-mcp-server` でClaude Desktopから直接会議データにアクセス可能

## 日次ワークフロー
- `vault/scripts/daily_workflow.py` - 日次業務自動化
- **朝のブリーフィング**: `python vault/scripts/daily_workflow.py --morning`
- **夕方の振り返り**: `python vault/scripts/daily_workflow.py --evening`
- **全データ同期**: `python vault/scripts/daily_workflow.py --sync-all`
- cron設定: 毎朝7時ブリーフィング / 毎日18時振り返り / 毎日21時tl;dv同期

## MCP連携（Claude Code / Claude Desktop）
- **Gmail**: メールの検索・閲覧・下書き作成
- **Slack**: チャンネル閲覧・メッセージ送信・検索
- **Google Calendar**: 予定の確認・作成・空き時間検索
- **tl;dv**: 会議データの直接アクセス

## メール自動化（Gmail MCP）
Claudeへの依頼例:
- 「未読メールを確認して、重要なものをリストアップして」
- 「○○さんからのメールを検索して、内容をまとめて」
- 「△△の件で返信の下書きを作成して」
- 「今週届いた加盟店からのメールを一覧にして」
※ Gmail MCPのパーミッション設定が必要（Google Cloud Console で Gmail API を有効化）

## Slack自動化
Claudeへの依頼例:
- 「#generalチャンネルの最新メッセージを確認して」
- 「○○さんにSlackで連絡して」
- 「今週のSlackで重要な会話をまとめて」

## カレンダー連携
Claudeへの依頼例:
- 「今週のスケジュールを確認して日次ノートに反映して」
- 「来週の空き時間を教えて」
- 「○○さんとの打ち合わせを設定して」
- 「面談予定の事前準備ノートを作成して」（カレンダー情報から自動で顧客情報を抽出）
