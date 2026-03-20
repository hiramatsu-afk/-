#!/usr/bin/env python3
"""
Obsidian Vault分析スクリプト - Claude活用の基盤

Vault内のノートを分析し、以下の出力を生成する:
  - ノートの要約・統計
  - 未処理タスクの抽出
  - 議事録からのアクションアイテム集約
  - 週次/月次レポート生成

Claude Code や Claude API と組み合わせて使うことを想定。

使い方:
  # Vault全体の統計を表示
  python vault_analyzer.py --stats

  # 未処理タスク（チェックボックス）を全ノートから抽出
  python vault_analyzer.py --tasks

  # 最近のノートを要約用に出力（Claudeに渡す用）
  python vault_analyzer.py --recent 7 --format summary

  # 議事録のアクションアイテムを集約
  python vault_analyzer.py --action-items

  # 週次レポート用のデータを生成
  python vault_analyzer.py --weekly-report

  # 特定フォルダのノートを一覧
  python vault_analyzer.py --list MeetingNotes
"""

import argparse
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parent.parent

# 除外パターン
EXCLUDE_DIRS = {".obsidian", "scripts", "Templates", ".git"}


def iter_notes(folder: str = None) -> list[Path]:
    """Vault内の.mdファイルを列挙"""
    if folder:
        search_root = VAULT_ROOT / folder
    else:
        search_root = VAULT_ROOT

    notes = []
    for md in search_root.rglob("*.md"):
        if any(part in EXCLUDE_DIRS for part in md.relative_to(VAULT_ROOT).parts):
            continue
        notes.append(md)
    return sorted(notes, key=lambda p: p.stat().st_mtime, reverse=True)


def parse_frontmatter(content: str) -> dict:
    """YAMLフロントマターをパース（簡易版）"""
    fm = {}
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if match:
        for line in match.group(1).split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                fm[key.strip()] = value.strip().strip('"').strip("'")
    return fm


def extract_tasks(content: str) -> list[dict]:
    """チェックボックス形式のタスクを抽出"""
    tasks = []
    for line in content.split("\n"):
        m = re.match(r'\s*- \[([ xX])\]\s*(.*)', line)
        if m:
            tasks.append({
                "done": m.group(1) != " ",
                "text": m.group(2).strip(),
            })
    return tasks


def get_note_date(filepath: Path, frontmatter: dict) -> datetime | None:
    """ノートの日付を取得（フロントマター優先、ファイル名フォールバック）"""
    date_str = frontmatter.get("date", "")
    if date_str:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            pass

    # ファイル名からの抽出: YYYYMMDD_... or YYYY-MM-DD...
    m = re.match(r'(\d{8})_', filepath.name)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d")
        except ValueError:
            pass

    m = re.match(r'(\d{4}-\d{2}-\d{2})', filepath.name)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d")
        except ValueError:
            pass
    return None


def cmd_stats():
    """Vault全体の統計"""
    notes = iter_notes()
    type_counter = Counter()
    tag_counter = Counter()
    folder_counter = Counter()

    for note in notes:
        content = note.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(content)
        note_type = fm.get("type", "unknown")
        type_counter[note_type] += 1
        folder_counter[note.parent.name] += 1
        tags_str = fm.get("tags", "")
        for tag in re.findall(r'[\w-]+', tags_str):
            tag_counter[tag] += 1

    print(f"=== Vault Statistics ===")
    print(f"Total notes: {len(notes)}")
    print(f"\nBy type:")
    for t, c in type_counter.most_common():
        print(f"  {t}: {c}")
    print(f"\nBy folder:")
    for f, c in folder_counter.most_common():
        print(f"  {f}: {c}")
    print(f"\nTop tags:")
    for t, c in tag_counter.most_common(15):
        print(f"  #{t}: {c}")


def cmd_tasks():
    """全ノートから未処理タスクを抽出"""
    notes = iter_notes()
    all_tasks = []

    for note in notes:
        content = note.read_text(encoding="utf-8", errors="replace")
        tasks = extract_tasks(content)
        pending = [t for t in tasks if not t["done"]]
        if pending:
            fm = parse_frontmatter(content)
            note_date = fm.get("date", "")
            for t in pending:
                all_tasks.append({
                    "file": note.relative_to(VAULT_ROOT),
                    "date": note_date,
                    "task": t["text"],
                })

    if not all_tasks:
        print("No pending tasks found.")
        return

    print(f"=== Pending Tasks ({len(all_tasks)}) ===\n")
    current_file = None
    for item in all_tasks:
        if item["file"] != current_file:
            current_file = item["file"]
            print(f"📄 {current_file} ({item['date']})")
        print(f"  - [ ] {item['task']}")


def cmd_action_items():
    """議事録からアクションアイテムを集約"""
    notes = iter_notes("MeetingNotes")
    items = []

    for note in notes:
        content = note.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(content)

        # アクションアイテムセクションを検出
        in_action = False
        for line in content.split("\n"):
            if re.match(r'^#+\s*アクションアイテム', line, re.IGNORECASE) or \
               re.match(r'^#+\s*Action\s*Item', line, re.IGNORECASE):
                in_action = True
                continue
            if in_action and re.match(r'^#+\s', line):
                in_action = False
                continue
            if in_action:
                m = re.match(r'\s*- \[([ xX])\]\s*(.*)', line)
                if m:
                    items.append({
                        "done": m.group(1) != " ",
                        "text": m.group(2).strip(),
                        "meeting": note.stem,
                        "date": fm.get("date", ""),
                    })

    pending = [i for i in items if not i["done"]]
    done = [i for i in items if i["done"]]

    print(f"=== Meeting Action Items ===")
    print(f"Pending: {len(pending)} | Completed: {len(done)}\n")

    if pending:
        print("--- Pending ---")
        for i in pending:
            print(f"  - [ ] {i['text']}  (from: {i['meeting']}, {i['date']})")

    if done:
        print("\n--- Completed ---")
        for i in done:
            print(f"  - [x] {i['text']}  (from: {i['meeting']}, {i['date']})")


def cmd_recent(days: int, fmt: str):
    """最近のノートを出力"""
    notes = iter_notes()
    cutoff = datetime.now() - timedelta(days=days)
    recent = []

    for note in notes:
        content = note.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(content)
        note_date = get_note_date(note, fm)
        if note_date and note_date >= cutoff:
            recent.append((note, fm, content))

    if not recent:
        print(f"No notes from the last {days} day(s).")
        return

    if fmt == "summary":
        # Claude向け要約用フォーマット
        print(f"以下は過去{days}日間の{len(recent)}件のノートです。\n")
        print("---\n")
        for note, fm, content in recent:
            # フロントマターを除いた本文の冒頭を出力
            body = re.sub(r'^---\s*\n.*?\n---\s*\n?', '', content, flags=re.DOTALL)
            preview = body[:1000].strip()
            print(f"## {note.relative_to(VAULT_ROOT)}")
            print(f"Type: {fm.get('type', 'unknown')} | Date: {fm.get('date', 'N/A')}")
            print(f"\n{preview}\n")
            print("---\n")
    else:
        print(f"=== Recent Notes (last {days} days): {len(recent)} ===\n")
        for note, fm, _ in recent:
            print(f"  {fm.get('date', '????-??-??')} [{fm.get('type', '?')}] {note.relative_to(VAULT_ROOT)}")


def cmd_weekly_report():
    """週次レポート用データを生成"""
    days = 7
    notes = iter_notes()
    cutoff = datetime.now() - timedelta(days=days)

    meetings = []
    research = []
    tasks_done = []
    tasks_pending = []

    for note in notes:
        content = note.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(content)
        note_date = get_note_date(note, fm)

        if not note_date or note_date < cutoff:
            continue

        note_type = fm.get("type", "unknown")
        if note_type == "meeting":
            meetings.append((note, fm))
        elif note_type == "research":
            research.append((note, fm))

        for task in extract_tasks(content):
            if task["done"]:
                tasks_done.append(task["text"])
            else:
                tasks_pending.append(task["text"])

    week_start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    week_end = datetime.now().strftime("%Y-%m-%d")

    print(f"=== Weekly Report ({week_start} ~ {week_end}) ===\n")

    print(f"## Meetings ({len(meetings)})")
    for note, fm in meetings:
        print(f"  - {fm.get('date', '')} {note.stem}")

    print(f"\n## Research ({len(research)})")
    for note, fm in research:
        print(f"  - {fm.get('date', '')} {note.stem}")

    print(f"\n## Tasks Completed ({len(tasks_done)})")
    for t in tasks_done:
        print(f"  - [x] {t}")

    print(f"\n## Tasks Pending ({len(tasks_pending)})")
    for t in tasks_pending:
        print(f"  - [ ] {t}")

    # Claude向けプロンプト用
    print(f"\n---")
    print(f"# Claude向け指示")
    print(f"上記の週次データをもとに、以下を生成してください:")
    print(f"1. 今週の活動サマリー（3-5行）")
    print(f"2. 主な成果と進捗")
    print(f"3. 来週に向けた推奨アクション")


def cmd_list(folder: str):
    """特定フォルダのノート一覧"""
    notes = iter_notes(folder)
    if not notes:
        print(f"No notes in {folder}/")
        return
    print(f"=== {folder} ({len(notes)} notes) ===\n")
    for note in notes:
        fm_content = note.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(fm_content)
        print(f"  {fm.get('date', '????-??-??')} {note.name}")


def main():
    parser = argparse.ArgumentParser(description="Analyze Obsidian Vault for Claude integration")
    parser.add_argument("--stats", action="store_true", help="Show vault statistics")
    parser.add_argument("--tasks", action="store_true", help="Extract pending tasks")
    parser.add_argument("--action-items", action="store_true", help="Aggregate meeting action items")
    parser.add_argument("--recent", type=int, metavar="DAYS", help="Show recent notes")
    parser.add_argument("--format", choices=["list", "summary"], default="list",
                        help="Output format for --recent")
    parser.add_argument("--weekly-report", action="store_true", help="Generate weekly report data")
    parser.add_argument("--list", metavar="FOLDER", help="List notes in folder")

    args = parser.parse_args()

    if args.stats:
        cmd_stats()
    elif args.tasks:
        cmd_tasks()
    elif args.action_items:
        cmd_action_items()
    elif args.recent:
        cmd_recent(args.recent, args.format)
    elif args.weekly_report:
        cmd_weekly_report()
    elif args.list:
        cmd_list(args.list)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
