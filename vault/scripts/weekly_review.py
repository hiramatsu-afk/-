#!/usr/bin/env python3
"""
週次レビュー自動生成スクリプト

毎週月曜に自動実行され、DailyNotesに以下を含むレビューノートを作成する:
  - 先週のアクションアイテム未完了一覧
  - Inbox内の未整理ノート一覧（推奨フォルダ提案付き）
  - 先週のミーティング・リサーチサマリー
  - 今週のチェックリスト

使い方:
  python weekly_review.py
  python weekly_review.py --dry-run
"""

import argparse
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = VAULT_ROOT / "DailyNotes"
INBOX_DIR = VAULT_ROOT / "00_Inbox"
MEETING_DIR = VAULT_ROOT / "MeetingNotes"
RESEARCH_DIR = VAULT_ROOT / "Research"
EXCLUDE_DIRS = {".obsidian", "scripts", "Templates", ".git"}


def parse_frontmatter(content):
    fm = {}
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if match:
        for line in match.group(1).split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                fm[key.strip()] = value.strip().strip('"').strip("'")
    return fm


def get_note_date(filepath, fm):
    date_str = fm.get("date", "")
    if date_str:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            pass
    m = re.match(r'(\d{8})_', filepath.name)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d")
        except ValueError:
            pass
    return None


def suggest_folder(note_path, content, fm):
    """ノートの内容から推奨フォルダを判定"""
    text = (content + " " + str(note_path.name)).lower()
    tags = fm.get("tags", "").lower()

    if "meeting" in tags or "議事録" in content[:200] or "アクションアイテム" in content:
        return "MeetingNotes/"
    if "research" in tags or "リサーチ" in text or "genspark" in text:
        return "Research/"
    if "project" in tags or "プロジェクト" in text[:300]:
        return "01_Projects/"
    if "archive" in tags or fm.get("status") == "completed":
        return "04_Archive/"
    return "03_Resources/"


def collect_review_data():
    now = datetime.now()
    last_week_start = now - timedelta(days=7)

    # Inbox内の未整理ノート
    inbox_items = []
    if INBOX_DIR.exists():
        for note in sorted(INBOX_DIR.glob("*.md")):
            content = note.read_text(encoding="utf-8", errors="replace")
            fm = parse_frontmatter(content)
            inbox_items.append({
                "name": note.name,
                "date": fm.get("date", ""),
                "suggested": suggest_folder(note, content, fm),
            })

    # 未完了アクションアイテム（全期間）
    pending_actions = []
    if MEETING_DIR.exists():
        for note in MEETING_DIR.glob("*.md"):
            content = note.read_text(encoding="utf-8", errors="replace")
            fm = parse_frontmatter(content)
            in_action = False
            for line in content.split("\n"):
                if re.match(r'^#+\s*(アクションアイテム|Action\s*Item)', line, re.IGNORECASE):
                    in_action = True
                    continue
                if in_action and re.match(r'^#+\s', line):
                    in_action = False
                    continue
                if in_action:
                    m = re.match(r'\s*- \[ \]\s*(.*)', line)
                    if m:
                        pending_actions.append({
                            "text": m.group(1).strip(),
                            "meeting": note.stem,
                            "date": fm.get("date", ""),
                        })

    # 先週のミーティング・リサーチ
    last_week_meetings = []
    last_week_research = []
    for folder, target in [(MEETING_DIR, last_week_meetings), (RESEARCH_DIR, last_week_research)]:
        if not folder.exists():
            continue
        for note in folder.glob("*.md"):
            content = note.read_text(encoding="utf-8", errors="replace")
            fm = parse_frontmatter(content)
            ndate = get_note_date(note, fm)
            if ndate and ndate >= last_week_start:
                target.append({"name": note.stem, "date": fm.get("date", "")})

    return {
        "inbox_items": inbox_items,
        "pending_actions": pending_actions,
        "last_week_meetings": sorted(last_week_meetings, key=lambda x: x["date"], reverse=True),
        "last_week_research": sorted(last_week_research, key=lambda x: x["date"], reverse=True),
    }


def build_review_note(data):
    now = datetime.now()
    week_num = now.isocalendar()[1]
    last_week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    last_week_end = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    frontmatter = f"""---
type: weekly-review
date: "{now.strftime('%Y-%m-%d')}"
week: {week_num}
tags: [weekly-review, auto-generated]
status: draft
generated_at: "{now.strftime('%Y-%m-%dT%H:%M:%S')}"
---"""

    body = f"\n# 週次レビュー Week {week_num} ({last_week_start} ~ {last_week_end})\n\n"

    body += "## 整理チェックリスト\n"
    body += "- [ ] Inboxの未整理ノートを適切なフォルダに移動\n"
    body += "- [ ] 未完了アクションアイテムを確認・更新\n"
    body += "- [ ] 完了したプロジェクトを04_Archiveに移動\n"
    body += "- [ ] 今週の重要タスクを01_Projectsに追加\n\n"

    body += f"## Inboxの未整理ノート ({len(data['inbox_items'])} 件)\n"
    if data["inbox_items"]:
        body += "以下のノートを適切なフォルダに移動してください:\n\n"
        for item in data["inbox_items"]:
            body += f"- [ ] `{item['name']}` → 推奨: `{item['suggested']}`\n"
    else:
        body += "Inboxは空です。\n"
    body += "\n"

    body += f"## 未完了アクションアイテム ({len(data['pending_actions'])} 件)\n"
    if data["pending_actions"]:
        for a in data["pending_actions"][:30]:
            body += f"- [ ] {a['text']} _(from: {a['meeting']}, {a['date']})_\n"
        if len(data["pending_actions"]) > 30:
            body += f"\n_他 {len(data['pending_actions']) - 30} 件_\n"
    else:
        body += "未完了アクションアイテムはありません。\n"
    body += "\n"

    body += f"## 先週のミーティング ({len(data['last_week_meetings'])} 件)\n"
    for m in data["last_week_meetings"]:
        body += f"- {m['date']} [[{m['name']}]]\n"
    body += "\n"

    body += f"## 先週のリサーチ ({len(data['last_week_research'])} 件)\n"
    for r in data["last_week_research"]:
        body += f"- {r['date']} [[{r['name']}]]\n"
    body += "\n"

    body += "## 今週の重点項目\n"
    body += "- [ ] \n- [ ] \n- [ ] \n\n"

    body += "## 振り返り・気づき\n\n"

    return frontmatter + body


def main():
    parser = argparse.ArgumentParser(description="Generate weekly review note")
    parser.add_argument("--dry-run", action="store_true", help="Print without saving")
    args = parser.parse_args()

    data = collect_review_data()
    note = build_review_note(data)

    now = datetime.now()
    week_num = now.isocalendar()[1]
    filename = f"{now.strftime('%Y%m%d')}_週次レビュー_W{week_num}.md"
    filepath = DAILY_DIR / filename

    if args.dry_run:
        print(note)
        print(f"\n[DRY RUN] Would save: {filepath}")
        return

    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    counter = 1
    while filepath.exists():
        filepath = DAILY_DIR / f"{now.strftime('%Y%m%d')}_週次レビュー_W{week_num}_{counter}.md"
        counter += 1

    filepath.write_text(note, encoding="utf-8")
    print(f"Weekly review saved: {filepath}")
    print(f"  Inbox items: {len(data['inbox_items'])}")
    print(f"  Pending actions: {len(data['pending_actions'])}")
    print(f"  Last week meetings: {len(data['last_week_meetings'])}")


if __name__ == "__main__":
    main()
