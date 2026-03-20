#!/usr/bin/env python3
"""
Obsidian Vaultへのコンテンツ自動保存スクリプト

使い方:
  python save_to_vault.py --type meeting --title "週次MTG" --content "議事内容..."
  python save_to_vault.py --type research --title "AI動向" --source "Genspark" --url "https://..."
  python save_to_vault.py --type inbox --title "メモ" --content "テキスト"
  cat file.txt | python save_to_vault.py --type inbox --title "取り込み"
"""

import argparse
import sys
import os
from datetime import datetime
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parent.parent

TYPE_CONFIG = {
    "meeting": {
        "folder": "MeetingNotes",
        "template": "meeting-note",
    },
    "research": {
        "folder": "Research",
        "template": "research-note",
    },
    "daily": {
        "folder": "DailyNotes",
        "template": "daily-note",
    },
    "inbox": {
        "folder": "00_Inbox",
        "template": "inbox-item",
    },
}


def sanitize_filename(name: str) -> str:
    for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(ch, '_')
    return name.strip()


def build_frontmatter(note_type: str, title: str, source: str = "", url: str = "") -> str:
    now = datetime.now()
    lines = [
        "---",
        f"type: {note_type}",
        f'date: "{now.strftime("%Y-%m-%d")}"',
    ]
    if note_type == "meeting":
        lines.append(f'time: "{now.strftime("%H:%M")}"')
        lines.append("attendees: []")
        lines.append("tags: [meeting]")
    elif note_type == "research":
        lines.append(f'source: "{source}"')
        lines.append(f'url: "{url}"')
        lines.append("tags: [research]")
    elif note_type == "daily":
        lines.append("tags: [daily]")
    else:
        lines.append(f'source: "{source}"')
        lines.append("tags: [inbox, unprocessed]")
    lines.append("status: draft")
    lines.append("---")
    return "\n".join(lines)


def save_note(note_type: str, title: str, content: str,
              source: str = "", url: str = "") -> Path:
    config = TYPE_CONFIG.get(note_type)
    if not config:
        raise ValueError(f"Unknown type: {note_type}. Use: {list(TYPE_CONFIG.keys())}")

    folder = VAULT_ROOT / config["folder"]
    folder.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    if note_type == "daily":
        filename = f"{now.strftime('%Y-%m-%d')}.md"
    else:
        safe_title = sanitize_filename(title)
        filename = f"{now.strftime('%Y%m%d')}_{safe_title}.md"

    filepath = folder / filename

    # Avoid overwriting — append a suffix if file exists
    counter = 1
    while filepath.exists():
        stem = filepath.stem
        filepath = folder / f"{stem}_{counter}.md"
        counter += 1

    frontmatter = build_frontmatter(note_type, title, source, url)
    body = f"\n# {title}\n\n{content}\n"

    filepath.write_text(frontmatter + body, encoding="utf-8")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Save content to Obsidian vault")
    parser.add_argument("--type", "-t", required=True,
                        choices=list(TYPE_CONFIG.keys()),
                        help="Note type")
    parser.add_argument("--title", required=True, help="Note title")
    parser.add_argument("--content", "-c", default="", help="Note content")
    parser.add_argument("--source", "-s", default="", help="Source (e.g. Genspark)")
    parser.add_argument("--url", "-u", default="", help="Source URL")

    args = parser.parse_args()

    # Read from stdin if no content provided
    content = args.content
    if not content and not sys.stdin.isatty():
        content = sys.stdin.read()

    filepath = save_note(args.type, args.title, content, args.source, args.url)
    print(f"Saved: {filepath}")


if __name__ == "__main__":
    main()
