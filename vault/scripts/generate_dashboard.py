#!/usr/bin/env python3
"""
Obsidian Vault のHTMLダッシュボードを生成する。

使い方:
  python generate_dashboard.py
  python generate_dashboard.py --open   # 生成後にブラウザで自動的に開く
  python generate_dashboard.py --port 8080  # ローカルサーバーで起動

生成先: vault/dashboard.html
"""

import argparse
import html
import json
import re
import sys
import webbrowser
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os

VAULT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_FILE = VAULT_ROOT / "dashboard.html"
EXCLUDE_DIRS = {".obsidian", "scripts", "Templates", ".git"}


def iter_notes(folder=None):
    search_root = VAULT_ROOT / folder if folder else VAULT_ROOT
    notes = []
    for md in search_root.rglob("*.md"):
        if any(part in EXCLUDE_DIRS for part in md.relative_to(VAULT_ROOT).parts):
            continue
        notes.append(md)
    return sorted(notes, key=lambda p: p.stat().st_mtime, reverse=True)


def parse_frontmatter(content):
    fm = {}
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if match:
        for line in match.group(1).split("\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                fm[key.strip()] = value.strip().strip('"').strip("'")
    return fm


def get_body(content):
    return re.sub(r'^---\s*\n.*?\n---\s*\n?', '', content, flags=re.DOTALL)


def extract_tasks(content):
    tasks = []
    for line in content.split("\n"):
        m = re.match(r'\s*- \[([ xX])\]\s*(.*)', line)
        if m:
            tasks.append({"done": m.group(1) != " ", "text": m.group(2).strip()})
    return tasks


def extract_section(content, header_pattern):
    lines = []
    in_section = False
    for line in content.split("\n"):
        if re.match(header_pattern, line, re.IGNORECASE):
            in_section = True
            continue
        if in_section and re.match(r'^#+\s', line):
            break
        if in_section and line.strip():
            lines.append(line.strip())
    return lines


def collect_data():
    all_notes = iter_notes()
    meetings = []
    research_notes = []
    action_items = []
    attendee_counter = Counter()
    type_counter = Counter()
    tag_counter = Counter()

    for note in all_notes:
        content = note.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(content)
        body = get_body(content)
        note_type = fm.get("type", "unknown")
        type_counter[note_type] += 1
        rel_path = str(note.relative_to(VAULT_ROOT))

        for tag in re.findall(r'[\w-]+', fm.get("tags", "")):
            tag_counter[tag] += 1

        if note_type == "meeting":
            highlights = extract_section(content, r'^#+\s*(ハイライト|要点|Highlights)')
            action_section = extract_section(content, r'^#+\s*(アクションアイテム|Action\s*Item)')

            attendees_str = fm.get("attendees", "")
            attendee_names = re.findall(r'"([^"]+)"', attendees_str)
            for name in attendee_names:
                attendee_counter[name] += 1

            meeting_actions = []
            for line in action_section:
                m = re.match(r'- \[([ xX])\]\s*(.*)', line)
                if m:
                    item = {"done": m.group(1) != " ", "text": m.group(2).strip(),
                            "meeting": note.stem, "date": fm.get("date", "")}
                    meeting_actions.append(item)
                    action_items.append(item)

            meetings.append({
                "title": note.stem,
                "date": fm.get("date", ""),
                "time": fm.get("time", ""),
                "platform": fm.get("platform", ""),
                "tldv_url": fm.get("tldv_url", ""),
                "attendees": attendee_names,
                "highlights": highlights[:6],
                "actions": meeting_actions,
                "path": rel_path,
                "body_preview": body[:500],
            })

        elif note_type == "research":
            research_notes.append({
                "title": note.stem,
                "date": fm.get("date", ""),
                "source": fm.get("source", ""),
                "url": fm.get("url", ""),
                "path": rel_path,
                "body_preview": body[:500],
            })

    meetings.sort(key=lambda x: x["date"], reverse=True)
    research_notes.sort(key=lambda x: x["date"], reverse=True)

    return {
        "meetings": meetings,
        "research": research_notes,
        "action_items": action_items,
        "attendee_counter": attendee_counter.most_common(15),
        "type_counter": dict(type_counter),
        "tag_counter": tag_counter.most_common(20),
        "total_notes": len(all_notes),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def generate_html(data):
    pending = [a for a in data["action_items"] if not a["done"]]
    done = [a for a in data["action_items"] if a["done"]]

    # Meeting cards
    meeting_cards = ""
    for m in data["meetings"]:
        platform_badge = f'<span class="badge platform">{html.escape(m["platform"])}</span>' if m["platform"] else ""
        attendee_tags = "".join(f'<span class="badge attendee">{html.escape(a)}</span>' for a in m["attendees"])
        highlights_html = "".join(f"<li>{html.escape(h)}</li>" for h in m["highlights"] if h.startswith("- "))
        if not highlights_html:
            highlights_html = "".join(f"<li>{html.escape(h)}</li>" for h in m["highlights"])

        actions_html = ""
        for a in m["actions"]:
            checked = "checked disabled" if a["done"] else ""
            cls = "done" if a["done"] else ""
            actions_html += f'<li class="{cls}"><input type="checkbox" {checked}> {html.escape(a["text"])}</li>'

        tldv_link = f'<a href="{html.escape(m["tldv_url"])}" target="_blank" class="tldv-link">tl;dv</a>' if m["tldv_url"] else ""

        meeting_cards += f"""
        <div class="card meeting-card" data-search="{html.escape((m['title'] + ' ' + ' '.join(m['attendees']) + ' ' + ' '.join(m['highlights'])).lower())}">
          <div class="card-header">
            <span class="card-date">{html.escape(m['date'])} {html.escape(m['time'])}</span>
            {platform_badge} {tldv_link}
          </div>
          <h3>{html.escape(m['title'].replace('_', ' '))}</h3>
          <div class="attendees">{attendee_tags}</div>
          <div class="highlights">
            <h4>Key Points</h4>
            <ul>{highlights_html}</ul>
          </div>
          {'<div class="actions"><h4>Action Items</h4><ul>' + actions_html + '</ul></div>' if actions_html else ''}
        </div>"""

    # Research cards
    research_cards = ""
    for r in data["research"]:
        source_link = f'<a href="{html.escape(r["url"])}" target="_blank">{html.escape(r["source"])}</a>' if r["url"] else html.escape(r["source"])
        preview = html.escape(r["body_preview"][:300])
        research_cards += f"""
        <div class="card research-card" data-search="{html.escape((r['title'] + ' ' + r['source'] + ' ' + r['body_preview']).lower())}">
          <div class="card-header">
            <span class="card-date">{html.escape(r['date'])}</span>
            <span class="badge source">{source_link}</span>
          </div>
          <h3>{html.escape(r['title'].replace('_', ' '))}</h3>
          <p class="preview">{preview}...</p>
        </div>"""

    # Pending actions
    pending_html = ""
    for a in pending:
        pending_html += f'<li><input type="checkbox"> {html.escape(a["text"])} <span class="action-source">from {html.escape(a["meeting"])} ({html.escape(a["date"])})</span></li>'

    # Attendee list
    attendee_list = ""
    for name, count in data["attendee_counter"]:
        attendee_list += f'<li><strong>{html.escape(name)}</strong> <span class="count">{count} meetings</span></li>'

    # Stats
    type_stats = "".join(f"<li>{html.escape(k)}: <strong>{v}</strong></li>" for k, v in data["type_counter"].items())
    tag_badges = "".join(f'<span class="badge tag">#{html.escape(t)} ({c})</span>' for t, c in data["tag_counter"][:12])

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Obsidian Vault Dashboard</title>
<style>
  :root {{
    --bg: #1a1b26; --surface: #24283b; --surface2: #2f3347;
    --text: #c0caf5; --text2: #9aa5ce; --accent: #7aa2f7;
    --green: #9ece6a; --orange: #ff9e64; --red: #f7768e;
    --purple: #bb9af7; --cyan: #7dcfff;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }}

  .header {{ background: var(--surface); padding: 20px 30px; border-bottom: 1px solid var(--surface2); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px; }}
  .header h1 {{ font-size: 1.4em; color: var(--accent); }}
  .header .meta {{ color: var(--text2); font-size: 0.85em; }}

  .search-bar {{ padding: 15px 30px; background: var(--surface); border-bottom: 1px solid var(--surface2); position: sticky; top: 0; z-index: 100; }}
  .search-bar input {{ width: 100%; padding: 12px 18px; border-radius: 8px; border: 1px solid var(--surface2); background: var(--bg); color: var(--text); font-size: 1em; outline: none; }}
  .search-bar input:focus {{ border-color: var(--accent); }}
  .search-bar input::placeholder {{ color: var(--text2); }}

  .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}

  .stats-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 15px; margin-bottom: 25px; }}
  .stat-card {{ background: var(--surface); padding: 18px; border-radius: 10px; text-align: center; }}
  .stat-card .number {{ font-size: 2em; font-weight: bold; color: var(--accent); }}
  .stat-card .label {{ font-size: 0.85em; color: var(--text2); margin-top: 4px; }}

  .tabs {{ display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }}
  .tab {{ padding: 8px 18px; border-radius: 20px; background: var(--surface); color: var(--text2); cursor: pointer; border: 1px solid transparent; font-size: 0.9em; transition: all 0.2s; }}
  .tab:hover {{ border-color: var(--accent); }}
  .tab.active {{ background: var(--accent); color: var(--bg); font-weight: 600; }}

  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}

  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 18px; }}

  .card {{ background: var(--surface); border-radius: 12px; padding: 20px; border: 1px solid var(--surface2); transition: border-color 0.2s; }}
  .card:hover {{ border-color: var(--accent); }}
  .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; flex-wrap: wrap; gap: 6px; }}
  .card-date {{ font-size: 0.85em; color: var(--text2); }}
  .card h3 {{ font-size: 1.05em; margin-bottom: 10px; color: var(--text); word-break: break-word; }}

  .badge {{ display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.75em; font-weight: 500; }}
  .badge.platform {{ background: var(--purple); color: var(--bg); }}
  .badge.attendee {{ background: var(--surface2); color: var(--cyan); margin: 2px; }}
  .badge.source {{ background: var(--orange); color: var(--bg); }}
  .badge.source a {{ color: var(--bg); text-decoration: none; }}
  .badge.tag {{ background: var(--surface2); color: var(--green); margin: 3px; }}

  .tldv-link {{ font-size: 0.8em; color: var(--accent); text-decoration: none; padding: 2px 8px; border: 1px solid var(--accent); border-radius: 8px; }}

  .highlights h4, .actions h4 {{ font-size: 0.85em; color: var(--text2); margin: 10px 0 6px; }}
  .highlights ul, .actions ul {{ list-style: none; padding: 0; }}
  .highlights li {{ padding: 3px 0; font-size: 0.9em; border-left: 3px solid var(--accent); padding-left: 10px; margin-bottom: 4px; }}
  .actions li {{ padding: 4px 0; font-size: 0.88em; }}
  .actions li.done {{ color: var(--text2); text-decoration: line-through; }}
  .action-source {{ font-size: 0.78em; color: var(--text2); display: block; margin-top: 2px; }}

  .preview {{ font-size: 0.88em; color: var(--text2); }}

  .sidebar-section {{ background: var(--surface); border-radius: 12px; padding: 20px; margin-bottom: 18px; border: 1px solid var(--surface2); }}
  .sidebar-section h3 {{ font-size: 1em; color: var(--accent); margin-bottom: 12px; }}
  .sidebar-section ul {{ list-style: none; padding: 0; }}
  .sidebar-section li {{ padding: 5px 0; font-size: 0.9em; border-bottom: 1px solid var(--surface2); }}
  .sidebar-section li:last-child {{ border-bottom: none; }}
  .count {{ color: var(--text2); font-size: 0.85em; }}

  .two-col {{ display: grid; grid-template-columns: 1fr 320px; gap: 25px; }}
  @media (max-width: 900px) {{
    .two-col {{ grid-template-columns: 1fr; }}
    .grid {{ grid-template-columns: 1fr; }}
  }}

  .hidden {{ display: none !important; }}
</style>
</head>
<body>

<div class="header">
  <h1>Obsidian Vault Dashboard</h1>
  <div class="meta">Updated: {data['generated_at']} | {data['total_notes']} notes</div>
</div>

<div class="search-bar">
  <input type="text" id="searchInput" placeholder="Search meetings, attendees, keywords... (e.g. A社, 価格, 田中)">
</div>

<div class="container">
  <div class="stats-row">
    <div class="stat-card"><div class="number">{len(data['meetings'])}</div><div class="label">Meetings</div></div>
    <div class="stat-card"><div class="number">{len(data['research'])}</div><div class="label">Research Notes</div></div>
    <div class="stat-card"><div class="number">{len(pending)}</div><div class="label">Pending Actions</div></div>
    <div class="stat-card"><div class="number">{len(done)}</div><div class="label">Completed</div></div>
    <div class="stat-card"><div class="number">{data['total_notes']}</div><div class="label">Total Notes</div></div>
  </div>

  <div class="tabs">
    <div class="tab active" data-tab="meetings">Meetings</div>
    <div class="tab" data-tab="research">Research</div>
    <div class="tab" data-tab="actions">Action Items</div>
    <div class="tab" data-tab="overview">Overview</div>
  </div>

  <div class="tab-content active" id="tab-meetings">
    <div class="two-col">
      <div class="grid" id="meetingGrid">{meeting_cards}</div>
      <div>
        <div class="sidebar-section">
          <h3>Frequent Attendees</h3>
          <ul>{attendee_list}</ul>
        </div>
      </div>
    </div>
  </div>

  <div class="tab-content" id="tab-research">
    <div class="grid" id="researchGrid">{research_cards}</div>
  </div>

  <div class="tab-content" id="tab-actions">
    <div class="two-col">
      <div class="sidebar-section">
        <h3>Pending ({len(pending)})</h3>
        <ul>{pending_html}</ul>
      </div>
      <div class="sidebar-section">
        <h3>Stats</h3>
        <ul>{type_stats}</ul>
        <div style="margin-top: 15px;">{tag_badges}</div>
      </div>
    </div>
  </div>

  <div class="tab-content" id="tab-overview">
    <div class="stats-row">
      <div class="sidebar-section"><h3>By Type</h3><ul>{type_stats}</ul></div>
      <div class="sidebar-section"><h3>Tags</h3><div>{tag_badges}</div></div>
      <div class="sidebar-section"><h3>Attendees</h3><ul>{attendee_list}</ul></div>
    </div>
  </div>
</div>

<script>
// Tab switching
document.querySelectorAll('.tab').forEach(tab => {{
  tab.addEventListener('click', () => {{
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
  }});
}});

// Live search
const searchInput = document.getElementById('searchInput');
searchInput.addEventListener('input', () => {{
  const q = searchInput.value.toLowerCase().trim();
  document.querySelectorAll('.card').forEach(card => {{
    const text = card.dataset.search || card.textContent.toLowerCase();
    card.classList.toggle('hidden', q && !text.includes(q));
  }});
}});
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate Obsidian Vault HTML Dashboard")
    parser.add_argument("--open", "-o", action="store_true", help="Open in browser after generating")
    parser.add_argument("--port", "-p", type=int, help="Start a local server on this port")
    args = parser.parse_args()

    print("Collecting vault data...")
    data = collect_data()

    print("Generating dashboard...")
    html_content = generate_html(data)
    OUTPUT_FILE.write_text(html_content, encoding="utf-8")
    print(f"Dashboard saved: {OUTPUT_FILE}")

    if args.port:
        os.chdir(str(VAULT_ROOT))
        print(f"\nServing at http://localhost:{args.port}/dashboard.html")
        print("Press Ctrl+C to stop.\n")
        httpd = HTTPServer(("", args.port), SimpleHTTPRequestHandler)
        webbrowser.open(f"http://localhost:{args.port}/dashboard.html")
        httpd.serve_forever()
    elif args.open:
        webbrowser.open(str(OUTPUT_FILE))


if __name__ == "__main__":
    main()
