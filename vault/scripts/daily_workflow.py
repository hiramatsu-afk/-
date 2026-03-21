#!/usr/bin/env python3
"""
daily_workflow.py - 日次業務自動化スクリプト

毎朝実行して、その日のブリーフィングを自動生成する。
カレンダー・tl;dv・Vault のデータを統合して日次ノートを準備。

使い方:
    python vault/scripts/daily_workflow.py --morning    # 朝のブリーフィング
    python vault/scripts/daily_workflow.py --evening    # 夕方の振り返り
    python vault/scripts/daily_workflow.py --sync-all   # 全データ同期

cron設定例:
    # 毎朝7時にブリーフィング生成
    0 7 * * * cd /path/to/vault && python scripts/daily_workflow.py --morning
    # 毎日18時に振り返りノート準備
    0 18 * * * cd /path/to/vault && python scripts/daily_workflow.py --evening
    # 毎日21時にtl;dv会議データ同期
    0 21 * * * TLDV_API_KEY=your_key python scripts/tldv_sync.py --days 1
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
VAULT_DIR = SCRIPT_DIR.parent


def run_script(script_name, args=None):
    """Vaultスクリプトを実行"""
    script_path = SCRIPT_DIR / script_name
    cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return result.stdout
    except Exception as e:
        return f"[エラー] {script_name}: {e}"


def create_daily_note(date_str=None):
    """日次ノートのテンプレートを生成"""
    if not date_str:
        date_str = datetime.now().strftime('%Y-%m-%d')

    daily_dir = VAULT_DIR / 'DailyNotes'
    daily_dir.mkdir(exist_ok=True)
    filepath = daily_dir / f"{date_str}.md"

    if filepath.exists():
        print(f"  日次ノート既存: {filepath.name}")
        return filepath

    weekdays = ['月', '火', '水', '木', '金', '土', '日']
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    weekday = weekdays[dt.weekday()]

    content = f"""---
type: daily
date: {date_str}
tags: [日次, スケジュール]
---

# {date_str}（{weekday}）

## 今日のスケジュール
<!-- Googleカレンダーの予定をClaude経由で自動挿入 -->
-

## 優先タスク
- [ ]

## メモ


## 振り返り
<!-- 夕方に記入 -->

"""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  日次ノート作成: {filepath.name}")
    return filepath


def cmd_morning():
    """朝のブリーフィング"""
    today = datetime.now().strftime('%Y-%m-%d')
    print("=" * 60)
    print(f"  朝のブリーフィング - {today}")
    print("=" * 60)

    # 1. 日次ノート作成
    print("\n[1] 日次ノート")
    create_daily_note(today)

    # 2. 未完了アクションアイテム
    print("\n[2] 未完了アクションアイテム")
    output = run_script('vault_analyzer.py', ['--action-items'])
    if output:
        # 最初の20行だけ表示
        lines = output.strip().split('\n')
        for line in lines[:20]:
            print(f"  {line}")
        if len(lines) > 20:
            print(f"  ... 他 {len(lines) - 20} 行")

    # 3. 事業概要
    print("\n[3] 事業概要サマリー")
    output = run_script('business_hub.py', ['--overview'])
    if output:
        for line in output.strip().split('\n'):
            print(f"  {line}")

    print("\n" + "=" * 60)
    print("  Claudeへの依頼例:")
    print("  「今日のカレンダーの予定を確認して、日次ノートに反映して」")
    print("  「未完了タスクの優先順位をつけて」")
    print("  「今週の重点施策を提案して」")
    print("=" * 60)


def cmd_evening():
    """夕方の振り返り"""
    today = datetime.now().strftime('%Y-%m-%d')
    print("=" * 60)
    print(f"  夕方の振り返り - {today}")
    print("=" * 60)

    # 今日のtl;dv会議データを同期
    print("\n[1] 会議データ同期")
    if os.environ.get('TLDV_API_KEY'):
        output = run_script('tldv_sync.py', ['--days', '1'])
        if output:
            for line in output.strip().split('\n')[:10]:
                print(f"  {line}")
    else:
        print("  TLDV_API_KEY未設定 - スキップ")

    # 今日追加されたノート
    print("\n[2] 今日のノート")
    output = run_script('vault_analyzer.py', ['--recent', '5', '--format', 'list'])
    if output:
        for line in output.strip().split('\n')[:10]:
            print(f"  {line}")

    print("\n" + "=" * 60)
    print("  Claudeへの依頼例:")
    print("  「今日の会議内容をまとめて、明日のタスクを整理して」")
    print("  「今週の進捗を分析して、遅れている項目を教えて」")
    print("=" * 60)


def cmd_sync_all():
    """全データ同期"""
    print("全データ同期を開始します...\n")

    # tl;dv同期
    print("[1] tl;dv会議データ同期")
    if os.environ.get('TLDV_API_KEY'):
        output = run_script('tldv_sync.py', ['--days', '7'])
        print(f"  {output.strip().split(chr(10))[-1] if output else 'エラー'}")
    else:
        print("  TLDV_API_KEY未設定 - スキップ")

    # Vault統計
    print("\n[2] Vault統計")
    output = run_script('vault_analyzer.py', ['--stats'])
    if output:
        for line in output.strip().split('\n')[:15]:
            print(f"  {line}")

    # ダッシュボード更新
    print("\n[3] ダッシュボード更新")
    output = run_script('generate_dashboard.py')
    print(f"  {output.strip().split(chr(10))[-1] if output else '完了'}")

    print("\n同期完了!")


def main():
    parser = argparse.ArgumentParser(
        description='日次業務自動化スクリプト')
    parser.add_argument('--morning', action='store_true',
                        help='朝のブリーフィング')
    parser.add_argument('--evening', action='store_true',
                        help='夕方の振り返り')
    parser.add_argument('--sync-all', action='store_true',
                        help='全データ同期')

    args = parser.parse_args()

    if args.morning:
        cmd_morning()
    elif args.evening:
        cmd_evening()
    elif args.sync_all:
        cmd_sync_all()
    else:
        # デフォルトは朝のブリーフィング
        cmd_morning()


if __name__ == '__main__':
    main()
