# Obsidian Knowledge Base

## 構造 (PARAメソッド)
- `vault/00_Inbox/` - 未整理の取り込みノート
- `vault/01_Projects/` - 進行中のプロジェクト
- `vault/02_Areas/` - 継続的な責任領域
- `vault/03_Resources/` - 参考資料
- `vault/04_Archive/` - 完了・非アクティブ
- `vault/05_Confidential/` - 機密情報（Git管理外）
- `vault/MeetingNotes/` - 議事録
- `vault/Research/` - リサーチノート
- `vault/DailyNotes/` - 日次ノート
- `vault/Templates/` - テンプレート
- `vault/attachments/` - 添付ファイル（PDF/画像等、Git管理外）

## スクリプト
- `vault/scripts/save_to_vault.py` - コンテンツ保存（meeting/research/inbox/daily）
- `vault/scripts/organize_inbox.py` - Inbox整理ヘルパー
- `vault/scripts/genspark_import.py` - Genspark等の外部リサーチ取り込み
- `vault/scripts/tldv_sync.py` - tl;dv議事録の自動同期（API経由）
- `vault/scripts/tldv_webhook_server.py` - tl;dv Webhook受信サーバー（リアルタイム自動保存）
- `vault/scripts/vault_analyzer.py` - Vault分析（統計/タスク抽出/週次レポート）
- `vault/scripts/bookmarklet.js` - ブラウザからWebページをVaultに取り込むブックマークレット

## Claudeへの指示
- ノートを保存する際は `save_to_vault.py` を使うか、直接Markdownファイルを作成する
- フロントマター（YAML）を必ず含める（type, date, tags）
- ファイル名は `YYYYMMDD_タイトル.md` 形式
- 新しいコンテンツはまず `00_Inbox` に入れ、後で適切なフォルダに移動する
- `vault_analyzer.py --recent N --format summary` でノートを読み込み、要約・分析に活用する
- 議事録のアクションアイテムは `vault_analyzer.py --action-items` で集約して管理する
- 週次レポートは `vault_analyzer.py --weekly-report` の出力をもとに生成する

## tl;dv連携
- APIキー: 環境変数 `TLDV_API_KEY` に設定
- 手動同期: `python vault/scripts/tldv_sync.py --days 7`
- 自動同期: `tldv_webhook_server.py` を起動 + tl;dv Webhookに登録
- MCP Server: `tldv-mcp-server` でClaude Desktopから直接会議データにアクセス可能
- ダッシュボード: `python vault/scripts/generate_dashboard.py --open` でブラウザ表示

## 注意事項
- `vault/05_Confidential/` は `.gitignore` で除外済み。NDA・契約書・個人情報はここに置く
- `vault/attachments/` もGit管理外。PDF・画像・動画はここに格納する
- ノートが大量になってもテキスト(.md)のみなら問題ない。パフォーマンス劣化は主にバイナリファイルが原因
