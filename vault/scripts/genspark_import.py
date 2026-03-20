#!/usr/bin/env python3
"""
Gensparkなど外部リサーチツールの結果をObsidian Vaultに取り込むスクリプト。

使い方:
  # クリップボードからMarkdownを取り込み（macOS）
  pbpaste | python genspark_import.py --title "AI最新動向" --source "Genspark"

  # ファイルから取り込み
  python genspark_import.py --title "市場調査" --source "Genspark" --file exported.md

  # URLを指定してメタデータに記録
  python genspark_import.py --title "競合分析" --source "Genspark" --url "https://..." --file report.md

  # Genspark Sparkpage PDFからテキスト抽出して取り込み（要pdfplumber）
  python genspark_import.py --title "レポート" --source "Genspark" --pdf report.pdf
"""

import argparse
import sys
import os
from datetime import datetime
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_DIR = VAULT_ROOT / "Research"
INBOX_DIR = VAULT_ROOT / "00_Inbox"


def sanitize_filename(name: str) -> str:
    for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(ch, '_')
    return name.strip()


def extract_pdf_text(pdf_path: str) -> str:
    """PDFからテキストを抽出（pdfplumberが必要）"""
    try:
        import pdfplumber
    except ImportError:
        print("Error: pdfplumber is required for PDF import.")
        print("Install with: pip install pdfplumber")
        sys.exit(1)

    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
    return "\n\n".join(text_parts)


def build_note(title: str, content: str, source: str, url: str, tags: list) -> str:
    now = datetime.now()
    tag_str = ", ".join(tags)
    frontmatter = f"""---
type: research
date: "{now.strftime('%Y-%m-%d')}"
source: "{source}"
url: "{url}"
tags: [{tag_str}]
status: draft
imported_at: "{now.strftime('%Y-%m-%dT%H:%M:%S')}"
---"""

    body = f"\n# {title}\n\n"
    if url:
        body += f"> Source: [{source}]({url})\n\n"
    body += content + "\n"
    return frontmatter + body


def save_note(title: str, content: str, source: str, url: str, tags: list,
              dest: str = "research") -> Path:
    folder = RESEARCH_DIR if dest == "research" else INBOX_DIR
    folder.mkdir(parents=True, exist_ok=True)

    safe_title = sanitize_filename(title)
    now = datetime.now()
    filename = f"{now.strftime('%Y%m%d')}_{safe_title}.md"
    filepath = folder / filename

    counter = 1
    while filepath.exists():
        filepath = folder / f"{now.strftime('%Y%m%d')}_{safe_title}_{counter}.md"
        counter += 1

    note_content = build_note(title, content, source, url, tags)
    filepath.write_text(note_content, encoding="utf-8")
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="Import research from Genspark and other sources into Obsidian"
    )
    parser.add_argument("--title", "-t", required=True, help="Note title")
    parser.add_argument("--source", "-s", default="Genspark", help="Source name")
    parser.add_argument("--url", "-u", default="", help="Source URL")
    parser.add_argument("--file", "-f", help="Import from file (Markdown or text)")
    parser.add_argument("--pdf", help="Import from PDF file")
    parser.add_argument("--tags", default="research,genspark",
                        help="Comma-separated tags (default: research,genspark)")
    parser.add_argument("--dest", choices=["research", "inbox"], default="research",
                        help="Destination folder (default: research)")

    args = parser.parse_args()
    tags = [t.strip() for t in args.tags.split(",")]

    # Determine content source
    if args.pdf:
        content = extract_pdf_text(args.pdf)
    elif args.file:
        content = Path(args.file).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        content = sys.stdin.read()
    else:
        print("Error: Provide content via --file, --pdf, or stdin (pipe)")
        sys.exit(1)

    if not content.strip():
        print("Error: No content to import")
        sys.exit(1)

    filepath = save_note(args.title, content, args.source, args.url, tags, args.dest)
    print(f"Imported: {filepath}")
    print(f"  Title:  {args.title}")
    print(f"  Source: {args.source}")
    print(f"  Tags:   {', '.join(tags)}")


if __name__ == "__main__":
    main()
