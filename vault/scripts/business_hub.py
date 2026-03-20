#!/usr/bin/env python3
"""
business_hub.py - 事業データ統合管理ハブ

全事業部のデータを横断的に検索・分析・レポートするCLIツール。
Claude Code から呼び出して、ビジネスインテリジェンスとして活用する。

使い方:
    python vault/scripts/business_hub.py --overview          # 事業全体の概要
    python vault/scripts/business_hub.py --pipeline          # 商談パイプライン
    python vault/scripts/business_hub.py --franchise-summary  # 加盟店サマリー
    python vault/scripts/business_hub.py --weekly-brief       # 週次ブリーフィング
    python vault/scripts/business_hub.py --search "キーワード" # 全データ横断検索
    python vault/scripts/business_hub.py --customer "顧客名"  # 顧客履歴
"""

import argparse
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Vault のルートディレクトリ
SCRIPT_DIR = Path(__file__).parent
VAULT_DIR = SCRIPT_DIR.parent


def parse_frontmatter(filepath):
    """Markdownファイルのフロントマターを解析"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return {}, ""

    frontmatter = {}
    body = content

    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            fm_text = parts[1].strip()
            body = parts[2].strip()
            for line in fm_text.split('\n'):
                if ':' in line:
                    key, val = line.split(':', 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if val.startswith('[') and val.endswith(']'):
                        val = [v.strip().strip('"').strip("'")
                               for v in val[1:-1].split(',')]
                    frontmatter[key] = val

    return frontmatter, body


def get_all_notes():
    """Vault内の全Markdownファイルを取得"""
    notes = []
    for md_file in VAULT_DIR.rglob('*.md'):
        rel = md_file.relative_to(VAULT_DIR)
        # テンプレートとスクリプトは除外
        if str(rel).startswith(('Templates/', 'scripts/', '.obsidian/')):
            continue
        fm, body = parse_frontmatter(md_file)
        notes.append({
            'path': md_file,
            'relative': str(rel),
            'folder': str(rel).split('/')[0] if '/' in str(rel) else '',
            'frontmatter': fm,
            'body': body,
            'name': md_file.stem,
        })
    return notes


def extract_action_items(body):
    """本文からアクションアイテム（チェックボックス）を抽出"""
    items = []
    for line in body.split('\n'):
        line = line.strip()
        if line.startswith('- [ ]'):
            items.append(('pending', line[5:].strip()))
        elif line.startswith('- [x]') or line.startswith('- [X]'):
            items.append(('done', line[5:].strip()))
    return items


def cmd_overview(notes):
    """事業全体の概要を表示"""
    print("=" * 60)
    print("📊 事業概要ダッシュボード")
    print(f"   生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # フォルダ別集計
    folder_counts = {}
    for n in notes:
        folder = n['folder']
        folder_counts[folder] = folder_counts.get(folder, 0) + 1

    print("\n■ ノート数（フォルダ別）")
    for folder, count in sorted(folder_counts.items()):
        if folder:
            print(f"  {folder}: {count}件")

    # 全アクションアイテム
    pending = []
    for n in notes:
        items = extract_action_items(n['body'])
        for status, text in items:
            if status == 'pending':
                pending.append((n['name'], text))

    print(f"\n■ 未完了アクションアイテム: {len(pending)}件")
    for name, text in pending[:15]:
        print(f"  [{name}] {text}")
    if len(pending) > 15:
        print(f"  ... 他{len(pending) - 15}件")

    # 最近のノート
    recent = sorted(notes, key=lambda n: n['frontmatter'].get('date', ''), reverse=True)[:5]
    print("\n■ 最近のノート")
    for n in recent:
        date = n['frontmatter'].get('date', '不明')
        print(f"  [{date}] {n['name']} ({n['folder']})")


def cmd_pipeline(notes):
    """商談パイプラインを表示"""
    print("=" * 60)
    print("🏠 商談パイプライン")
    print("=" * 60)

    meetings = [n for n in notes if n['frontmatter'].get('type') == 'meeting']
    customer_meetings = [m for m in meetings
                         if m['frontmatter'].get('subtype') == 'customer'
                         or '商談' in str(m['frontmatter'].get('tags', []))
                         or '面談' in m['name']]

    if not customer_meetings:
        # タグやフォルダから推定
        customer_meetings = [n for n in notes
                             if n['folder'] == 'MeetingNotes'
                             and ('商談' in n['body'] or '面談' in n['body']
                                  or '提案' in n['body'] or '契約' in n['body'])]

    stages = {'初回': [], '提案': [], '契約': [], 'フォロー': [], 'その他': []}

    for m in customer_meetings:
        stage = m['frontmatter'].get('deal_stage', '')
        if not stage:
            body_lower = m['body']
            if '初回' in m['name'] or 'ヒアリング' in m['name']:
                stage = '初回'
            elif '提案' in m['name']:
                stage = '提案'
            elif '契約' in m['name']:
                stage = '契約'
            else:
                stage = 'その他'
        if stage in stages:
            stages[stage].append(m)
        else:
            stages['その他'].append(m)

    for stage_name, items in stages.items():
        if items:
            print(f"\n【{stage_name}】({len(items)}件)")
            for m in items:
                date = m['frontmatter'].get('date', '')
                attendees = m['frontmatter'].get('attendees', '')
                print(f"  {date} | {m['name']}")
                if attendees:
                    print(f"         参加者: {attendees}")


def cmd_franchise_summary(notes):
    """加盟店関連のサマリー"""
    print("=" * 60)
    print("🏗️ 加盟店サマリー")
    print("=" * 60)

    franchise = [n for n in notes
                 if '加盟' in str(n['frontmatter'].get('tags', []))
                 or '工務店' in str(n['frontmatter'].get('tags', []))
                 or '加盟' in n['body'] or '工務店' in n['body']]

    if not franchise:
        print("\n  加盟店関連のノートがまだありません。")
        print("  テンプレート: Templates/franchise-meeting.md を使って記録を開始してください。")
        return

    print(f"\n関連ノート: {len(franchise)}件")
    for n in sorted(franchise, key=lambda x: x['frontmatter'].get('date', ''), reverse=True):
        date = n['frontmatter'].get('date', '')
        print(f"  [{date}] {n['name']} ({n['folder']})")

    # アクションアイテム
    pending = []
    for n in franchise:
        items = extract_action_items(n['body'])
        for status, text in items:
            if status == 'pending':
                pending.append((n['name'], text))

    if pending:
        print(f"\n未完了アクション: {len(pending)}件")
        for name, text in pending:
            print(f"  [{name}] {text}")


def cmd_weekly_brief(notes):
    """週次ブリーフィング生成"""
    print("=" * 60)
    print("📋 週次ブリーフィング")
    week_start = datetime.now() - timedelta(days=7)
    print(f"   期間: {week_start.strftime('%Y-%m-%d')} 〜 {datetime.now().strftime('%Y-%m-%d')}")
    print("=" * 60)

    # 今週のノート
    recent = []
    for n in notes:
        date_str = n['frontmatter'].get('date', '')
        try:
            note_date = datetime.strptime(date_str, '%Y-%m-%d')
            if note_date >= week_start:
                recent.append(n)
        except (ValueError, TypeError):
            pass

    # 種別ごとに分類
    meetings = [n for n in recent if n['folder'] == 'MeetingNotes'
                or n['frontmatter'].get('type') == 'meeting']
    research = [n for n in recent if n['folder'] == 'Research'
                or n['frontmatter'].get('type') == 'research']
    others = [n for n in recent if n not in meetings and n not in research]

    print(f"\n■ 今週の会議: {len(meetings)}件")
    for m in meetings:
        date = m['frontmatter'].get('date', '')
        attendees = m['frontmatter'].get('attendees', '')
        print(f"  [{date}] {m['name']}")
        if attendees:
            print(f"           参加者: {attendees}")

    print(f"\n■ 今週のリサーチ: {len(research)}件")
    for r in research:
        date = r['frontmatter'].get('date', '')
        print(f"  [{date}] {r['name']}")

    if others:
        print(f"\n■ その他: {len(others)}件")
        for o in others:
            print(f"  {o['name']} ({o['folder']})")

    # 全アクションアイテム集約
    all_pending = []
    for n in recent:
        items = extract_action_items(n['body'])
        for status, text in items:
            if status == 'pending':
                all_pending.append((n['name'], text))

    print(f"\n■ 今週発生した未完了アクション: {len(all_pending)}件")
    for name, text in all_pending:
        print(f"  [{name}] {text}")

    print("\n■ Claudeへの依頼例:")
    print("  「今週の会議内容を要約して、来週の優先事項を提案してください」")
    print("  「未完了アクションの優先順位をつけてください」")


def cmd_search(notes, keyword):
    """全データ横断検索"""
    keywords = keyword.split()
    print(f"🔍 検索: {keyword}")
    print("-" * 40)

    results = []
    for n in notes:
        full_text = f"{n['name']} {n['body']} {str(n['frontmatter'])}"
        if all(kw.lower() in full_text.lower() for kw in keywords):
            results.append(n)

    if not results:
        print("  該当なし")
        return

    print(f"  {len(results)}件ヒット\n")
    for n in results:
        date = n['frontmatter'].get('date', '')
        print(f"  [{date}] {n['relative']}")
        # コンテキスト表示（キーワード周辺）
        for kw in keywords:
            for line in n['body'].split('\n'):
                if kw.lower() in line.lower():
                    print(f"    > {line.strip()[:80]}")
                    break


def cmd_customer(notes, customer_name):
    """顧客・取引先の全履歴を表示"""
    print(f"👤 顧客履歴: {customer_name}")
    print("=" * 60)

    results = []
    for n in notes:
        full_text = f"{n['name']} {n['body']} {str(n['frontmatter'])}"
        if customer_name.lower() in full_text.lower():
            results.append(n)

    if not results:
        print(f"  「{customer_name}」に関するデータが見つかりません。")
        return

    results.sort(key=lambda x: x['frontmatter'].get('date', ''))

    print(f"\n関連ノート: {len(results)}件（時系列順）\n")
    for n in results:
        date = n['frontmatter'].get('date', '')
        ntype = n['frontmatter'].get('type', '')
        print(f"  [{date}] [{ntype}] {n['name']}")

        # アクションアイテム表示
        items = extract_action_items(n['body'])
        pending = [t for s, t in items if s == 'pending']
        if pending:
            for text in pending:
                print(f"    ⬜ {text}")


def main():
    parser = argparse.ArgumentParser(
        description='事業データ統合管理ハブ - Claude Code連携')
    parser.add_argument('--overview', action='store_true',
                        help='事業全体の概要')
    parser.add_argument('--pipeline', action='store_true',
                        help='商談パイプライン')
    parser.add_argument('--franchise-summary', action='store_true',
                        help='加盟店サマリー')
    parser.add_argument('--weekly-brief', action='store_true',
                        help='週次ブリーフィング')
    parser.add_argument('--search', type=str,
                        help='全データ横断検索')
    parser.add_argument('--customer', type=str,
                        help='顧客・取引先の全履歴')

    args = parser.parse_args()

    notes = get_all_notes()

    if args.overview:
        cmd_overview(notes)
    elif args.pipeline:
        cmd_pipeline(notes)
    elif args.franchise_summary:
        cmd_franchise_summary(notes)
    elif args.weekly_brief:
        cmd_weekly_brief(notes)
    elif args.search:
        cmd_search(notes, args.search)
    elif args.customer:
        cmd_customer(notes, args.customer)
    else:
        # デフォルトは概要表示
        cmd_overview(notes)


if __name__ == '__main__':
    main()
