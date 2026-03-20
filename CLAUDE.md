# Obsidian Knowledge Base

## 構造 (PARAメソッド)
- `vault/00_Inbox/` - 未整理の取り込みノート
- `vault/01_Projects/` - 進行中のプロジェクト
- `vault/02_Areas/` - 継続的な責任領域
- `vault/03_Resources/` - 参考資料
- `vault/04_Archive/` - 完了・非アクティブ
- `vault/MeetingNotes/` - 議事録
- `vault/Research/` - リサーチノート
- `vault/DailyNotes/` - 日次ノート
- `vault/Templates/` - テンプレート

## スクリプト
- `vault/scripts/save_to_vault.py` - コンテンツ保存（meeting/research/inbox/daily）
- `vault/scripts/organize_inbox.py` - Inbox整理ヘルパー

## Claudeへの指示
- ノートを保存する際は `save_to_vault.py` を使うか、直接Markdownファイルを作成する
- フロントマター（YAML）を必ず含める（type, date, tags）
- ファイル名は `YYYYMMDD_タイトル.md` 形式
- 新しいコンテンツはまず `00_Inbox` に入れ、後で適切なフォルダに移動する
