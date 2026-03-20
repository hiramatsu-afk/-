#!/usr/bin/env python3
"""
Inboxの未整理ノートを一覧表示し、適切なフォルダへ移動するヘルパー。
Claude連携時に、このスクリプトの出力を元にファイルの分類・移動を指示できる。

使い方:
  python organize_inbox.py --list          # 未整理ノートの一覧
  python organize_inbox.py --move FILE DEST # ファイルを移動
"""

import argparse
import shutil
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parent.parent
INBOX = VAULT_ROOT / "00_Inbox"

DESTINATIONS = {
    "projects": VAULT_ROOT / "01_Projects",
    "areas": VAULT_ROOT / "02_Areas",
    "resources": VAULT_ROOT / "03_Resources",
    "archive": VAULT_ROOT / "04_Archive",
    "meeting": VAULT_ROOT / "MeetingNotes",
    "research": VAULT_ROOT / "Research",
}


def list_inbox():
    files = sorted(INBOX.glob("*.md"))
    if not files:
        print("Inbox is empty.")
        return
    print(f"Inbox items ({len(files)}):")
    for f in files:
        print(f"  - {f.name}")


def move_file(filename: str, destination: str):
    src = INBOX / filename
    if not src.exists():
        print(f"Error: {src} not found")
        return

    dest_dir = DESTINATIONS.get(destination)
    if not dest_dir:
        print(f"Error: Unknown destination '{destination}'. Use: {list(DESTINATIONS.keys())}")
        return

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    shutil.move(str(src), str(dest))
    print(f"Moved: {filename} -> {dest_dir.name}/")


def main():
    parser = argparse.ArgumentParser(description="Organize Obsidian inbox")
    parser.add_argument("--list", "-l", action="store_true", help="List inbox items")
    parser.add_argument("--move", "-m", nargs=2, metavar=("FILE", "DEST"),
                        help="Move file to destination folder")
    args = parser.parse_args()

    if args.list:
        list_inbox()
    elif args.move:
        move_file(args.move[0], args.move[1])
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
